"""应用配置（pydantic-settings，从 .env 读取）。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # ASR（本地 Qwen3-ASR）
    qwen_asr_model_path: str = ""
    qwen_asr_device: str = ""
    yt_dlp_cookies_file: str = ""

    # 字幕校验：B站字幕时长与视频时长偏差超过阈值时，自动换 Whisper 转写兜底
    # 相对偏差（如 0.15=15%）与绝对偏差（秒）同时满足才触发 fallback
    subtitle_duration_mismatch_ratio: float = 0.15
    subtitle_duration_mismatch_abs_sec: float = 10.0


@lru_cache
def get_settings() -> Settings:
    return Settings()