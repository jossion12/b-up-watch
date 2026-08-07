"""RagFlow 同步与客户端测试。"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.config import get_settings
from app.rag.ragflow_client import RagFlowClient, RagFlowError


@pytest.fixture()
def ragflow_env(monkeypatch):
    monkeypatch.setenv("RAGFLOW_BASE_URL", "http://127.0.0.1:9380")
    monkeypatch.setenv("RAGFLOW_API_KEY", "test-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_create_dataset(ragflow_env):
    async with RagFlowClient() as client:
        with respx.mock(base_url="http://127.0.0.1:9380") as routes:
            route = routes.post("/api/v1/datasets").respond(
                200,
                json={
                    "code": 0,
                    "data": {
                        "id": "ds_123",
                        "name": "test_up",
                        "embedding_model": "BAAI/bge-large-zh-v1.5@BAAI",
                        "chunk_method": "naive",
                    },
                },
            )
            result = await client.create_dataset("test_up")
            assert result["id"] == "ds_123"
            assert route.called
            body = json.loads(route.calls[0].request.content)
            assert body["language"] == "Chinese"


@pytest.mark.asyncio
async def test_api_error_raises_ragflow_error(ragflow_env):
    async with RagFlowClient() as client:
        with respx.mock(base_url="http://127.0.0.1:9380") as routes:
            routes.get("/api/v1/datasets").respond(
                200,
                json={"code": 102, "message": "The dataset doesn't exist"},
            )
            with pytest.raises(RagFlowError) as exc_info:
                await client.list_datasets(name="missing")
            assert exc_info.value.code == "RAGFLOW_API_ERROR"


@pytest.mark.asyncio
async def test_unconfigured_client_raises(monkeypatch):
    monkeypatch.setenv("RAGFLOW_BASE_URL", "")
    monkeypatch.setenv("RAGFLOW_API_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(RagFlowError) as exc_info:
        RagFlowClient(base_url="", api_key="")
    assert exc_info.value.code == "RAGFLOW_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_get_or_create_dataset_uses_existing_by_id(ragflow_env):
    async with RagFlowClient() as client:
        with respx.mock(base_url="http://127.0.0.1:9380") as routes:
            routes.get("/api/v1/datasets", params={"id": "ds_existing"}).respond(
                200,
                json={
                    "code": 0,
                    "data": [
                        {
                            "id": "ds_existing",
                            "name": "test_up",
                            "embedding_model": "BAAI/bge-large-zh-v1.5@BAAI",
                            "chunk_method": "naive",
                        }
                    ],
                },
            )
            result = await client.get_or_create_dataset(
                "test_up",
                dataset_id="ds_existing",
            )
            assert result["id"] == "ds_existing"


@pytest.mark.asyncio
async def test_get_or_create_dataset_fallback_when_id_inaccessible(ragflow_env):
    async with RagFlowClient() as client:
        with respx.mock(base_url="http://127.0.0.1:9380") as routes:
            routes.get("/api/v1/datasets", params={"id": "ds_inaccessible"}).respond(
                200,
                json={
                    "code": 102,
                    "message": "User 'u1' lacks permission for dataset 'test_up'",
                },
            )
            routes.get("/api/v1/datasets", params={"name": "test_up"}).respond(
                200,
                json={
                    "code": 0,
                    "data": [
                        {
                            "id": "ds_fallback",
                            "name": "test_up",
                            "embedding_model": "BAAI/bge-large-zh-v1.5@BAAI",
                            "chunk_method": "naive",
                        }
                    ],
                },
            )
            result = await client.get_or_create_dataset(
                "test_up",
                dataset_id="ds_inaccessible",
            )
            assert result["id"] == "ds_fallback"


@pytest.mark.asyncio
async def test_get_or_create_dataset_creates_when_name_permission_denied(
    ragflow_env,
):
    async with RagFlowClient() as client:
        with respx.mock(base_url="http://127.0.0.1:9380") as routes:
            routes.get("/api/v1/datasets", params={"name": "test_up"}).respond(
                200,
                json={
                    "code": 102,
                    "message": "User 'u1' lacks permission for dataset 'test_up'",
                },
            )
            create_route = routes.post("/api/v1/datasets").respond(
                200,
                json={
                    "code": 0,
                    "data": {
                        "id": "ds_new",
                        "name": "test_up",
                        "embedding_model": "BAAI/bge-large-zh-v1.5@BAAI",
                        "chunk_method": "naive",
                    },
                },
            )
            result = await client.get_or_create_dataset("test_up")
            assert result["id"] == "ds_new"
            assert create_route.called


@pytest.mark.asyncio
async def test_get_or_create_dataset_retries_with_suffix_on_duplicate_name(
    ragflow_env,
):
    async with RagFlowClient() as client:
        with respx.mock(base_url="http://127.0.0.1:9380") as routes:
            routes.get("/api/v1/datasets", params={"name": "test_up"}).respond(
                200,
                json={
                    "code": 102,
                    "message": "User 'u1' lacks permission for dataset 'test_up'",
                },
            )
            create_route = routes.post("/api/v1/datasets")
            create_route.side_effect = [
                httpx.Response(
                    200,
                    json={"code": 102, "message": "Duplicated dataset name."},
                ),
                httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "data": {
                            "id": "ds_new",
                            "name": "test_up_suffix",
                            "embedding_model": "BAAI/bge-large-zh-v1.5@BAAI",
                            "chunk_method": "naive",
                        },
                    },
                ),
            ]
            result = await client.get_or_create_dataset("test_up")
            assert result["id"] == "ds_new"
            assert result["name"].startswith("test_up_")
            assert create_route.call_count == 2


@pytest.mark.asyncio
async def test_list_documents_paginates(ragflow_env):
    async with RagFlowClient() as client:
        with respx.mock(base_url="http://127.0.0.1:9380") as routes:
            list_route = routes.get(
                "/api/v1/datasets/ds_1/documents",
            ).mock(side_effect=[
                httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "data": {
                            "docs": [
                                {"id": "doc_1", "name": "a.md"},
                                {"id": "doc_2", "name": "b.md"},
                            ],
                        },
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "data": {
                            "docs": [
                                {"id": "doc_3", "name": "c.md"},
                            ],
                        },
                    },
                ),
            ])
            result = await client.list_documents("ds_1", page_size=2)
            assert len(result) == 3
            assert list_route.call_count == 2


@pytest.mark.asyncio
async def test_list_documents_caps_page_size(ragflow_env):
    async with RagFlowClient() as client:
        with respx.mock(base_url="http://127.0.0.1:9380") as routes:
            list_route = routes.get(
                "/api/v1/datasets/ds_1/documents",
            ).respond(
                200,
                json={
                    "code": 0,
                    "data": {
                        "docs": [
                            {"id": "doc_1", "name": "a.md"},
                        ],
                    },
                },
            )
            await client.list_documents("ds_1", page_size=1000)
            assert list_route.called
            assert list_route.calls[0].request.url.params["page_size"] == "100"
