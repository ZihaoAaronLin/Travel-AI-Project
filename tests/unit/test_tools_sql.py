"""2e：query_kb / describe_schema 两个工具。默认不注册，只给 A2 对照组用。

为什么默认不注册：窄接口工具（is_open 等）由代码判定，结论可测；query_kb 把判定交还给模型写的 SQL，
只用来在评测里回答「让模型自己写 SQL 行不行」（H2）。Desktop 日常使用不该看到它。

接口：
- build_server(pois, ..., sql_kb=ReadOnlyKB | None)：给了才注册这两个工具，都是只读
- SQL_ENV = "TRAVELKB_ENABLE_SQL"；sql_kb_from_env(env, db_path) -> ReadOnlyKB | None
  没设或 "0" → None；"1" → 打开 db_path（不存在就启动失败，提示先跑 build_db.py）；
  其他值 → ValueError（写错了不能悄悄当成没开）
- query_kb(sql) → {columns, rows, truncated}；被拒 → 工具错误，消息给模型看
- describe_schema() → {tables: [{name, columns}]}
"""

import sqlite3

import pytest
from mcp import Client

from travelkb.server import SQL_ENV, build_server, sql_kb_from_env
from travelkb.sql.readonly import ReadOnlyKB

SQL_TOOLS = {"query_kb", "describe_schema"}


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "kb.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE pois(id TEXT PRIMARY KEY, city TEXT);"
        "INSERT INTO pois VALUES ('demo-a', 'Budapest'), ('demo-b', 'Vienna');"
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
async def client(make_poi, db_path):
    server = build_server([make_poi()], sql_kb=ReadOnlyKB(db_path))
    async with Client(server, raise_exceptions=True) as c:
        yield c


def error_text(result) -> str:
    return " ".join(getattr(block, "text", "") for block in result.content)


# ---- 注册 ----


@pytest.mark.anyio
async def test_sql_tools_are_not_registered_by_default(make_poi):
    async with Client(build_server([make_poi()]), raise_exceptions=True) as c:
        names = {t.name for t in (await c.list_tools()).tools}

    assert names & SQL_TOOLS == set()


@pytest.mark.anyio
async def test_sql_tools_are_registered_and_read_only(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}

    assert SQL_TOOLS <= tools.keys()
    for name in SQL_TOOLS:
        assert tools[name].annotations.read_only_hint is True


@pytest.mark.anyio
async def test_query_kb_description_points_to_describe_schema(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}

    assert "describe_schema" in tools["query_kb"].description
    assert "SELECT" in tools["query_kb"].description


# ---- 调用 ----


@pytest.mark.anyio
async def test_query_kb_returns_rows(client):
    result = await client.call_tool("query_kb", {"sql": "SELECT id FROM pois ORDER BY id"})

    assert result.is_error is False
    assert result.structured_content == {
        "columns": ["id"],
        "rows": [["demo-a"], ["demo-b"]],
        "truncated": False,
    }


@pytest.mark.anyio
async def test_rejected_sql_is_reported_to_the_model(client):
    result = await client.call_tool("query_kb", {"sql": "DROP TABLE pois"})

    assert result.is_error is True
    assert "SELECT" in error_text(result)


@pytest.mark.anyio
async def test_describe_schema_lists_tables(client):
    result = await client.call_tool("describe_schema", {})

    assert result.structured_content == {"tables": [{"name": "pois", "columns": ["id", "city"]}]}


# ---- 环境变量 ----


def test_env_name_is_the_documented_one():
    assert SQL_ENV == "TRAVELKB_ENABLE_SQL"


@pytest.mark.parametrize("env", [{}, {SQL_ENV: "0"}])
def test_sql_is_off_unless_enabled(env, db_path):
    assert sql_kb_from_env(env, db_path) is None


def test_enabled_opens_the_database(db_path):
    kb = sql_kb_from_env({SQL_ENV: "1"}, db_path)

    assert kb.query("SELECT count(*) AS n FROM pois").rows == [[2]]


def test_enabled_without_database_fails_at_startup(tmp_path):
    with pytest.raises(FileNotFoundError, match="build_db"):
        sql_kb_from_env({SQL_ENV: "1"}, tmp_path / "missing.sqlite")


@pytest.mark.parametrize("value", ["yes", "true", ""])
def test_bad_value_fails_loudly(value, db_path):
    with pytest.raises(ValueError, match=SQL_ENV):
        sql_kb_from_env({SQL_ENV: value}, db_path)
