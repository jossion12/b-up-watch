"""为所有已存在字幕的视频批量生成 RAGFlow 语料。

用法：
    cd backend
    python scripts/generate_corpus.py

说明：
- 仅处理 has_subtitle=true 的视频。
- 已生成的语料文件会被覆盖（幂等）。
- 失败不影响整体流程，最后会输出失败列表。
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

# 把 backend 目录加入模块搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows cmd/powershell 默认编码可能不是 utf-8，强制 stdout/stderr 用 utf-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from sqlalchemy import select

from app.collect.corpus import save_ragflow_corpus
from app.config import get_settings
from app.db import SessionLocal
from app.models import Subtitle, Video


def main() -> None:
    settings = get_settings()
    if not settings.ragflow_corpus_enabled:
        print("RAGFLOW_CORPUS_ENABLED=false，语料生成已禁用。")
        print("如需生成，请在 .env 中设置 RAGFLOW_CORPUS_ENABLED=true 后重试。")
        return

    with SessionLocal() as db:
        videos = db.execute(
            select(Video).where(Video.has_subtitle.is_(True))
        ).scalars().all()

        total = len(videos)
        if total == 0:
            print("没有已拉取字幕的视频。")
            return

        print(f"发现 {total} 个有字幕的视频，开始生成语料...")
        generated = 0
        failed: list[tuple[str, str, str]] = []

        for i, v in enumerate(videos, 1):
            sub = db.get(Subtitle, v.id)
            if sub is None or not sub.lines:
                print(f"[{i}/{total}] 跳过：video={v.id} 无字幕内容")
                continue
            try:
                path = save_ragflow_corpus(v, sub.lines, source=sub.source)
                print(f"[{i}/{total}] 已生成：{path}")
                generated += 1
            except Exception as e:
                print(f"[{i}/{total}] 失败：video={v.id}, error={e}")
                failed.append((v.id, v.title, str(e)))

        print("\n====================")
        print(f"总计：{total} 个视频")
        print(f"成功：{generated} 个")
        print(f"失败：{len(failed)} 个")
        if failed:
            print("\n失败列表：")
            for vid, title, err in failed:
                print(f"  - {vid} | {title} | {err}")


if __name__ == "__main__":
    main()
