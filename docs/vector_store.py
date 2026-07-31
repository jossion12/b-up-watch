#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[已弃用] 将观点卡片JSON写入 Chroma 向量库，支持检索+对话

该独立脚本为早期原型，其功能已合并进后端 RAG 模块：
- 向量库存储：backend/app/rag/milvus_store.py（使用 Milvus 替代 Chroma）
- 服务编排：backend/app/rag/service.py
- REST API：backend/app/api/rag.py

后续请优先使用后端服务与 API；该脚本不再维护，并可能在将来删除。

依赖：
    pip install chromadb sentence-transformers

用法：
    python vector_store.py --input rag_chunks.json --db_path ./chroma_db --collection video_opinions
"""

import json
import argparse
import os
from typing import List, Dict


class OpinionVectorStore:
    """基于Chroma的观点向量库"""

    def __init__(self, db_path: str, collection_name: str = "video_opinions"):
        import chromadb
        from chromadb.config import Settings

        self.client = chromadb.PersistentClient(
            path=db_path,
            settings=Settings(anonymized_telemetry=False)
        )
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"description": "UP主视频观点卡片"}
        )

        # 使用本地embedding模型（无需API）
        from sentence_transformers import SentenceTransformer
        self.embedder = SentenceTransformer('BAAI/bge-large-zh-v1.5')
        print(f"[VectorStore] 已加载 embedding 模型: BAAI/bge-large-zh-v1.5")

    def add_chunks(self, chunks: List[Dict]):
        """批量写入观点卡片"""
        documents = []
        metadatas = []
        ids = []

        for c in chunks:
            # 构建增强文本：把metadata中的关键信息拼接到content里，提升检索精度
            meta = c.get("metadata", {})
            enriched_text = self._enrich_text(c["content"], meta)

            documents.append(enriched_text)
            metadatas.append({
                "chunk_id": c["chunk_id"],
                "video_title": meta.get("video_title", ""),
                "up_name": meta.get("up_name", ""),
                "time_position": meta.get("time_position", ""),
                "content_type": meta.get("content_type", ""),
                "argument_role": meta.get("argument_role", ""),
                "core_topic": meta.get("core_topic", ""),
                "stance_type": meta.get("stance_type", ""),
                "confidence": meta.get("confidence", ""),
                "original_arguments": json.dumps(meta.get("original_arguments", []), ensure_ascii=False)
            })
            ids.append(c["chunk_id"])

        # 生成向量
        print(f"[VectorStore] 正在编码 {len(documents)} 个文档...")
        embeddings = self.embedder.encode(documents, show_progress_bar=True).tolist()

        # 写入
        self.collection.add(
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        print(f"[VectorStore] 已写入 {len(ids)} 条记录")

    def _enrich_text(self, content: str, meta: Dict) -> str:
        """
        增强文本：把结构化metadata拼接到content中，让向量检索更精准
        例如：用户搜"长鑫科技 预测"，能匹配到core_topic和stance_type
        """
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

    def search(
        self,
        query: str,
        n_results: int = 5,
        filters: Dict = None
    ) -> List[Dict]:
        """
        检索观点卡片
        Args:
            query: 用户问题
            n_results: 返回数量
            filters: metadata过滤条件，如 {"up_name": "科技袁人", "stance_type": "预测"}
        """
        query_embedding = self.embedder.encode([query]).tolist()

        kwargs = {
            "query_embeddings": query_embedding,
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"]
        }
        if filters:
            kwargs["where"] = filters

        results = self.collection.query(**kwargs)

        output = []
        for i in range(len(results["ids"][0])):
            meta = results["metadatas"][0][i]
            output.append({
                "chunk_id": results["ids"][0][i],
                "content": results["documents"][0][i],
                "distance": results["distances"][0][i],
                "metadata": {
                    **meta,
                    "original_arguments": json.loads(meta.get("original_arguments", "[]"))
                }
            })
        return output

    def search_by_topic(self, topic: str, n_results: int = 10) -> List[Dict]:
        """按主题检索（利用metadata过滤加速）"""
        return self.search(
            query=topic,
            n_results=n_results,
            filters={"core_topic": {"$contains": topic}}
        )

    def search_by_stance(self, stance: str, n_results: int = 10) -> List[Dict]:
        """按立场检索"""
        return self.search(
            query=stance,
            n_results=n_results,
            filters={"stance_type": stance}
        )

    def stats(self) -> Dict:
        """统计信息"""
        count = self.collection.count()
        return {"total_chunks": count}


# ============================================================
# 对话Agent封装
# ============================================================

class OpinionRAGAgent:
    """基于观点卡片的对话Agent"""

    SYSTEM_PROMPT = """你是一位视频观点分析助手。你的回答必须基于检索到的UP主观点片段。

