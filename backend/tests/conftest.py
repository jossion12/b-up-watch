"""测试公共夹具：为每个测试重建指向临时 SQLite 的 engine/session。"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def temp_db(monkeypatch) -> Iterator[str]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    # 测试环境关掉后台 worker，由测试自己驱动 tick
    monkeypatch.setenv("WORKER_ENABLED", "false")
    # 清掉 Settings 缓存，使上面的 env 立即生效（lifespan 会重新读取）
    from app.config import get_settings
    get_settings.cache_clear()
    yield db_url
    get_settings.cache_clear()
    try:
        os.remove(path)
    except OSError:
        pass


@pytest.fixture()
def db_engine(temp_db):
    """重建 engine 指向临时库，并替换 app.db 模块的 engine/SessionLocal。"""
    import app.db as dbmod
    from app.db import Base
    from app import models  # noqa: F401

    new_engine = create_engine(
        temp_db,
        connect_args={"check_same_thread": False},
        future=True,
    )

    @event.listens_for(new_engine, "connect")
    def _pragma(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    NewSession = sessionmaker(bind=new_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=new_engine)

    dbmod.engine = new_engine
    dbmod.SessionLocal = NewSession

    yield new_engine


@pytest.fixture()
def db_session_factory(db_engine):
    import app.db as dbmod
    return dbmod.SessionLocal


@pytest.fixture()
def client(db_engine, db_session_factory) -> Iterator[TestClient]:
    from app.db import get_db
    from app.main import app

    def _override_get_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture()
def reset_wbi_cache():
    from app.bilibili import wbi
    wbi.reset_for_test()
    yield
    wbi.reset_for_test()


@pytest.fixture()
def subtitle_data_dir(tmp_path: Path, monkeypatch) -> Iterator[Path]:
    """将字幕归档目录重定向到临时目录，避免测试污染 data/。"""
    import app.collect.fetch_subtitle as fetch_mod

    original = fetch_mod._SUBTITLE_DATA_DIR
    target = tmp_path / "subtitles"
    monkeypatch.setattr(fetch_mod, "_SUBTITLE_DATA_DIR", target)
    yield target
    shutil.rmtree(target, ignore_errors=True)
