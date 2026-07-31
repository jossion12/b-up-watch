"""Milvus 向量库封装。

基于 pymilvus.MilvusClient，同时支持：
- Milvus Lite 本地模式：uri 为以 .db 结尾的本地文件路径
- Milvus 服务器模式：uri 为 http://host:port 或空（使用 host+port）

Embedding 支持两种后端（通过 EMBEDDING_PROVIDER 配置）：
- sentence_transformers：本地加载 HuggingFace 模型（默认 BAAI/bge-large-zh-v1.5）
- ollama：调用本地 Ollama /api/embeddings 接口，无需下载大模型
"""

from __future__ import annotations

import json
import logging
import os
import re
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

# pymilvus 3.0 在模块导入时会读取 MILVUS_URI 环境变量并校验格式；
# 当 .env 中配置的是 Milvus Lite 本地 .db 路径时，导入会直接报错。
# 此处先将其置为合法的 http 占位符，确保 import 成功；
# 实际连接时 MilvusClient 使用的 URI 来自 get_settings().milvus_uri。
_milvus_uri_env = os.environ.get("MILVUS_URI", "")
os.environ["MILVUS_URI"] = "http://localhost:19530"

# 调整 gRPC keepalive，避免 Milvus Lite / 服务器模式因 PING 帧过频返回
# GOAWAY(ENHANCE_YOUR_CALM, too_many_pings)。setdefault 保留用户自定义值。
os.environ.setdefault("GRPC_KEEPALIVE_TIME_MS", "300000")       # 5 分钟
os.environ.setdefault("GRPC_KEEPALIVE_TIMEOUT_MS", "20000")     # 20 秒
os.environ.setdefault("GRPC_KEEPALIVE_PERMIT_WITHOUT_CALLS", "0")

try:
    from pymilvus import DataType, MilvusClient
finally:
    if _milvus_uri_env:
        os.environ["MILVUS_URI"] = _milvus_uri_env
    else:
        os.environ.pop("MILVUS_URI", None)

from app.config import get_settings

log = logging.getLogger(__name__)

# 默认维度与 BAAI/bge-large-zh-v1.5 一致；使用 Ollama 等其它模型时请同步修改 EMBEDDING_DIM
_DEFAULT_DIM = 1024

# 关键词检索覆盖的 VARCHAR 字段
_KEYWORD_FIELDS = ["content", "core_topic", "sub_topics", "original_arguments"]


