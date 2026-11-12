"""MCP 层测试：内存客户端直连 server 对象，不起子进程、不走 stdio。"""

from importlib.metadata import version

import pytest
from mcp import Client

from travelkb.server import mcp


@pytest.fixture
async def client():
    # raise_exceptions=True：server 内部异常直接抛进测试，而不是被包成 is_error 结果
    async with Client(mcp, raise_exceptions=True) as c:
        yield c


@pytest.mark.anyio
async def test_ping_returns_structured_content(client: Client):
    result = await client.call_tool("ping", {})

    assert result.is_error is False
    assert result.structured_content == {
        "ok": True,
        "server_version": version("travel-kb"),
    }


@pytest.mark.anyio
async def test_real_server_loads_data_directory(client: Client):
    # Claude Desktop 启动的就是这个模块级 server：它必须真的读了 data/pois/，
    # 否则单元测试（都用假数据）全绿，Desktop 里却什么都查不到
    result = await client.call_tool("resolve_poi", {"query": "美术馆", "city": "Budapest"})

    assert [c["poi_id"] for c in result.structured_content["candidates"]] == [
        "hungarian-national-gallery",
        "museum-of-fine-arts-budapest",
    ]


@pytest.mark.anyio
async def test_ping_is_read_only(client: Client):
    tools = (await client.list_tools()).tools
    ping = next(t for t in tools if t.name == "ping")

    assert ping.annotations is not None
    assert ping.annotations.read_only_hint is True


@pytest.mark.anyio
async def test_module_server_reads_pinned_today_from_env(monkeypatch):
    # 评测时 claude 按 mcp.json 启动的就是这个模块级 server，env 里的 TRAVELKB_TODAY 必须真的生效。
    # 模块在 import 时组装 server，所以要设好环境变量后重新加载；结束后恢复成不钉的版本
    import importlib

    import travelkb.server as server_module

    monkeypatch.setenv("TRAVELKB_TODAY", "2026-10-12")  # 周一；真实数据 10-08 核验
    try:
        reloaded = importlib.reload(server_module)
        async with Client(reloaded.mcp, raise_exceptions=True) as c:
            result = await c.call_tool("is_open", {"poi_id": "hungarian-national-gallery"})
    finally:
        monkeypatch.delenv("TRAVELKB_TODAY")
        importlib.reload(server_module)

    content = result.structured_content
    assert content["date"] == "2026-10-12"
    assert content["status"] == "CLOSED"  # 国家美术馆周一闭馆
    assert content["warnings"] == []  # 核验后第 4 天，不过期
