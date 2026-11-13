"""YAML → build/travelkb.sqlite：uv run python scripts/build_db.py

只有 query_kb（评测 A2 组）读这个库；窄接口工具照旧直接读 YAML。
先跑数据校验：有 error 就不生成，免得 A2 组查到的是坏数据。
"""

import sys
from pathlib import Path

from travelkb.core.loader import load_pois
from travelkb.core.validate import validate_pois
from travelkb.sql.build import DEFAULT_DB_PATH, build_database

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "pois"


def main() -> int:
    pois = load_pois(DATA_DIR)
    errors = [issue for issue in validate_pois(pois) if issue.level == "error"]
    if errors:
        for issue in errors:
            print(f"[error] {issue.code} {issue.poi_id or '-'} {issue.message}")
        print("数据有 error，没有生成数据库。先跑 scripts/validate_data.py 看详情。")
        return 1

    build_database(pois, DEFAULT_DB_PATH)
    print(f"已生成 {DEFAULT_DB_PATH}：{len(pois)} 个景点")
    return 0


if __name__ == "__main__":
    sys.exit(main())
