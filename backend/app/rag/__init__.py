"""UP 复盘 RAG 模块。

当前默认方案已切换为生成 RAGFlow 语料（见 app.collect.corpus），原 Milvus +
LLM 提取路径暂停。为兼容未安装 pymilvus 的环境，service 层导出在
pymilvus 不可用时会被跳过。
"""

__all__ = []

# 仅在 pymilvus 可用时导出 Milvus 相关的 RAG 服务；
# 这样 app.rag.parser 等轻量模块仍可被字幕/语料流程单独导入。
try:
    from app.rag.service import (
        chat_global_reviews,
        chat_reviews,
        get_stats,
        ingest_directory,
        ingest_file,
        ingest_uploader,
        ingest_video,
        search_global_reviews,
        search_reviews,
        search_videos,
    )
except ImportError as _e:
    if "pymilvus" not in str(_e).lower():
        raise
    chat_global_reviews = None  # type: ignore
    chat_reviews = None  # type: ignore
    get_stats = None  # type: ignore
    ingest_directory = None  # type: ignore
    ingest_file = None  # type: ignore
    ingest_uploader = None  # type: ignore
    ingest_video = None  # type: ignore
    search_global_reviews = None  # type: ignore
    search_reviews = None  # type: ignore
    search_videos = None  # type: ignore
else:
    __all__ = [
        "chat_global_reviews",
        "chat_reviews",
        "get_stats",
        "ingest_directory",
        "ingest_file",
        "ingest_uploader",
        "ingest_video",
        "search_global_reviews",
        "search_reviews",
        "search_videos",
    ]
