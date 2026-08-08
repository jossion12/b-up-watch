"""重新为所有 UP 主执行完整的 RagFlow 流程。

用法：
    cd backend
    python scripts/rebuild_ragflow_all_ups.py

执行步骤：
1. 重置所有 Uploader 的 ragflow_dataset_id / ragflow_chat_id（因为 RagFlow 侧知识库已被清空）
2. 删除本地语料目录下的 .ragflow-sync.json 同步状态文件
3. 为所有 has_subtitle=true 的视频重新生成 RagFlow 语料
4. 依次调用 sync_uploader_to_ragflow 将每位 UP 主的语料同步到 RagFlow

注意：
- 要求 .env 中 RAGFLOW_SYNC_ENABLED=true 且 RagFlow 服务可访问。
- 第 4 步会逐个文件上传并等待解析完成，耗时较长，请耐心等候。
- 运行前请确保 RagFlow 知识库确实已被清空；本脚本不会主动删除 RagFlow 侧资源。
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import sys
from pathlib import Path

# 把 backend 目录加入模块搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows cmd/powershell 默认编码可能不是 utf-8，强制 stdout/stderr 用 utf-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from sqlalchemy import select

from app.collect.corpus import get_corpus_dir
from app.config import get_settings
from app.db import SessionLocal
from app.models import Uploader
from app.rag.ragflow_sync import sync_uploader_to_ragflow

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("rebuild_ragflow")


def _reset_uploader_ragflow_ids(db) -> list[Uploader]:
    """清空所有 Uploader 的 RagFlow dataset/chat ID。"""
    ups = db.execute(select(Uploader)).scalars().all()
    for up in ups:
        if up.ragflow_dataset_id or up.ragflow_chat_id:
            log.info("reset ragflow ids for uploader=%s name=%s", up.id, up.name)
            up.ragflow_dataset_id = None
            up.ragflow_chat_id = None
    db.commit()
    return ups


def _clear_sync_state_files() -> int:
    """删除所有 .ragflow-sync.json 状态文件。"""
    corpus_dir = get_corpus_dir()
    removed = 0
    if not corpus_dir.exists():
        return removed
    for path in corpus_dir.rglob(".ragflow-sync.json"):
        try:
            path.unlink()
            removed += 1
            log.info("removed sync state: %s", path)
        except Exception as exc:
            log.warning("failed to remove %s: %s", path, exc)
    return removed


def _generate_corpus() -> None:
    """调用 generate_corpus.py 的主函数重新生成语料。"""
    import scripts.generate_corpus as generate_corpus

    log.info("=== start corpus generation ===")
    generate_corpus.main()
    log.info("=== corpus generation finished ===")


async def _sync_all_uploaders(ups: list[Uploader]) -> dict:
    """依次同步所有 UP 主。"""
    summary = {
        "total": len(ups),
        "success": 0,
        "failed": 0,
        "details": [],
    }

    for idx, up in enumerate(ups, 1):
        log.info("=== [%d/%d] syncing uploader=%s name=%s ===", idx, len(ups), up.id, up.name)
        try:
            with SessionLocal() as db:
                # 重新加载 uploader，避免会话过期
                up = db.get(Uploader, up.id)
                if up is None:
                    raise RuntimeError("UP主不存在")
                result = await sync_uploader_to_ragflow(db, up)
                db.commit()
                detail = {
                    "id": up.id,
                    "name": up.name,
                    "status": "success",
                    "dataset_id": result.dataset_id,
                    "chat_id": result.chat_id,
                    "uploaded": result.uploaded,
                    "replaced": result.replaced,
                    "skipped": result.skipped,
                    "failed": result.failed,
                    "errors": result.errors,
                }
                summary["success"] += 1
                log.info(
                    "sync success: up=%s dataset=%s chat=%s uploaded=%s replaced=%s skipped=%s failed=%s",
                    up.id,
                    result.dataset_id,
                    result.chat_id,
                    result.uploaded,
                    result.replaced,
                    result.skipped,
                    result.failed,
                )
        except Exception as exc:
            detail = {
                "id": up.id,
                "name": up.name,
                "status": "failed",
                "error": str(exc),
            }
            summary["failed"] += 1
            log.exception("sync failed for uploader=%s name=%s", up.id, up.name)
        summary["details"].append(detail)

    return summary


async def main() -> None:
    settings = get_settings()

    if not settings.ragflow_corpus_enabled:
        print("RAGFLOW_CORPUS_ENABLED=false，语料生成已禁用。请在 .env 中设置为 true 后重试。")
        return

    if not settings.ragflow_sync_enabled:
        print("RAGFLOW_SYNC_ENABLED=false，RagFlow 同步已禁用。请在 .env 中设置为 true 后重试。")
        return

    if not settings.ragflow_base_url or not settings.ragflow_api_key:
        print("RAGFLOW_BASE_URL 或 RAGFLOW_API_KEY 未配置，无法同步。")
        return

    with SessionLocal() as db:
        ups = _reset_uploader_ragflow_ids(db)
        log.info("found %d uploaders, reset ragflow ids", len(ups))

    removed_states = _clear_sync_state_files()
    log.info("cleared %d .ragflow-sync.json files", removed_states)

    _generate_corpus()

    summary = await _sync_all_uploaders(ups)

    print("\n====================")
    print("RagFlow 重建完成")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
