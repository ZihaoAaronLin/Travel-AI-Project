"""把景点写成 SQLite 事实表（scripts/build_db.py 调用）。只有 query_kb 读它；窄接口工具照旧读 YAML。

日期存 YYYY-MM-DD、时刻存 HH:MM 文本：字符串比较就是先后，模型写 SQL 不用做类型转换。
例外的三种写法（单日 / 区间 / rrule）都展开进 exception_days，用的是引擎自己的 DayException.days()，
所以 SQL 里看到的例外日期和 is_open 判定时用的一定是同一批。
"""

import sqlite3
from collections.abc import Sequence
from pathlib import Path

from travelkb.core.models import Hours, Poi

# src/travelkb/sql/build.py → 往上三级是项目根目录；build/ 不进 git
DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "build" / "travelkb.sqlite"

SCHEMA = """
CREATE TABLE pois (
    id TEXT PRIMARY KEY, city TEXT NOT NULL, country TEXT NOT NULL, tz TEXT NOT NULL,
    category TEXT NOT NULL, status TEXT NOT NULL, review TEXT NOT NULL,
    name_local TEXT, name_en TEXT NOT NULL, name_zh TEXT NOT NULL,
    source_url TEXT, verified_at TEXT
);
CREATE TABLE aliases (
    poi_id TEXT NOT NULL REFERENCES pois(id), alias TEXT NOT NULL
);
CREATE TABLE rules (
    poi_id TEXT NOT NULL REFERENCES pois(id), rule_id TEXT NOT NULL,
    valid_from TEXT NOT NULL, valid_to TEXT NOT NULL,
    closed INTEGER NOT NULL, open TEXT, close TEXT, last_entry TEXT, outside_hours TEXT NOT NULL,
    PRIMARY KEY (poi_id, rule_id)
);
CREATE TABLE rule_days (
    poi_id TEXT NOT NULL, rule_id TEXT NOT NULL, weekday TEXT NOT NULL,
    PRIMARY KEY (poi_id, rule_id, weekday)
);
CREATE TABLE exceptions (
    poi_id TEXT NOT NULL REFERENCES pois(id), exception_id TEXT NOT NULL, reason TEXT NOT NULL,
    closed INTEGER NOT NULL, open TEXT, close TEXT, last_entry TEXT, outside_hours TEXT NOT NULL,
    rrule TEXT,
    PRIMARY KEY (poi_id, exception_id)
);
CREATE TABLE exception_days (
    poi_id TEXT NOT NULL, exception_id TEXT NOT NULL, day TEXT NOT NULL,
    PRIMARY KEY (poi_id, exception_id, day)
);
"""


def build_database(pois: Sequence[Poi], path: Path) -> None:
    """写到临时文件再整个替换：正在读旧库的人不会读到写了一半的库。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)

    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(SCHEMA)
        for poi in pois:
            _insert_poi(conn, poi)
        conn.commit()
    finally:
        conn.close()
    tmp.replace(path)


def _insert_poi(conn: sqlite3.Connection, poi: Poi) -> None:
    conn.execute(
        "INSERT INTO pois VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            poi.id, poi.city, poi.country, poi.tz, poi.category, poi.status, poi.review,
            poi.names.local, poi.names.en, poi.names.zh, poi.source_url, _iso(poi.verified_at),
        ),
    )  # fmt: skip
    conn.executemany("INSERT INTO aliases VALUES (?, ?)", [(poi.id, a) for a in poi.aliases])

    for rule in poi.rules:
        conn.execute(
            "INSERT INTO rules VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (poi.id, rule.id, _iso(rule.valid[0]), _iso(rule.valid[1]), *_hours(rule)),
        )
        conn.executemany(
            "INSERT INTO rule_days VALUES (?, ?, ?)", [(poi.id, rule.id, d) for d in rule.days]
        )

    for exc in poi.exceptions:
        conn.execute(
            "INSERT INTO exceptions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (poi.id, exc.id, exc.reason, *_hours(exc), exc.rrule),
        )
        conn.executemany(
            "INSERT INTO exception_days VALUES (?, ?, ?)",
            [(poi.id, exc.id, _iso(day)) for day in exc.days()],
        )


def _hours(h: Hours) -> tuple:
    """(closed, open, close, last_entry, outside_hours)，和表里的列顺序一致。"""
    return (int(h.closed), _hhmm(h.open), _hhmm(h.close), _hhmm(h.last_entry), h.outside_hours)


def _iso(value) -> str | None:
    return None if value is None else value.isoformat()


def _hhmm(value) -> str | None:
    return None if value is None else value.strftime("%H:%M")
