"""2e：scripts/build_db.py 背后的 build_database：把景点写成 SQLite 事实表。

只给 query_kb 用（A2 对照组：模型自己写 SQL）。
resolve_poi / is_open 等窄接口工具照旧读 YAML，不经过这里。

表结构（测试钉死，改要先问 Aaron）：
- pois(id, city, country, tz, category, status, review, name_local, name_en, name_zh,
       source_url, verified_at)
- aliases(poi_id, alias)
- rules(poi_id, rule_id, valid_from, valid_to, closed, open, close, last_entry, outside_hours)
- rule_days(poi_id, rule_id, weekday)              weekday 是 MON…SUN，每天一行
- exceptions(poi_id, exception_id, reason, closed, open, close, last_entry, outside_hours, rrule)
- exception_days(poi_id, exception_id, day)        三种写法都展开成具体日期，rrule 只展开 valid 之内

日期一律 YYYY-MM-DD、时刻一律 HH:MM 文本：字符串比较就是时间先后，模型写 SQL 不用转换。
closed 是 0 / 1。rrule 原文保留，但模型不用自己展开：exception_days 已经展开好了
（和引擎用同一个 DayException.days()）。
90 天信任窗口不单独建列：校验已经保证每条规则的 valid 落在窗口内，valid_from / valid_to 就是答案。

接口：travelkb.sql.build.build_database(pois, path)；目标文件已存在就整个替换。
"""

import datetime as dt
import sqlite3
from pathlib import Path

import pytest

from travelkb.core.loader import load_pois
from travelkb.sql.build import build_database

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "pois"

EXPECTED_COLUMNS = {
    "pois": [
        "id", "city", "country", "tz", "category", "status", "review",
        "name_local", "name_en", "name_zh", "source_url", "verified_at",
    ],
    "aliases": ["poi_id", "alias"],
    "rules": [
        "poi_id", "rule_id", "valid_from", "valid_to",
        "closed", "open", "close", "last_entry", "outside_hours",
    ],
    "rule_days": ["poi_id", "rule_id", "weekday"],
    "exceptions": [
        "poi_id", "exception_id", "reason",
        "closed", "open", "close", "last_entry", "outside_hours", "rrule",
    ],
    "exception_days": ["poi_id", "exception_id", "day"],
}  # fmt: skip


@pytest.fixture
def museum(make_poi):
    """假博物馆（周二到周日 10–18、最后入场 17、周一闭馆）加上三种写法的例外。"""
    return make_poi(
        exceptions=[
            {"id": "e1", "date": dt.date(2026, 10, 20), "closed": True, "reason": "临时闭馆"},
            {
                "id": "e2",
                "dates": [dt.date(2026, 12, 24), dt.date(2026, 12, 26)],
                "closed": True,
                "reason": "圣诞",
            },
            {
                "id": "e3",
                "rrule": "FREQ=MONTHLY;BYDAY=-1MO",
                "valid": [dt.date(2026, 10, 1), dt.date(2026, 12, 31)],
                "closed": True,
                "reason": "每月最后一个周一",
            },
            {
                "id": "e4",
                "date": dt.date(2026, 11, 13),
                "open": "12:00",
                "close": "20:00",
                "last_entry": "19:00",
                "reason": "延长开放",
            },
        ]
    )


@pytest.fixture
def db(tmp_path, museum, make_poi):
    path = tmp_path / "kb.sqlite"
    build_database([museum, make_poi(id="demo-other", aliases=[])], path)
    conn = sqlite3.connect(path)
    yield conn
    conn.close()


def rows(conn, sql: str) -> list[tuple]:
    return conn.execute(sql).fetchall()


