"""校验景点数据：uv run python scripts/validate_data.py [目录 …]。有 error 时退出码为 1。

不给目录就校验 data/pois/。核对草稿时连同正式数据一起校验，才查得出跨文件的同名撞车：
    uv run python scripts/validate_data.py data/pois data/drafts
"""

import sys
from pathlib import Path

from travelkb.core.loader import load_pois
from travelkb.core.validate import validate_pois

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "pois"


def main(argv: list[str]) -> int:
    dirs = [Path(d) for d in argv] or [DATA_DIR]
    # 格式错误（如时间没加引号）在加载这一步就会报出文件名
    pois = [poi for d in dirs for poi in load_pois(d)]
    issues = validate_pois(pois)
    for issue in issues:
        print(f"[{issue.level:7}] {issue.code:30} {issue.poi_id or '-':40} {issue.message}")

    counts = {
        level: sum(i.level == level for i in issues) for level in ("error", "warning", "info")
    }
    summary = "，".join(f"{level} {n}" for level, n in counts.items())
    print(f"\n{len(pois)} 个景点：{summary}")
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