class _MilvusLiteGrpcFilter(logging.Filter):
    """过滤 Milvus Lite 未实现 AllocTimestamp 导致的 grpc._server 报错日志。

    Milvus Lite 在 drop/create collection 等操作时会内部调用 AllocTimestamp，
    但该 RPC 在 Lite 模式下未实现，会抛出 NotImplementedError 并被 grpc._server
    记录为 ERROR。该错误是非致命的，后续操作仍能正常完成，因此在此处静默掉
    这一特定日志，避免污染服务日志。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        # 快速排除：不是 grpc 未实现错误的不处理
        if "Method not implemented!" not in msg:
            return True

        # Milvus Lite 的报错信息里 AllocTimestamp 出现在 traceback 中，
        # 而非 msg 主消息里，因此需要同时检查格式化后的异常文本。
        exc_text = record.exc_text or ""
        if "AllocTimestamp" in msg or "AllocTimestamp" in exc_text:
            return False

        # filter 在 formatter 之前执行，exc_text 可能尚未生成，
        # 此时需要从 exc_info 的 traceback 对象中自行格式化检查。
        exc_info = record.exc_info
        if exc_info and exc_info[0] is NotImplementedError and exc_info[2] is not None:
            tb_str = "".join(traceback.format_tb(exc_info[2]))
            if "AllocTimestamp" in tb_str:
                return False

        return True


# 仅针对 grpc._server 中 Milvus Lite 的已知非致命错误做过滤
logging.getLogger("grpc._server").addFilter(_MilvusLiteGrpcFilter())


class _OllamaEmbedder:
    """Ollama embedding 封装。"""

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def encode(self, texts: List[str]) -> List[List[float]]:
        embeddings: List[List[float]] = []
        for text in texts:
            try:
                resp = httpx.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                    timeout=120.0,
                )
                resp.raise_for_status()
                data = resp.json()
                embeddings.append(data["embedding"])
            except Exception as e:
                log.error("Ollama embedding failed for text %.50s: %s", text, e)
                raise
        return embeddings


class _CrossEncoderReranker:
    """基于 sentence-transformers CrossEncoder 的轻量重排序封装。"""

    def __init__(self, model_name: str, model_path: Optional[str] = None):
        from sentence_transformers import CrossEncoder

        self.model_source = model_path if model_path else model_name
        self.model = CrossEncoder(self.model_source)
        log.info("Loaded cross-encoder reranker: %s", self.model_source)

    def rerank(self, query: str, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not chunks:
            return []
        pairs = [(query, c["content"]) for c in chunks]
        scores = self.model.predict(pairs)
        scored = [(score, chunk) for score, chunk in zip(scores, chunks)]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [chunk for _, chunk in scored]


# 按配置维度缓存 MilvusReviewStore 实例，避免每次请求都重建 MilvusClient 与 embedding 模型。
_store_cache: Dict[tuple, "MilvusReviewStore"] = {}


class MilvusReviewStore:
    """UP 复盘观点卡片的 Milvus 向量库封装。"""

    def __init__(
        self,
        uri: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        collection_name: Optional[str] = None,
    ):
        settings = get_settings()
        self.uri = uri or settings.milvus_uri
        self.host = host or settings.milvus_host
        self.port = port or settings.milvus_port
        self.collection_name = collection_name or settings.milvus_collection
        self.embedding_provider = settings.embedding_provider
        self.embedding_model = settings.embedding_model
        self.embedding_dim = settings.embedding_dim
        self.ollama_base_url = settings.ollama_base_url

        self.rerank_enabled = settings.rerank_enabled
        self.rerank_model = settings.rerank_model
        self.rerank_model_path = settings.rerank_model_path
        self.rerank_top_k = settings.rerank_top_k

        self._reranker: Optional[_CrossEncoderReranker] = None

        if self.uri and self.uri.strip():
            use_uri = self.uri.strip()
            if use_uri.endswith(".db"):
                # 确保目录存在
                Path(use_uri).parent.mkdir(parents=True, exist_ok=True)
        else:
            use_uri = f"http://{self.host}:{self.port}"

        self.client = MilvusClient(uri=use_uri)
        log.debug("Milvus client created: %s", use_uri)

        self._embedder = None
        self._ensure_collection()

    @classmethod
    def get_instance(
        cls,
        uri: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        collection_name: Optional[str] = None,
    ) -> "MilvusReviewStore":
        """获取（或创建）按配置维度缓存的 Store 实例。"""
        key = (uri, host, port, collection_name)
        if key not in _store_cache:
            _store_cache[key] = cls(
                uri=uri,
                host=host,
                port=port,
                collection_name=collection_name,
            )
        return _store_cache[key]

    def _get_embedder(self):
        if self._embedder is None:
            if self.embedding_provider == "ollama":
                self._embedder = _OllamaEmbedder(self.ollama_base_url, self.embedding_model)
                log.info("Using Ollama embedding: %s/%s", self.ollama_base_url, self.embedding_model)
            else:
                from sentence_transformers import SentenceTransformer

                self._embedder = SentenceTransformer(self.embedding_model)
                log.info("Loaded sentence-transformers model: %s", self.embedding_model)
        return self._embedder

    def encode(self, texts: List[str]) -> List[List[float]]:
        embedder = self._get_embedder()
        return embedder.encode(texts)

    # 当前代码期望 collection 包含的字段集合
    _EXPECTED_FIELDS = {
        "id", "content", "video_id", "uploader_id", "video_title", "up_name",
        "date", "published_at", "time_position", "content_type", "argument_role",
        "core_topic", "stance_type", "confidence", "verifiability", "source_type",
        "sub_topics", "original_arguments", "embedding",
    }

    def _ensure_collection(self) -> None:
        """确保 collection 存在且 schema 与当前代码一致；不一致则删除重建。"""
        if self.client.has_collection(self.collection_name):
            desc = self.client.describe_collection(self.collection_name)
            existing = {f.get("name") for f in desc.get("fields", [])}
            missing = self._EXPECTED_FIELDS - existing
            if not missing:
                return
            log.warning(
                "Collection %s schema missing fields %s, dropping and recreating",
                self.collection_name,
                sorted(missing),
            )
            self.client.drop_collection(self.collection_name)

        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(field_name="id", datatype=DataType.VARCHAR, max_length=64, is_primary=True)
        schema.add_field(field_name="content", datatype=DataType.VARCHAR, max_length=8192)
        schema.add_field(field_name="video_id", datatype=DataType.VARCHAR, max_length=32)
        schema.add_field(field_name="uploader_id", datatype=DataType.VARCHAR, max_length=32)
        schema.add_field(field_name="video_title", datatype=DataType.VARCHAR, max_length=512)
        schema.add_field(field_name="up_name", datatype=DataType.VARCHAR, max_length=128)
        schema.add_field(field_name="date", datatype=DataType.VARCHAR, max_length=16)
        schema.add_field(field_name="published_at", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="time_position", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="content_type", datatype=DataType.VARCHAR, max_length=32)
        schema.add_field(field_name="argument_role", datatype=DataType.VARCHAR, max_length=32)
        schema.add_field(field_name="core_topic", datatype=DataType.VARCHAR, max_length=256)
        schema.add_field(field_name="stance_type", datatype=DataType.VARCHAR, max_length=32)
        schema.add_field(field_name="confidence", datatype=DataType.VARCHAR, max_length=16)
        schema.add_field(field_name="verifiability", datatype=DataType.VARCHAR, max_length=32)
        schema.add_field(field_name="source_type", datatype=DataType.VARCHAR, max_length=32)
        schema.add_field(field_name="sub_topics", datatype=DataType.VARCHAR, max_length=1024)
        schema.add_field(field_name="original_arguments", datatype=DataType.VARCHAR, max_length=4096)
        schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=self.embedding_dim)

        index_params = MilvusClient.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            metric_type="L2",
            index_type="IVF_FLAT",
            params={"nlist": 128},
        )

        self.client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=index_params,
        )
        log.info("Milvus collection %s created (dim=%d)", self.collection_name, self.embedding_dim)

    def add_chunks(self, chunks: List[Dict[str, Any]]) -> int:
        """批量写入观点卡片。"""
        if not chunks:
            return 0

        data = []
        for c in chunks:
            meta = c.get("metadata", {})
            enriched = self._enrich_text(c["content"], meta)
            embedding = self.encode([enriched])[0]
            data.append({
                "id": c["chunk_id"],
                "content": c["content"],
                "video_id": meta.get("video_id", ""),
                "uploader_id": meta.get("uploader_id", ""),
                "video_title": meta.get("video_title", ""),
                "up_name": meta.get("up_name", ""),
                "date": meta.get("date", ""),
                "published_at": meta.get("published_at", ""),
                "time_position": meta.get("time_position", ""),
                "content_type": meta.get("content_type", ""),
                "argument_role": meta.get("argument_role", ""),
                "core_topic": meta.get("core_topic", ""),
                "stance_type": meta.get("stance_type", ""),
                "confidence": meta.get("confidence", ""),
                "verifiability": meta.get("verifiability", ""),
                "source_type": meta.get("source_type", ""),
                "sub_topics": ", ".join(meta.get("sub_topics", [])),
                "original_arguments": json.dumps(meta.get("original_arguments", []), ensure_ascii=False),
                "embedding": embedding,
            })

        self.client.insert(collection_name=self.collection_name, data=data)
        log.info("Inserted %d chunks into Milvus", len(data))
        return len(data)

    def _enrich_text(self, content: str, meta: Dict[str, Any]) -> str:
        """把关键 metadata 拼接到 content 中，提升向量检索精度。"""
        parts = [content]
        if meta.get("core_topic"):
            parts.append(f"主题: {meta['core_topic']}")
        if meta.get("stance_type") and meta["stance_type"] != "无":
            parts.append(f"立场: {meta['stance_type']}")
        if meta.get("argument_role") and meta["argument_role"] != "无":
            parts.append(f"角色: {meta['argument_role']}")
        if meta.get("content_type"):
            parts.append(f"类型: {meta['content_type']}")
        return " | ".join(parts)

    def _load(self) -> None:
        """确保 collection 已加载。"""
        try:
            self.client.load_collection(self.collection_name)
        except Exception as e:
            log.debug("load_collection skipped: %s", e)

    def search(
        self,
        query: str,
        n_results: int = 5,
        filter_expr: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """语义检索。"""
        self._load()
        query_embedding = self.encode([query])

        results = self.client.search(
            collection_name=self.collection_name,
            data=query_embedding,
            anns_field="embedding",
            limit=n_results,
            filter=filter_expr,
            output_fields=[
                "content", "video_id", "uploader_id", "video_title", "up_name", "date",
                "published_at", "time_position", "content_type", "argument_role",
                "core_topic", "stance_type", "confidence", "verifiability", "source_type",
                "sub_topics", "original_arguments"
            ],
        )

        output: List[Dict[str, Any]] = []
        for hits in results:
            for hit in hits:
                entity = hit.get("entity", {})
                output.append({
                    "chunk_id": hit.get("id") or entity.get("id"),
                    "content": entity.get("content"),
                    "distance": float(hit.get("distance", 0)),
                    "metadata": {
                        "video_id": entity.get("video_id"),
                        "uploader_id": entity.get("uploader_id"),
                        "video_title": entity.get("video_title"),
                        "up_name": entity.get("up_name"),
                        "date": entity.get("date"),
                        "published_at": entity.get("published_at"),
                        "time_position": entity.get("time_position"),
                        "content_type": entity.get("content_type"),
                        "argument_role": entity.get("argument_role"),
                        "core_topic": entity.get("core_topic"),
                        "stance_type": entity.get("stance_type"),
                        "confidence": entity.get("confidence"),
                        "verifiability": entity.get("verifiability"),
                        "source_type": entity.get("source_type"),
                        "sub_topics": [t.strip() for t in (entity.get("sub_topics") or "").split(",") if t.strip()],
                        "original_arguments": json.loads(entity.get("original_arguments") or "[]"),
                    },
                })
        return output

    @staticmethod
    def _tokenize_query(query: str) -> List[str]:
        """把查询拆分为可用于关键词匹配的词项。"""
        # 去掉通配符字符，避免干扰 Milvus like 表达式
        cleaned = re.sub(r"[%_]+", " ", query)
        terms = [t.strip() for t in cleaned.split() if t.strip()]
        # 过滤过短词项，保留长度 >= 2 或数字
        return [t for t in terms if len(t) >= 2 or t.isdigit()]

    @staticmethod
    def _build_keyword_filter(query: str) -> Optional[str]:
        """为 Milvus query 构建 like 过滤表达式。

        每个词项需在任一关键词字段中出现；多个词项之间为 AND 关系。
        """
        terms = MilvusReviewStore._tokenize_query(query)
        if not terms:
            return None

        term_clauses = []
        for term in terms:
            # 双引号转义：Milvus 字符串字面量使用双引号包裹
            escaped_term = term.replace('"', '\\"')
            field_clauses = [f'{field} like "%{escaped_term}%"' for field in _KEYWORD_FIELDS]
            term_clauses.append(f"({' or '.join(field_clauses)})")
        return " and ".join(term_clauses)

    def keyword_search(
        self,
        query: str,
        n_results: int = 5,
        filter_expr: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """基于 Milvus like 表达式的关键词检索。"""
        keyword_filter = self._build_keyword_filter(query)
        if keyword_filter is None:
            return []

        combined_filter = keyword_filter
        if filter_expr:
            combined_filter = f"({filter_expr}) and ({keyword_filter})"

        self._load()
        try:
            results = self.client.query(
                collection_name=self.collection_name,
                filter=combined_filter,
                output_fields=[
                    "id", "content", "video_id", "uploader_id", "video_title", "up_name",
                    "date", "published_at", "time_position", "content_type", "argument_role",
                    "core_topic", "stance_type", "confidence", "verifiability", "source_type",
                    "sub_topics", "original_arguments"
                ],
                limit=n_results,
            )
        except Exception as e:
            log.warning("Keyword search failed (%s): %s", combined_filter, e)
            return []

        output: List[Dict[str, Any]] = []
        for entity in results:
            output.append({
                "chunk_id": entity.get("id"),
                "content": entity.get("content"),
                "distance": 0.0,
                "metadata": {
                    "video_id": entity.get("video_id"),
                    "uploader_id": entity.get("uploader_id"),
                    "video_title": entity.get("video_title"),
                    "up_name": entity.get("up_name"),
                    "date": entity.get("date"),
                    "published_at": entity.get("published_at"),
                    "time_position": entity.get("time_position"),
                    "content_type": entity.get("content_type"),
                    "argument_role": entity.get("argument_role"),
                    "core_topic": entity.get("core_topic"),
                    "stance_type": entity.get("stance_type"),
                    "confidence": entity.get("confidence"),
                    "verifiability": entity.get("verifiability"),
                    "source_type": entity.get("source_type"),
                    "sub_topics": [t.strip() for t in (entity.get("sub_topics") or "").split(",") if t.strip()],
                    "original_arguments": json.loads(entity.get("original_arguments") or "[]"),
                },
            })
        return output

    @staticmethod
    def _rrf_fuse(ranked_lists: List[List[Dict[str, Any]]], k: int = 60) -> List[Dict[str, Any]]:
        """使用 Reciprocal Rank Fusion 合并多个排序列表。"""
        scores: Dict[str, float] = {}
        item_map: Dict[str, Dict[str, Any]] = {}

        for lst in ranked_lists:
            for rank, item in enumerate(lst, start=1):
                item_id = item["chunk_id"]
                scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
                if item_id not in item_map:
                    item_map[item_id] = item

        fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [item_map[item_id] for item_id, _ in fused]

    def hybrid_search(
        self,
        query: str,
        n_results: int = 5,
        filter_expr: Optional[str] = None,
        rrf_k: int = 60,
    ) -> List[Dict[str, Any]]:
        """混合检索：向量检索 + 关键词检索，使用 RRF 融合。

        如果启用 rerank_enabled，会对 RRF 后的 Top-K 候选做交叉编码器重排。
        """
        vector_results = self.search(query, n_results=n_results * 3, filter_expr=filter_expr)
        keyword_results = self.keyword_search(query, n_results=n_results * 3, filter_expr=filter_expr)

        fused = self._rrf_fuse([vector_results, keyword_results], k=rrf_k)
        candidates = fused[:n_results]

        if self.rerank_enabled and candidates:
            reranked = self.rerank(query, candidates, top_k=n_results)
            return reranked
        return candidates

    def _get_reranker(self) -> _CrossEncoderReranker:
        if self._reranker is None:
            self._reranker = _CrossEncoderReranker(
                self.rerank_model,
                model_path=self.rerank_model_path or None,
            )
        return self._reranker

    def rerank(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """使用交叉编码器对候选 chunk 重排序。"""
        if not chunks:
            return []
        top_k = top_k or self.rerank_top_k
        try:
            reranker = self._get_reranker()
            reranked = reranker.rerank(query, chunks[:top_k])
            return reranked
        except Exception as e:
            log.warning("Rerank failed: %s", e)
            return chunks[:top_k]

    def clear(self, filter_expr: Optional[str] = None) -> None:
        """清空 collection。

        未提供 filter_expr 时 drop 整个 collection 后重建；
        提供 filter_expr 时仅删除匹配的数据。
        """
        if not self.client.has_collection(self.collection_name):
            self._ensure_collection()
            return

        if filter_expr:
            self._load()
            self.client.delete(
                collection_name=self.collection_name,
                filter=filter_expr,
            )
            log.info(
                "Deleted chunks from collection %s matching: %s",
                self.collection_name,
                filter_expr,
            )
        else:
            self.client.drop_collection(self.collection_name)
            log.info("Dropped Milvus collection %s", self.collection_name)
            self._ensure_collection()

    def stats(self, filter_expr: Optional[str] = None) -> Dict[str, Any]:
        """统计信息。"""
        self._load()
        if not filter_expr:
            stats = self.client.get_collection_stats(self.collection_name)
            return {"total_chunks": stats.get("row_count", 0)}

        results = self.client.query(
            collection_name=self.collection_name,
            filter=filter_expr,
            output_fields=["id"],
        )
        return {"total_chunks": len(results)}
