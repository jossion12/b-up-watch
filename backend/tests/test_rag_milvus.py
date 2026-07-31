"""RAG Milvus 模块测试。"""

from __future__ import annotations

import logging
import sys
import traceback
from unittest.mock import MagicMock

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


class TestKeywordSearch:
    """关键词检索相关单元测试。"""

    def test_tokenize_query_filters_short_terms(self):
        from app.rag.milvus_store import MilvusReviewStore

        terms = MilvusReviewStore._tokenize_query("a 中文 测试 1")
        assert "中文" in terms
        assert "测试" in terms
        assert "a" not in terms
        assert "1" in terms  # 数字保留

    def test_tokenize_query_removes_wildcards(self):
        from app.rag.milvus_store import MilvusReviewStore

        terms = MilvusReviewStore._tokenize_query("100%_增长")
        assert "%" not in terms
        assert "_" not in terms
        assert "100" in terms
        assert "增长" in terms

    def test_build_keyword_filter_and_across_terms(self):
        from app.rag.milvus_store import MilvusReviewStore

        expr = MilvusReviewStore._build_keyword_filter("长鑫 预测")
        assert "content" in expr
        assert "core_topic" in expr
        assert 'like "%长鑫%"' in expr
        assert 'like "%预测%"' in expr
        assert " and " in expr

    def test_build_keyword_filter_returns_none_for_short_query(self):
        from app.rag.milvus_store import MilvusReviewStore

        assert MilvusReviewStore._build_keyword_filter("a") is None


class TestHybridSearchAndRerank:
    """混合检索、RRF 与重排序单元测试。"""

    @pytest.fixture()
    def sample_chunks(self):
        return [
            {"chunk_id": "c1", "content": "内容1", "metadata": {"video_title": "v1"}},
            {"chunk_id": "c2", "content": "内容2", "metadata": {"video_title": "v1"}},
            {"chunk_id": "c3", "content": "内容3", "metadata": {"video_title": "v1"}},
        ]

    def test_rrf_fuse_combines_ranked_lists(self, sample_chunks):
        from app.rag.milvus_store import MilvusReviewStore

        vector_results = [sample_chunks[0], sample_chunks[1]]
        keyword_results = [sample_chunks[1], sample_chunks[2]]
        fused = MilvusReviewStore._rrf_fuse([vector_results, keyword_results], k=60)

        # c1 只在 vector 出现，c3 只在 keyword 出现，c2 在两个列表都出现应排最前
        assert fused[0]["chunk_id"] == "c2"
        assert len(fused) == 3

    def test_rrf_fuse_single_list(self, sample_chunks):
        from app.rag.milvus_store import MilvusReviewStore

        fused = MilvusReviewStore._rrf_fuse([sample_chunks])
        assert [c["chunk_id"] for c in fused] == ["c1", "c2", "c3"]

    def test_keyword_search_calls_client_query(self, monkeypatch):
        from app.rag import milvus_store as store_mod
        from app.rag.milvus_store import MilvusReviewStore

        class FakeSettings:
            milvus_uri = "./data/milvus/test.db"
            milvus_host = "localhost"
            milvus_port = 19530
            milvus_collection = "test_collection"
            embedding_provider = "sentence_transformers"
            embedding_model = "dummy"
            embedding_dim = 1024
            ollama_base_url = ""
            rerank_enabled = False
            rerank_model = "dummy"
            rerank_top_k = 20

        monkeypatch.setattr(store_mod, "get_settings", lambda: FakeSettings())

        fake_client = MagicMock()
        fake_client.has_collection.return_value = True
        fake_client.query.return_value = [
            {
                "id": "c1",
                "content": "测试内容",
                "video_title": "vt",
                "up_name": "up",
                "date": "2026-01-01",
                "time_position": "00:00 -> 00:01",
                "content_type": "观点",
                "argument_role": "主论点",
                "core_topic": "主题",
                "stance_type": "判断",
                "confidence": "中",
                "verifiability": "可验证",
                "source_type": "UP主本人",
                "sub_topics": "",
                "original_arguments": "[]",
            }
        ]

        store = object.__new__(MilvusReviewStore)
        store.client = fake_client
        store.collection_name = "test_collection"
        store.embedding_dim = 1024
        store.rerank_enabled = False
        store.rerank_model = "dummy"
        store.rerank_top_k = 20
        store._reranker = None

        results = store.keyword_search("测试", n_results=5)
        assert len(results) == 1
        assert results[0]["chunk_id"] == "c1"
        fake_client.query.assert_called_once()
        call_kwargs = fake_client.query.call_args.kwargs
        assert "like" in call_kwargs["filter"]

    def test_hybrid_search_fuses_and_reranks(self, sample_chunks, monkeypatch):
        from app.rag import milvus_store as store_mod
        from app.rag.milvus_store import MilvusReviewStore

        class FakeSettings:
            milvus_uri = "./data/milvus/test.db"
            milvus_host = "localhost"
            milvus_port = 19530
            milvus_collection = "test_collection"
            embedding_provider = "sentence_transformers"
            embedding_model = "dummy"
            embedding_dim = 1024
            ollama_base_url = ""
            rerank_enabled = True
            rerank_model = "dummy"
            rerank_top_k = 20

        monkeypatch.setattr(store_mod, "get_settings", lambda: FakeSettings())

        store = object.__new__(MilvusReviewStore)
        store.collection_name = "test_collection"
        store.embedding_dim = 1024
        store.rerank_enabled = True
        store.rerank_model = "dummy"
        store.rerank_top_k = 20
        store._reranker = None

        store.search = MagicMock(return_value=[sample_chunks[0], sample_chunks[1]])
        store.keyword_search = MagicMock(return_value=[sample_chunks[1], sample_chunks[2]])

        # Mock reranker: reverse order to verify rerank is applied
        fake_reranker = MagicMock()
        fake_reranker.rerank.return_value = [sample_chunks[1], sample_chunks[0]]
        monkeypatch.setattr(store, "_get_reranker", lambda: fake_reranker)

        results = store.hybrid_search("查询", n_results=2)
        assert len(results) == 2
        fake_reranker.rerank.assert_called_once()

    def test_rerank_falls_back_on_failure(self, sample_chunks, monkeypatch):
        from app.rag import milvus_store as store_mod
        from app.rag.milvus_store import MilvusReviewStore

        class FakeSettings:
            milvus_uri = "./data/milvus/test.db"
            milvus_host = "localhost"
            milvus_port = 19530
            milvus_collection = "test_collection"
            embedding_provider = "sentence_transformers"
            embedding_model = "dummy"
            embedding_dim = 1024
            ollama_base_url = ""
            rerank_enabled = False
            rerank_model = "dummy"
            rerank_top_k = 20

        monkeypatch.setattr(store_mod, "get_settings", lambda: FakeSettings())

        store = object.__new__(MilvusReviewStore)
        store.collection_name = "test_collection"
        store.rerank_model = "dummy"
        store.rerank_top_k = 20
        store._reranker = None

        def _broken_get_reranker():
            raise RuntimeError("model not found")

        monkeypatch.setattr(store, "_get_reranker", _broken_get_reranker)

        results = store.rerank("查询", sample_chunks, top_k=2)
        assert len(results) == 2
        assert results[0]["chunk_id"] == "c1"
