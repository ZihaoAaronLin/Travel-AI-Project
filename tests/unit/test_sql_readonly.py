"""2e：query_kb 背后的只读执行层。模型写的 SQL 原样进来，这一层保证它什么都改不了、也跑不死。

防护分层（ROADMAP 第 2 阶段；CC 在 SQLite 3.45 上逐条实测过，下面每种攻击都能挡住）：
1. 只读打开：file:…?mode=ro
2. PRAGMA query_only = ON
3. authorizer 只放行 SELECT / READ / FUNCTION / RECURSIVE（递归 CTE 用来逐日枚举日期）
4. 一次一条语句（sqlite3 的 execute 本身就拒绝多条）
5. progress handler 超时中断
6. 行数上限
7. 不返回结果列的语句一律拒绝。实测：空串、纯注释都能「成功」执行、什么也不返回，
   不拦的话模型会以为查到了「零行」
另有 schema()：authorizer 连读 PRAGMA 也拦，模型自己查不到列名，由它告诉模型有哪些表和列。

接口：travelkb.sql.readonly
- ReadOnlyKB(path, max_rows=200, timeout_s=0.5)
  文件不存在 → FileNotFoundError，提示先跑 build_db.py
- kb.query(sql) -> QueryResult(columns: list[str], rows: list[list], truncated: bool)
- kb.schema() -> list[TableSchema(name, columns: list[str])]，按表名排序，不含 sqlite 内部表
- 拒绝一律抛 QueryRejected，消息是写给模型看的：为什么被拒、该怎么改
"""

import hashlib
import sqlite3
import time

import pytest

from travelkb.sql.readonly import QueryRejected, ReadOnlyKB

# 递归生成 1..n 的整数，用来造多行结果
SERIES = (
    "WITH RECURSIVE s(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM s WHERE n < {n}) SELECT n FROM s"
)


@pytest.fixture
def db_path(tmp_path):
    """和 build_database 无关的一个小库：这一层只管「怎么执行」，不管表是怎么建的。"""
    path = tmp_path / "kb.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE pois(id TEXT PRIMARY KEY, city TEXT, verified_at TEXT);
        CREATE INDEX pois_city ON pois(city);
        INSERT INTO pois VALUES
            ('demo-a', 'Budapest', '2026-10-08'),
            ('demo-b', 'Budapest', '2026-10-08'),
            ('demo-c', 'Vienna', '2026-10-01');
        """
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def kb(db_path):
    return ReadOnlyKB(db_path, max_rows=5, timeout_s=0.5)


# ---- 正常查询 ----


def test_select_returns_columns_and_rows(kb):
    result = kb.query("SELECT id, city FROM pois WHERE city = 'Budapest' ORDER BY id")

    assert result.columns == ["id", "city"]
    assert result.rows == [["demo-a", "Budapest"], ["demo-b", "Budapest"]]
    assert result.truncated is False


def test_trailing_semicolon_is_fine(kb):
    assert kb.query("SELECT id FROM pois ORDER BY id;").rows == [["demo-a"], ["demo-b"], ["demo-c"]]


def test_bounded_recursive_cte_can_enumerate_dates(kb):
    # 模型算「某段时间里有哪些周一」最自然的写法；允许 RECURSIVE 就是为了这个
    sql = (
        "WITH RECURSIVE d(day) AS (SELECT '2026-10-01' UNION ALL "
        "SELECT date(day, '+1 day') FROM d WHERE day < '2026-10-03') SELECT day FROM d"
    )
    assert kb.query(sql).rows == [["2026-10-01"], ["2026-10-02"], ["2026-10-03"]]


def test_row_cap_truncates(kb):
    result = kb.query(SERIES.format(n=20))

    assert result.rows == [[1], [2], [3], [4], [5]]
    assert result.truncated is True


def test_exactly_max_rows_is_not_truncated(kb):
    assert kb.query(SERIES.format(n=5)).truncated is False


def test_schema_lists_tables_and_columns(kb):
    assert [(t.name, t.columns) for t in kb.schema()] == [("pois", ["id", "city", "verified_at"])]


# ---- 攻击：每种一条 ----

ATTACKS = [
    "DROP TABLE pois",
    "DELETE FROM pois",
    "UPDATE pois SET city = 'x'",
    "INSERT INTO pois VALUES ('x', 'y', 'z')",
    "WITH x AS (SELECT 1) DELETE FROM pois",  # 写操作藏在 CTE 后面
    "CREATE TABLE t(x)",
    "CREATE TEMP TABLE t(x)",  # 临时表不写库文件，但只读库上也不该能建
    "CREATE INDEX i ON pois(verified_at)",
    "ATTACH DATABASE ':memory:' AS m",
    "PRAGMA query_only = OFF",  # 想先关掉第 2 层
    "PRAGMA table_info(pois)",  # 读 PRAGMA 也拦：列名由 schema() 提供
    "VACUUM",
    "ANALYZE",  # 会写 sqlite_stat1
    "REINDEX",
    "SELECT 1; DROP TABLE pois",  # 第二条语句
    "SELECT load_extension('evil')",  # 加载任意本地代码
    "SELECT length(zeroblob(2000000000))",  # 想撑爆内存
    "",
    "   ",
    "-- 只有注释",
]


@pytest.mark.parametrize("sql", ATTACKS)
def test_attack_is_rejected(kb, sql):
    with pytest.raises(QueryRejected):
        kb.query(sql)


def test_vacuum_into_cannot_create_a_file(kb, tmp_path):
    # VACUUM INTO 能把整个库复制成一个新文件：等于往磁盘上任意位置写东西
    target = tmp_path / "copy.sqlite"

    with pytest.raises(QueryRejected):
        kb.query(f"VACUUM INTO '{target}'")
    assert not target.exists()


def test_runaway_query_is_interrupted(kb):
    endless = (
        "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT count(*) FROM r"
    )
    started = time.monotonic()

    with pytest.raises(QueryRejected, match="超时"):
        kb.query(endless)
    assert time.monotonic() - started < 2


def test_database_is_byte_for_byte_unchanged_after_every_attack(kb, db_path):
    def snapshot():
        files = sorted(p.name for p in db_path.parent.iterdir())
        return files, hashlib.sha256(db_path.read_bytes()).hexdigest()

    before = snapshot()
    for sql in ATTACKS:
        with pytest.raises(QueryRejected):
            kb.query(sql)
    assert snapshot() == before  # 内容一字节没变，也没留下 -journal / -wal 之类的文件


def test_rejection_tells_the_model_what_is_allowed(kb):
    with pytest.raises(QueryRejected, match="SELECT"):
        kb.query("DROP TABLE pois")


def test_missing_database_points_to_build_script(tmp_path):
    with pytest.raises(FileNotFoundError, match="build_db"):
        ReadOnlyKB(tmp_path / "missing.sqlite")
    assert not (tmp_path / "missing.sqlite").exists()  # 只读打开不会顺手建一个空库
