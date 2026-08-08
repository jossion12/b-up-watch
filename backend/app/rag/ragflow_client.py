"""RagFlow HTTP API 客户端。

封装 dataset、document、chat 的常用操作，统一处理认证与错误码。
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Optional

import httpx

from app.config import get_settings
from app.errors import BizError

log = logging.getLogger(__name__)


class RagFlowError(BizError):
    """RagFlow 上游返回的业务错误。"""

    def __init__(
        self,
        code: str,
        message: str,
        http_status: int = 502,
        details: Optional[dict] = None,
    ) -> None:
        super().__init__(code, message, http_status=http_status, details=details)


def _is_permission_error(exc: RagFlowError) -> bool:
    """判断是否为无权访问他人 dataset/chat 等资源的错误。"""
    msg = (exc.message or "").lower()
    return (
        "lacks permission" in msg
        or "do not own" in msg
        or "don't own" in msg
        or "you do not own" in msg
    )


class RagFlowClient:
    """RagFlow API 异步客户端。"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.ragflow_base_url).rstrip("/")
        self.api_key = api_key or settings.ragflow_api_key
        self.timeout = timeout
        if not self.base_url or not self.api_key:
            raise RagFlowError(
                "RAGFLOW_NOT_CONFIGURED",
                "RagFlow 未配置：请设置 RAGFLOW_BASE_URL 和 RAGFLOW_API_KEY",
                http_status=500,
            )
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "RagFlowClient":
        await self._get_client()
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.close()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
        data: Optional[dict] = None,
        files: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> dict:
        client = await self._get_client()
        try:
            resp = await client.request(
                method,
                path,
                params=params,
                json=json,
                data=data,
                files=files,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            log.warning("ragflow request failed: %s %s err=%s", method, path, exc)
            raise RagFlowError(
                "RAGFLOW_UNREACHABLE",
                f"RagFlow 请求失败: {exc}",
                http_status=502,
            ) from exc

        try:
            body = resp.json()
        except ValueError as exc:
            log.warning(
                "ragflow non-json response: %s %s status=%s body=%s",
                method,
                path,
                resp.status_code,
                resp.text[:200],
            )
            raise RagFlowError(
                "RAGFLOW_BAD_RESPONSE",
                "RagFlow 返回非 JSON 响应",
                http_status=502,
            ) from exc

        code = body.get("code")
        message = body.get("message", "")
        if code != 0:
            log.warning(
                "ragflow api error: %s %s code=%s message=%s",
                method,
                path,
                code,
                message,
            )
            raise RagFlowError(
                "RAGFLOW_API_ERROR",
                message or "RagFlow API 错误",
                http_status=502,
                details={"upstream_code": code, "path": path},
            )
        return body.get("data", {})

    # ---------- Dataset ----------

    async def list_datasets(
        self,
        name: Optional[str] = None,
        dataset_id: Optional[str] = None,
    ) -> list[dict]:
        """列出知识库，可按名称或 ID 精确过滤。"""
        params: dict = {"page": 1, "page_size": 100}
        if name:
            params["name"] = name
        if dataset_id:
            params["id"] = dataset_id
        data = await self._request("GET", "/api/v1/datasets", params=params)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        return []

    async def create_dataset(
        self,
        name: str,
        *,
        embedding_model: Optional[str] = None,
        chunk_method: Optional[str] = None,
        description: str = "",
    ) -> dict:
        """创建知识库。"""
        settings = get_settings()
        body: dict = {"name": name}
        model = embedding_model or settings.ragflow_embedding_model
        if model:
            body["embedding_model"] = model
        method = chunk_method or settings.ragflow_chunk_method or "naive"
        if method:
            body["chunk_method"] = method
        if description:
            body["description"] = description
        return await self._request("POST", "/api/v1/datasets", json=body)

    async def get_or_create_dataset(
        self,
        name: str,
        *,
        embedding_model: Optional[str] = None,
        chunk_method: Optional[str] = None,
        dataset_id: Optional[str] = None,
    ) -> dict:
        """按名称获取 dataset，不存在则创建。

        Args:
            name: dataset 显示名称。
            embedding_model: 嵌入模型。
            chunk_method: 分块方法。
            dataset_id: 上次同步时保存的 dataset ID；若仍可用则直接复用。

        当名称被其他用户占用导致无权限时，会自动追加唯一后缀创建新 dataset，
        避免同名冲突导致同步任务直接失败。
        """
        if dataset_id:
            try:
                existing = await self.list_datasets(dataset_id=dataset_id)
                if existing:
                    return existing[0]
            except RagFlowError as exc:
                if not _is_permission_error(exc):
                    raise
                log.warning(
                    "stored dataset %s no longer accessible: %s",
                    dataset_id,
                    exc.message,
                )

        try:
            existing = await self.list_datasets(name=name)
            if existing:
                return existing[0]
        except RagFlowError as exc:
            if not _is_permission_error(exc):
                raise
            log.warning(
                "dataset name %r is taken by another user, will create with suffix",
                name,
            )

        try:
            return await self.create_dataset(
                name,
                embedding_model=embedding_model,
                chunk_method=chunk_method,
            )
        except RagFlowError as exc:
            if not (
                _is_permission_error(exc)
                or "duplicated" in (exc.message or "").lower()
                or "already exists" in (exc.message or "").lower()
            ):
                raise
            unique_name = f"{name}_{uuid.uuid4().hex[:8]}"
            log.warning(
                "dataset create failed for %r, retrying as %r",
                name,
                unique_name,
            )
            return await self.create_dataset(
                unique_name,
                embedding_model=embedding_model,
                chunk_method=chunk_method,
            )

    async def delete_datasets(self, dataset_ids: list[str]) -> None:
        """批量删除知识库。"""
        if not dataset_ids:
            return
        await self._request("DELETE", "/api/v1/datasets", json={"ids": dataset_ids})

    # ---------- Document ----------

    async def list_documents(
        self,
        dataset_id: str,
        *,
        page_size: int = 100,
    ) -> list[dict]:
        """列出 dataset 内所有文档（自动分页）。

        RagFlow 限制 page_size 最大为 100，超过会自动截断为 100。
        """
        page_size = min(page_size, 100)
        all_docs: list[dict] = []
        page = 1
        while True:
            data = await self._request(
                "GET",
                f"/api/v1/datasets/{dataset_id}/documents",
                params={"page": page, "page_size": page_size},
            )
            docs = data.get("docs") if isinstance(data, dict) else data
            docs = list(docs or [])
            all_docs.extend(docs)
            if len(docs) < page_size:
                break
            page += 1
        return all_docs

    async def upload_document(
        self,
        dataset_id: str,
        file_path: Path,
    ) -> dict:
        """上传本地文件到指定 dataset。"""
        if not file_path.exists():
            raise RagFlowError(
                "RAGFLOW_FILE_NOT_FOUND",
                f"本地文件不存在: {file_path}",
                http_status=500,
            )
        with file_path.open("rb") as f:
            files = {"file": (file_path.name, f, "text/markdown")}
            return await self._request(
                "POST",
                f"/api/v1/datasets/{dataset_id}/documents",
                params={"type": "local"},
                files=files,
            )

    async def delete_documents(self, dataset_id: str, document_ids: list[str]) -> None:
        """批量删除 dataset 内文档。"""
        if not document_ids:
            return
        await self._request(
            "DELETE",
            f"/api/v1/datasets/{dataset_id}/documents",
            json={"ids": document_ids},
        )

    async def parse_documents(self, dataset_id: str, document_ids: list[str]) -> None:
        """启动文档解析。"""
        if not document_ids:
            return
        await self._request(
            "POST",
            f"/api/v1/datasets/{dataset_id}/chunks",
            json={"document_ids": document_ids},
        )

    async def get_document(self, dataset_id: str, document_id: str) -> dict:
        """获取单个文档详情（含解析状态）。"""
        data = await self._request(
            "GET",
            f"/api/v1/datasets/{dataset_id}/documents",
            params={"id": document_id},
        )
        docs = data.get("docs") if isinstance(data, dict) else data
        if docs:
            return docs[0]
        raise RagFlowError(
            "RAGFLOW_DOCUMENT_NOT_FOUND",
            f"文档不存在: {document_id}",
            http_status=404,
        )

    # ---------- Chat ----------

    async def list_chats(self, name: Optional[str] = None) -> list[dict]:
        """列出聊天助手，可按名称精确过滤。"""
        params: dict = {"page": 1, "page_size": 100}
        if name:
            params["name"] = name
        data = await self._request("GET", "/api/v1/chats", params=params)
        return list(data.get("chats") or [])

    async def create_chat(
        self,
        name: str,
        dataset_ids: list[str],
        *,
        prompt_config: Optional[dict] = None,
    ) -> dict:
        """创建聊天助手并关联知识库。"""
        body: dict = {"name": name, "dataset_ids": dataset_ids}
        if prompt_config:
            body["prompt_config"] = prompt_config
        return await self._request("POST", "/api/v1/chats", json=body)

    async def update_chat(
        self,
        chat_id: str,
        *,
        dataset_ids: Optional[list[str]] = None,
        name: Optional[str] = None,
    ) -> dict:
        """局部更新聊天助手。"""
        body: dict = {}
        if dataset_ids is not None:
            body["dataset_ids"] = dataset_ids
        if name is not None:
            body["name"] = name
        if not body:
            return {}
        return await self._request("PATCH", f"/api/v1/chats/{chat_id}", json=body)

    async def delete_chat(self, chat_id: str) -> None:
        """删除单个聊天助手。"""
        await self._request("DELETE", f"/api/v1/chats/{chat_id}")

    async def delete_chats(self, chat_ids: list[str]) -> None:
        """批量删除聊天助手。"""
        if not chat_ids:
            return
        await self._request("DELETE", "/api/v1/chats", json={"ids": chat_ids})
