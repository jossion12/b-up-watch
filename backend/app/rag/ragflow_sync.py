"""UP 主语料同步到 RagFlow 的业务逻辑。

职责：
- 按 UP 主获取/创建 RagFlow 知识库
- 对比本地语料文件与 RagFlow 已有文档，增量/变更上传
- 启动解析并轮询到完成
- 创建/更新聊天助手并关联知识库
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.collect.corpus import _sanitize_filename, clear_ragflow_corpus, get_corpus_dir
from app.errors import BizError
from app.models import Uploader
from app.rag.ragflow_client import RagFlowClient, RagFlowError
from app.schemas import build_ragflow_chat_url

log = logging.getLogger(__name__)


# RagFlow 文档状态映射（文本）
_DOC_RUN_DONE = "DONE"
_DOC_RUN_FAIL = "FAIL"
_DOC_RUN_CANCEL = "CANCEL"


@dataclass
class SyncResult:
    """一次同步任务的结果统计。"""

    dataset_id: Optional[str] = None
    chat_id: Optional[str] = None
    uploaded: int = 0
    replaced: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def to_meta(self) -> dict:
        return {
            "dataset_id": self.dataset_id,
            "chat_id": self.chat_id,
            "uploaded": self.uploaded,
            "replaced": self.replaced,
            "skipped": self.skipped,
            "failed": self.failed,
            "errors": self.errors,
        }


def _file_hash(path: Path) -> str:
    """计算文件 sha256。"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_sync_state_path(up_dir: Path) -> Path:
    """本地同步状态文件路径，用于记录每个语料文件的上次上传 hash。"""
    return up_dir / ".ragflow-sync.json"