规则：
1. 每个观点必须标注来源：UP主名 + 视频标题 + 时间戳
2. 如果多个UP主观点冲突，必须并列呈现，不要强行调和
3. 区分「事实陈述」和「主观观点」，用不同语气表述
4. 如果检索片段不足以回答问题，明确说"根据现有资料无法判断"
5. 用户追问证据时，引用原始论据列表
6. 对于预测类观点，标注UP主给出该预测的时间
"""

    def __init__(self, vector_store: OpinionVectorStore, api_key: str, base_url: str, model: str):
        from openai import OpenAI
        self.llm = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.store = vector_store

    def chat(self, question: str, n_results: int = 5) -> str:
        """单轮对话"""
        # 1. 检索
        chunks = self.store.search(question, n_results=n_results)
        if not chunks:
            return "根据现有资料库，没有找到相关观点。"

        # 2. 构建上下文
        context = self._build_context(chunks)

        # 3. 调用LLM
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": f"检索到的观点片段：\n{context}\n\n用户问题：{question}"}
        ]

        resp = self.llm.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3
        )
        return resp.choices[0].message.content

    def _build_context(self, chunks: List[Dict]) -> str:
        lines = []
        for i, c in enumerate(chunks, 1):
            meta = c["metadata"]
            lines.append(f"【片段{i}】")
            lines.append(f"来源: {meta.get('up_name', '未知UP主')}《{meta.get('video_title', '未知标题')}》{meta.get('time_position', '')}")
            lines.append(f"类型: {meta.get('content_type', '')} | 角色: {meta.get('argument_role', '')} | 立场: {meta.get('stance_type', '')}")
            lines.append(f"内容: {c['content']}")
            args = meta.get("original_arguments", [])
            if args:
                lines.append(f"论据: {'; '.join(args)}")
            lines.append("")
        return "\n".join(lines)


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="观点卡片向量库管理")
    sub = parser.add_subparsers(dest="command")

    # ingest
    p_ingest = sub.add_parser("ingest", help="导入JSON到向量库")
    p_ingest.add_argument("--input", "-i", required=True, help="rag_chunks.json")
    p_ingest.add_argument("--db", "-d", default="./chroma_db", help="向量库路径")
    p_ingest.add_argument("--collection", "-c", default="video_opinions")

    # search
    p_search = sub.add_parser("search", help="检索")
    p_search.add_argument("query", help="查询语句")
    p_search.add_argument("--db", "-d", default="./chroma_db")
    p_search.add_argument("--collection", "-c", default="video_opinions")
    p_search.add_argument("--n", type=int, default=5)

    # chat
    p_chat = sub.add_parser("chat", help="对话")
    p_chat.add_argument("question", help="问题")
    p_chat.add_argument("--db", "-d", default="./chroma_db")
    p_chat.add_argument("--collection", "-c", default="video_opinions")
    p_chat.add_argument("--model", "-m", default="kimi-latest")
    p_chat.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY", ""))
    p_chat.add_argument("--base-url", default=os.getenv("OPENAI_BASE_URL", "https://api.moonshot.cn/v1"))

    args = parser.parse_args()

    if args.command == "ingest":
        with open(args.input, 'r', encoding='utf-8') as f:
            chunks = json.load(f)
        store = OpinionVectorStore(args.db, args.collection)
        store.add_chunks(chunks)
        print(f"统计: {store.stats()}")

    elif args.command == "search":
        store = OpinionVectorStore(args.db, args.collection)
        results = store.search(args.query, n_results=args.n)
        for r in results:
            print(f"\n[{r['chunk_id']}] 距离: {r['distance']:.4f}")
            print(f"内容: {r['content'][:200]}...")
            print(f"元数据: {r['metadata']}")

    elif args.command == "chat":
        if not args.api_key:
            print("错误: 请设置 OPENAI_API_KEY")
            return
        store = OpinionVectorStore(args.db, args.collection)
        agent = OpinionRAGAgent(store, args.api_key, args.base_url, args.model)
        answer = agent.chat(args.question)
        print(f"\n🤖 回答:\n{answer}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
