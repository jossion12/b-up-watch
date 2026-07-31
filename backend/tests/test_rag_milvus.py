"""RAG Milvus 模块测试。"""

from __future__ import annotations

import logging
import sys
import traceback

import pytest


class TestMilvusLiteGrpcFilter:
    """验证 _MilvusLiteGrpcFilter 能正确过滤 Milvus Lite 的非致命 AllocTimestamp 日志。"""

    @pytest.fixture()
    def filter_obj(self):
        from app.rag.milvus_store import _MilvusLiteGrpcFilter

        return _MilvusLiteGrpcFilter()

    def _make_record(
        self,
        msg: str,
        exc_info: tuple | None = None,
    ) -> logging.LogRecord:
        return logging.LogRecord(
            name="grpc._server",
            level=logging.ERROR,
            pathname="grpc/_server.py",
            lineno=608,
            msg=msg,
            args=(),
            exc_info=exc_info,
        )

    def test_filter_suppresses_alloc_timestamp_error(self, filter_obj, monkeypatch):
        """AllocTimestamp + Method not implemented! 的日志应被抑制。"""

        try:
            raise NotImplementedError("Method not implemented!")
        except Exception:
            exc_info = sys.exc_info()

        # 模拟真实 Milvus Lite 报错中 traceback 包含 AllocTimestamp 帧
        monkeypatch.setattr(
            traceback,
            "format_tb",
            lambda tb: ['  File ".../milvus_pb2_grpc.py", line 1232, in AllocTimestamp\n'],
        )

        record = self._make_record(
            "Exception calling application: Method not implemented!",
            exc_info=exc_info,
        )
        assert filter_obj.filter(record) is False

    def test_does_not_suppress_other_errors(self, filter_obj):
        """其它 grpc 错误不应被误杀。"""

        try:
            raise ValueError("some real error")
        except Exception:
            exc_info = sys.exc_info()

        record = self._make_record(
            "Exception calling application: some real error",
            exc_info=exc_info,
        )
        assert filter_obj.filter(record) is True

    def test_does_not_suppress_plain_not_implemented(self, filter_obj):
        """不包含 AllocTimestamp 的 NotImplementedError 不应被过滤。"""

        try:
            raise NotImplementedError("Method not implemented!")
        except Exception:
            exc_info = sys.exc_info()

        record = self._make_record(
            "Exception calling application: Method not implemented!",
            exc_info=exc_info,
        )
        assert filter_obj.filter(record) is True

    def test_filter_uses_exc_text_when_available(self, filter_obj):
        """当 exc_text 已被格式化且包含 AllocTimestamp 时也应过滤。"""

        try:
            raise NotImplementedError("Method not implemented!")
        except Exception:
            exc_info = sys.exc_info()

        record = self._make_record(
            "Exception calling application: Method not implemented!",
            exc_info=exc_info,
        )
        # 模拟 formatter 已设置 exc_text 的场景
        record.exc_text = (
            "Traceback (most recent call last):\n"
            '  File ".../milvus_pb2_grpc.py", line 1232, in AllocTimestamp\n'
            "NotImplementedError: Method not implemented!"
        )
        assert filter_obj.filter(record) is False