def _load_sync_state(up_dir: Path) -> dict:
    """读取本地同步状态。"""
    path = _get_sync_state_path(up_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("failed to load ragflow sync state: %s", exc)
        return {}


def _save_sync_state(up_dir: Path, state: dict) -> None:
    """保存本地同步状态。"""
    path = _get_sync_state_path(up_dir)
    try:
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        log.warning("failed to save ragflow sync state: %s", exc)


def _up_corpus_dir(up: Uploader) -> Path:
    """返回指定 UP 主的本地语料目录。"""
    return get_corpus_dir() / _sanitize_filename(up.name)


def _find_local_corpus_files(up_dir: Path) -> list[Path]:
    """列出本地语料目录下所有 .md 文件。"""
    if not up_dir.exists():
        return []
    return sorted([p for p in up_dir.glob("*.md") if p.is_file()])


def _make_dataset_name(up: Uploader) -> str:
    """生成 RagFlow 知识库名称。"""
    return _sanitize_filename(up.name)


def _make_chat_name(up: Uploader) -> str:
    """生成 RagFlow 聊天助手名称。"""
    return f"{up.name}-助手"


async def _ensure_dataset(client: RagFlowClient, up: Uploader) -> str:
    """确保 UP 主对应的知识库存在，返回 dataset_id。"""
    settings = get_settings()
    name = _make_dataset_name(up)
    dataset = await client.get_or_create_dataset(
        name,
        embedding_model=settings.ragflow_embedding_model,
        chunk_method=settings.ragflow_chunk_method,
        dataset_id=up.ragflow_dataset_id,
    )
    dataset_id = dataset["id"]
    if up.ragflow_dataset_id != dataset_id:
        up.ragflow_dataset_id = dataset_id
    return dataset_id


def _should_replace(
    local_path: Path,
    local_hash: str,
    doc: dict,
    state: dict,
) -> bool:
    """判断是否需要删除旧文档并重新上传。

    逻辑：
    - 本地状态记录了上次上传 hash，且与当前 hash 不同 → 需要替换
    - 本地状态不存在：用文件大小兜底，大小不同 → 需要替换
    """
    file_name = local_path.name
    last_hash = state.get(file_name)
    if last_hash is not None:
        return last_hash != local_hash
    # 无状态记录时，用文件大小作为保守判断
    local_size = local_path.stat().st_size
    doc_size = doc.get("size", 0)
    return local_size != doc_size


async def _upload_or_replace(
    client: RagFlowClient,
    dataset_id: str,
    local_path: Path,
    existing_docs: dict[str, dict],
    state: dict,
    result: SyncResult,
) -> None:
    """处理单个语料文件的上传或替换。"""
    file_name = local_path.name
    local_hash = _file_hash(local_path)
    doc = existing_docs.get(file_name)

    if doc is None:
        # 新文件，直接上传
        try:
            upload_result = await client.upload_document(dataset_id, local_path)
            docs = upload_result if isinstance(upload_result, list) else [upload_result]
            doc_id = docs[0].get("id") if docs else None
            if doc_id:
                result.uploaded += 1
                log.info(
                    "uploaded corpus to ragflow: up=%s file=%s doc_id=%s",
                    dataset_id,
                    file_name,
                    doc_id,
                )
            else:
                result.failed += 1
                result.errors.append(f"上传 {file_name} 未返回 document_id")
        except RagFlowError as exc:
            result.failed += 1
            result.errors.append(f"上传 {file_name} 失败: {exc.message}")
        return

    # 文件已存在，检查内容是否变化
    if not _should_replace(local_path, local_hash, doc, state):
        result.skipped += 1
        state[file_name] = local_hash
        return

    # 删除旧文档并重新上传
    doc_id = doc.get("id")
    try:
        if doc_id:
            await client.delete_documents(dataset_id, [doc_id])
        upload_result = await client.upload_document(dataset_id, local_path)
        docs = upload_result if isinstance(upload_result, list) else [upload_result]
        new_doc_id = docs[0].get("id") if docs else None
        if new_doc_id:
            result.replaced += 1
            log.info(
                "replaced corpus in ragflow: up=%s file=%s old_doc=%s new_doc=%s",
                dataset_id,
                file_name,
                doc_id,
                new_doc_id,
            )
        else:
            result.failed += 1
            result.errors.append(f"替换 {file_name} 未返回 document_id")
    except RagFlowError as exc:
        result.failed += 1
        result.errors.append(f"替换 {file_name} 失败: {exc.message}")


async def _parse_and_wait(
    client: RagFlowClient,
    dataset_id: str,
    document_ids: list[str],
    up: Uploader,
) -> None:
    """启动解析并轮询到全部完成或失败。"""
    if not document_ids:
        return

    settings = get_settings()
    timeout = settings.ragflow_parse_timeout_sec
    interval = settings.ragflow_parse_poll_interval_sec
    await client.parse_documents(dataset_id, document_ids)

    pending = set(document_ids)
    start = asyncio.get_event_loop().time()
    while pending:
        if asyncio.get_event_loop().time() - start > timeout:
            raise BizError(
                "RAGFLOW_PARSE_TIMEOUT",
                f"RagFlow 文档解析超时，未完成的文档: {pending}",
                http_status=504,
            )

        await asyncio.sleep(interval)
        still_pending: set[str] = set()
        for doc_id in pending:
            try:
                doc = await client.get_document(dataset_id, doc_id)
                run_status = (doc.get("run") or "").upper()
                name = doc.get("name", doc_id)
                if run_status == _DOC_RUN_DONE:
                    log.info("ragflow parse done: %s", name)
                elif run_status == _DOC_RUN_FAIL:
                    raise BizError(
                        "RAGFLOW_PARSE_FAILED",
                        f"文档解析失败: {name}",
                        http_status=502,
                    )
                elif run_status == _DOC_RUN_CANCEL:
                    raise BizError(
                        "RAGFLOW_PARSE_CANCELLED",
                        f"文档解析被取消: {name}",
                        http_status=502,
                    )
                else:
                    still_pending.add(doc_id)
            except RagFlowError as exc:
                log.warning("failed to poll document %s: %s", doc_id, exc.message)
                still_pending.add(doc_id)
        pending = still_pending


async def _ensure_chat(
    client: RagFlowClient,
    up: Uploader,
    dataset_id: str,
) -> str:
    """确保 UP 主对应的聊天助手存在并关联知识库，返回 chat_id。"""
    chat_name = _make_chat_name(up)
    chat_id = up.ragflow_chat_id

    if chat_id:
        try:
            await client.update_chat(chat_id, dataset_ids=[dataset_id])
            up.ragflow_chat_url = build_ragflow_chat_url(chat_id)
            return chat_id
        except RagFlowError as exc:
            log.warning(
                "failed to update existing ragflow chat %s: %s, will recreate",
                chat_id,
                exc.message,
            )

    chats = await client.list_chats(name=chat_name)
    if chats:
        chat = chats[0]
        chat_id = chat["id"]
        # 确保关联当前 dataset
        await client.update_chat(chat_id, dataset_ids=[dataset_id])
    else:
        chat = await client.create_chat(
            name=chat_name,
            dataset_ids=[dataset_id],
        )
        chat_id = chat["id"]

    up.ragflow_chat_id = chat_id
    up.ragflow_chat_url = build_ragflow_chat_url(chat_id)
    return chat_id


async def sync_uploader_to_ragflow(
    db: Session,
    up: Uploader,
    on_progress: Optional[callable] = None,
) -> SyncResult:
    """将某位 UP 主的本地语料同步到 RagFlow。

    Args:
        db: 数据库会话
        up: UP 主对象
        on_progress: 进度回调，接收 0-100 整数

    Returns:
        SyncResult 包含同步统计与 dataset/chat ID
    """
    settings = get_settings()
    if not settings.ragflow_sync_enabled:
        raise BizError(
            "RAGFLOW_SYNC_DISABLED",
            "RagFlow 同步未启用",
            http_status=500,
        )

    result = SyncResult()
    async with RagFlowClient() as client:
        # 1. 确保知识库
        dataset_id = await _ensure_dataset(client, up)
        result.dataset_id = dataset_id

        # 2. 列出已有文档
        up_dir = _up_corpus_dir(up)
        local_files = _find_local_corpus_files(up_dir)
        remote_docs = await client.list_documents(dataset_id)
        existing_docs: dict[str, dict] = {
            doc.get("name"): doc for doc in remote_docs if doc.get("name")
        }
        state = _load_sync_state(up_dir)

        # 3. 遍历本地文件，上传或替换
        new_doc_ids: list[str] = []
        total = len(local_files)
        for i, local_path in enumerate(local_files):
            await _upload_or_replace(
                client,
                dataset_id,
                local_path,
                existing_docs,
                state,
                result,
            )
            # 如果刚上传/替换成功，记录新 hash 并在后续解析中跟踪
            file_name = local_path.name
            if file_name in state:
                # 已更新状态，说明发生了上传/替换或跳过
                pass
            # 从 existing_docs 中移除已处理的文件，剩余的就是本地已不存在的远端文件
            existing_docs.pop(file_name, None)

            if on_progress is not None and total > 0:
                on_progress(int((i + 1) / total * 50))

        # 4. 清理 RagFlow 中本地已不存在的旧文档（可选，保持两端一致）
        orphan_ids = [doc.get("id") for doc in existing_docs.values() if doc.get("id")]
        if orphan_ids:
            try:
                await client.delete_documents(dataset_id, orphan_ids)
                log.info("deleted orphan ragflow documents: %d", len(orphan_ids))
            except RagFlowError as exc:
                log.warning("failed to delete orphan documents: %s", exc.message)
                result.errors.append(f"清理远端孤立文档失败: {exc.message}")

        # 5. 收集需要解析的文档 ID
        # 重新列出文档，获取刚上传/替换的 document_id
        remote_docs = await client.list_documents(dataset_id)
        remote_by_name: dict[str, dict] = {
            doc.get("name"): doc for doc in remote_docs if doc.get("name")
        }
        for local_path in local_files:
            file_name = local_path.name
            current_hash = _file_hash(local_path)
            # 仅当本地状态中的 hash 与当前 hash 不一致时才需要解析（刚上传/替换）
            if state.get(file_name) != current_hash:
                doc = remote_by_name.get(file_name)
                if doc and doc.get("id"):
                    new_doc_ids.append(doc["id"])
                    state[file_name] = current_hash

        if on_progress is not None:
            on_progress(60)

        # 6. 解析并等待
        if new_doc_ids:
            await _parse_and_wait(client, dataset_id, new_doc_ids, up)

        if on_progress is not None:
            on_progress(90)

        # 7. 确保聊天助手
        chat_id = await _ensure_chat(client, up, dataset_id)
        result.chat_id = chat_id

    # 8. 保存状态
    _save_sync_state(up_dir, state)

    # 9. 提交 Uploader 变更
    db.commit()

    if on_progress is not None:
        on_progress(100)

    return result


async def cleanup_uploader_ragflow_resources(
    up: Uploader,
    *,
    ignore_errors: bool = True,
) -> dict:
    """删除 UP 主在 RagFlow 侧的资源。

    Args:
        up: UP 主对象
        ignore_errors: 是否忽略 RagFlow API 错误

    Returns:
        {"dataset_deleted": bool, "chat_deleted": bool, "errors": [...]}
    """
    settings = get_settings()
    errors: list[str] = []
    dataset_deleted = False
    chat_deleted = False

    if not settings.ragflow_base_url or not settings.ragflow_api_key:
        log.info("ragflow not configured, skip cleanup for uploader %s", up.id)
        return {
            "dataset_deleted": False,
            "chat_deleted": False,
            "errors": errors,
        }

    try:
        async with RagFlowClient() as client:
            if up.ragflow_chat_id:
                try:
                    await client.delete_chat(up.ragflow_chat_id)
                    chat_deleted = True
                except RagFlowError as exc:
                    if not ignore_errors:
                        raise
                    log.warning("failed to delete ragflow chat %s: %s", up.ragflow_chat_id, exc.message)
                    errors.append(f"删除 chat 失败: {exc.message}")

            if up.ragflow_dataset_id:
                try:
                    await client.delete_datasets([up.ragflow_dataset_id])
                    dataset_deleted = True
                except RagFlowError as exc:
                    if not ignore_errors:
                        raise
                    log.warning("failed to delete ragflow dataset %s: %s", up.ragflow_dataset_id, exc.message)
                    errors.append(f"删除 dataset 失败: {exc.message}")
    except Exception as exc:
        msg = str(exc) or exc.__class__.__name__
        log.warning("ragflow cleanup failed for uploader %s: %s", up.id, msg)
        if not ignore_errors:
            raise
        errors.append(msg)

    # 清理本地语料文件
    try:
        count = clear_ragflow_corpus(up.name)
        log.info("cleared %d local corpus files for uploader %s", count, up.id)
    except Exception as exc:
        msg = f"清理本地语料失败: {exc}"
        log.warning(msg)
        if not ignore_errors:
            raise
        errors.append(msg)

    return {
        "dataset_deleted": dataset_deleted,
        "chat_deleted": chat_deleted,
        "errors": errors,
    }
