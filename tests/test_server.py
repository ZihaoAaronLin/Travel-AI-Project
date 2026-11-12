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


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("query", "status", "poi_ids"),
    [
        # 需要 data/cities.yaml 里有 Budapest: [布达佩斯]
        (
            "布达佩斯的美术馆",
            "AMBIGUOUS",
            ["hungarian-national-gallery", "museum-of-fine-arts-budapest"],
        ),
        ("布达佩斯美术馆", "MATCH", ["museum-of-fine-arts-budapest"]),  # 正式名称，原样命中
        ("沃伊达奇城堡里的农业博物馆", "MATCH", ["hungarian-museum-of-agriculture"]),
        ("渔人堡的收费观景台", "MATCH", ["fishermans-bastion-terrace"]),
        (
            "圣史蒂芬大教堂的教堂大厅",
            "AMBIGUOUS",
            ["st-stephens-basilica-church", "st-stephens-basilica-panorama-treasury"],
        ),
        ("维也纳的国会大厦", "NOT_FOUND", []),  # 库里没有维也纳，不能退成布达佩斯的国会大厦
    ],
)
async def test_real_server_resolves_how_users_talk(client: Client, query, status, poi_ids):
    # 题库和 Desktop 里真实出现过的说法；不给 city，模拟模型把原话直接传进来
    result = await client.call_tool("resolve_poi", {"query": query})

    assert result.structured_content["status"] == status
    assert [c["poi_id"] for c in result.structured_content["candidates"]] == poi_ids