def test_tables_and_columns(db):
    tables = {name for (name,) in rows(db, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert tables == set(EXPECTED_COLUMNS)
    for table, columns in EXPECTED_COLUMNS.items():
        assert [col[1] for col in rows(db, f"PRAGMA table_info({table})")] == columns


def test_poi_row(db):
    assert rows(db, "SELECT * FROM pois WHERE id = 'demo-museum'") == [
        (
            "demo-museum", "Budapest", "HU", "Europe/Budapest", "museum", "OPEN", "draft",
            "Példa Múzeum", "Demo Museum", "示例博物馆",
            "https://example.org/demo-museum/hours", "2026-10-01",
        )
    ]  # fmt: skip


def test_one_row_per_alias(db):
    assert rows(db, "SELECT alias FROM aliases WHERE poi_id = 'demo-museum'") == [("示例馆",)]
    assert rows(db, "SELECT alias FROM aliases WHERE poi_id = 'demo-other'") == []


def test_rules_keep_dates_and_times_as_text(db):
    got = rows(
        db,
        "SELECT rule_id, valid_from, valid_to, closed, open, close, last_entry, outside_hours "
        "FROM rules WHERE poi_id = 'demo-museum' ORDER BY rule_id",
    )
    assert got == [
        ("r1", "2026-10-01", "2026-12-31", 0, "10:00", "18:00", "17:00", "CLOSED"),
        ("r2", "2026-10-01", "2026-12-31", 1, None, None, None, "CLOSED"),
    ]
    # 不是 600（YAML 不加引号的坑），也不是 10:00:00
    types = "SELECT typeof(open), typeof(valid_from) FROM rules WHERE rule_id = 'r1'"
    assert set(rows(db, types)) == {("text", "text")}


def test_one_row_per_weekday(db):
    got = set(rows(db, "SELECT rule_id, weekday FROM rule_days WHERE poi_id = 'demo-museum'"))
    tue_to_sun = {("r1", day) for day in ["TUE", "WED", "THU", "FRI", "SAT", "SUN"]}
    assert got == tue_to_sun | {("r2", "MON")}


def test_exception_definitions_keep_hours_and_rrule(db):
    got = rows(
        db,
        "SELECT exception_id, reason, closed, open, close, last_entry, rrule "
        "FROM exceptions WHERE poi_id = 'demo-museum' ORDER BY exception_id",
    )
    assert got == [
        ("e1", "临时闭馆", 1, None, None, None, None),
        ("e2", "圣诞", 1, None, None, None, None),
        ("e3", "每月最后一个周一", 1, None, None, None, "FREQ=MONTHLY;BYDAY=-1MO"),
        ("e4", "延长开放", 0, "12:00", "20:00", "19:00", None),
    ]


def test_exception_days_expand_all_three_kinds(db):
    # 单日、区间（首尾都算）、rrule（2026 年 10–12 月的最后一个周一：10-26、11-30、12-28）
    got = rows(
        db,
        "SELECT exception_id, day FROM exception_days WHERE poi_id = 'demo-museum' "
        "ORDER BY day, exception_id",
    )
    assert got == [
        ("e1", "2026-10-20"),
        ("e3", "2026-10-26"),
        ("e4", "2026-11-13"),
        ("e3", "2026-11-30"),
        ("e2", "2026-12-24"),
        ("e2", "2026-12-25"),
        ("e2", "2026-12-26"),
        ("e3", "2026-12-28"),
    ]


def test_rebuild_replaces_the_old_file(tmp_path, make_poi):
    path = tmp_path / "kb.sqlite"
    build_database([make_poi(), make_poi(id="demo-other")], path)
    build_database([make_poi()], path)

    conn = sqlite3.connect(path)
    try:
        assert rows(conn, "SELECT id FROM pois") == [("demo-museum",)]
    finally:
        conn.close()


def test_real_data_builds(tmp_path):
    pois = load_pois(DATA_DIR)
    path = tmp_path / "kb.sqlite"
    build_database(pois, path)

    conn = sqlite3.connect(path)
    try:
        assert rows(conn, "SELECT count(*) FROM pois") == [(len(pois),)]
        assert rows(conn, "SELECT count(*) FROM rules") == [(sum(len(p.rules) for p in pois),)]
    finally:
        conn.close()
