"""应用配置（pydantic-settings，从 .env 读取）。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# 运行时从数据库加载的 B站 SESSDATA 缓存；优先于 .env 中的值。
_live_bilibili_sessdata: str | None = None
# 运行时从数据库加载的完整 B站 Cookie 缓存；优先于 .env 中的值。
_live_bilibili_cookie: str | None = None
# 运行时从数据库加载的 RagFlow Web embed auth 缓存；优先于 .env 中的值。
_live_ragflow_embed_auth: str | None = None


def set_bilibili_sessdata(value: str | None) -> None:
    """更新内存中的 SESSDATA 缓存。"""
    global _live_bilibili_sessdata
    _live_bilibili_sessdata = value


def get_bilibili_sessdata() -> str:
    """获取当前生效的 SESSDATA：优先运行时缓存，其次 .env。"""
    if _live_bilibili_sessdata is not None:
        return _live_bilibili_sessdata
    return get_settings().bilibili_sessdata


def set_bilibili_cookie(value: str | None) -> None:
    """更新内存中的完整 B站 Cookie 缓存。"""
    global _live_bilibili_cookie
    _live_bilibili_cookie = value


def get_bilibili_cookie() -> str:
    """获取当前生效的完整 B站 Cookie：优先运行时缓存，其次 .env。"""
    if _live_bilibili_cookie is not None:
        return _live_bilibili_cookie
    return get_settings().bilibili_cookie


def set_ragflow_embed_auth(value: str | None) -> None:
    """更新内存中的 RagFlow Web embed auth 缓存。"""
    global _live_ragflow_embed_auth
    _live_ragflow_embed_auth = value


def get_ragflow_embed_auth() -> str:
    """获取当前生效的 RagFlow Web embed auth：优先运行时缓存，其次 .env。"""
    if _live_ragflow_embed_auth is not None:
        return _live_ragflow_embed_auth
    return get_settings().ragflow_embed_auth


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 服务
    database_url: str = "sqlite:///./data/upwatch.db"
    log_level: str = "INFO"
    worker_enabled: bool = True
    worker_tick_sec: float = 60.0

    # 任务调度器（在 worker 启用时自动创建周期性任务）
    scheduler_enabled: bool = True
    scheduler_subtitle_interval_sec: float = 120.0
    scheduler_summary_interval_sec: float = 120.0
    scheduler_backfill_interval_sec: float = 900.0
    scheduler_batch_size: int = 10
    scheduler_failed_task_backoff_sec: float = 1800.0
    backfill_extra_days: int = 30
    backfill_max_pages: int = 10

    # B站
    bilibili_sessdata: str = ""
    bilibili_cookie: str = ""
    bilibili_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )

    # LLM（OpenAI 兼容）
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_sec: float = 300.0
    llm_max_tokens: int = 4096
    # 是否发送 response_format={"type": "json_object"}；Ollama 等本地模型可设为 false
    llm_json_mode: bool = True

    # ASR（本地 Qwen3-ASR）
    qwen_asr_model_path: str = ""
    qwen_asr_device: str = ""
    yt_dlp_cookies_file: str = ""

    # 字幕校验：B站字幕时长与视频时长偏差超过阈值时，自动换 Whisper 转写兜底
    # 相对偏差（如 0.15=15%）与绝对偏差（秒）同时满足才触发 fallback
    subtitle_duration_mismatch_ratio: float = 0.15
    subtitle_duration_mismatch_abs_sec: float = 10.0

    # UP 复盘 RAG
    review_base_dir: str = "./data"
    # 字幕获取成功后是否自动导入 RAG（会调用 LLM 提取观点卡片）
    # 当前已切换为生成 RAGFlow 语料，原 Milvus 导入路径默认关闭
    rag_auto_ingest_enabled: bool = False
    # 是否自动生成 RAGFlow 语料文件（Markdown，无 LLM）
    ragflow_corpus_enabled: bool = True
    # RAGFlow 语料输出目录
    ragflow_corpus_dir: str = "./data/corpus"
    # 是否将生成的语料自动同步到 RagFlow 知识库
    ragflow_sync_enabled: bool = False
    # RagFlow 服务地址，例如 http://127.0.0.1:9380
    ragflow_base_url: str = ""
    # RagFlow Web UI 地址（用于生成聊天分享链接）。默认与 ragflow_base_url 相同；
    # 当 API 与 Web UI 使用不同端口时（如 Docker 部署 Web 在 80/API 在 9380），需单独配置。
    ragflow_web_url: str = ""
    # RagFlow API Key
    ragflow_api_key: str = ""
    # RagFlow Web 端 embed 对话 iframe 使用的 auth 参数。
    # 注意：这与 API Key 不同；UI 上「嵌入网页」会生成一个固定的 auth 值。
    # 运行时若数据库 SystemConfig.ragflow_embed_auth 有值，会覆盖此处。
    ragflow_embed_auth: str = "x6trEIhnczD9vljT4q_HHvvovNPxpWwL"
    # RagFlow 创建知识库时使用的 Embedding 模型，例如 "BAAI/bge-large-zh-v1.5@BAAI"
    ragflow_embedding_model: str = ""
    # RagFlow 分块方法，默认 naive
    ragflow_chunk_method: str = "naive"
    # RagFlow 创建知识库时的语言，默认中文
    ragflow_dataset_language: str = "Chinese"
    # 文档解析轮询超时（秒）
    ragflow_parse_timeout_sec: float = 600.0
    # 解析轮询间隔（秒）
    ragflow_parse_poll_interval_sec: float = 3.0
    # embedding 后端：sentence_transformers 或 ollama
    embedding_provider: str = "sentence_transformers"
    embedding_model: str = "BAAI/bge-large-zh-v1.5"
    embedding_dim: int = 1024
    ollama_base_url: str = "http://localhost:11434"

    # 重排序（交叉编码器），默认关闭
    rerank_enabled: bool = False
    # rerank_model 支持 HuggingFace 模型名或本地绝对路径
    rerank_model: str = "BAAI/bge-reranker-base"
    # rerank_model_path 若填写，则优先于 rerank_model 作为本地路径使用
    rerank_model_path: str = ""
    # 重排序返回 top_k 数量
    rerank_top_k: int = 20

    # Milvus 向量库
    # 如果设置 milvus_uri（如 ./data/milvus/taoge.db），则优先使用 Milvus Lite 本地模式；
    # 否则连接 milvus_host:milvus_port 的服务器模式。
    milvus_uri: str = "./data/milvus/taoge.db"
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection: str = "taoge_review_chunks"


@lru_cache
def get_settings() -> Settings:
    return Settings()