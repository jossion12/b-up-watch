"""数据库连接与初始化。"""

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """SQLAlchemy Declarative 基类。"""


def _make_engine():
    settings = get_settings()
    url = settings.database_url
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_engine(url, connect_args=connect_args, future=True)

    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_pragma(dbapi_conn, _):  # noqa: ANN001
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_priority_column() -> None:
    """无 Alembic 时的兜底迁移：确保 tasks 表包含 priority 列。"""
    try:
        with engine.connect() as conn:
            inspector = inspect(engine)
            columns = {c["name"] for c in inspector.get_columns("tasks")}
            if "priority" not in columns:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN priority INTEGER NOT NULL DEFAULT 0"))
                conn.commit()
    except Exception:
        # 首次启动表尚未创建时忽略；后续启动再检查
        pass


def init_db() -> None:
    """首次启动建表 + seed 默认模板与系统配置。"""
    from app import models  # noqa: F401  触发注册

    # 确保 SQLite 文件目录存在
    url = get_settings().database_url
    if url.startswith("sqlite"):
        db_file = Path(url.replace("sqlite:///", ""))
        db_file.parent.mkdir(parents=True, exist_ok=True)

    Base.metadata.create_all(bind=engine)
    _migrate_priority_column()

    with SessionLocal() as db:
        from app.models import SystemConfig, SummaryTemplate
        from datetime import datetime, timezone

        if db.query(SummaryTemplate).filter_by(id="tpl_default").first() is None:
            db.add(SummaryTemplate(
                id="tpl_default",
                name="通用深度总结",
                is_default=True,
                prompt=(
                    "你是视频内容分析助手。请根据以下字幕，只输出一个合法 JSON 对象，不要有任何解释或 markdown 代码块。\n"
                    "输出格式示例：\n"
                    '{\n'
                    '  "brief": "150字内摘要",\n'
                    '  "points": ["要点1", "要点2", "要点3"],\n'
                    '  "stance": {\n'
                    '    "label": "观点标签",\n'
                    '    "sentiment": "positive",\n'
                    '    "detail": "详细阐述UP主观点"\n'
                    '  },\n'
                    '  "topics": ["话题1", "话题2", "话题3"],\n'
                    '  "quote": "一句金句"\n'
                    '}\n'
                    "注意：sentiment 必须是 positive/neutral/negative/mixed 四选一。\n\n"
                    "视频标题：{{title}}\n"
                    "UP主：{{uploader}}\n"
                    "字幕：\n{{subtitle}}"
                ),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            ))
        if db.query(SystemConfig).count() == 0:
            db.add(SystemConfig(
                id=1,
                refresh_interval_sec=600,
                summary_model="qwen3-235b-a22b-instruct",
                summary_template_id="tpl_default",
                auto_summarize=False,
            ))
        db.commit()