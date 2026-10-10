"""跑 tests/golden/cases.yaml 里的金标准：真实数据 + 真实问题，答案由 Aaron 回官网独立核对。

expect 里写了哪些字段就比较哪些，没写的不比较。expect 为 null 的题跳过，等 Aaron 填写。
"""

import datetime as dt
from pathlib import Path

import pytest
import yaml

from travelkb.core.hours import is_open
from travelkb.core.loader import load_pois
from travelkb.core.resolve import resolve_poi

ROOT = Path(__file__).resolve().parents[2]
CASES = yaml.safe_load((Path(__file__).parent / "cases.yaml").read_text(encoding="utf-8"))
POIS = load_pois(ROOT / "data" / "pois")


def run_call(call: dict) -> dict:
    """执行一条用例的调用，把结果整理成和 expect 同样的写法（时刻 "HH:MM"，候选只留 id）。"""
    args = call["args"]
    if call["tool"] == "resolve_poi":
        result = resolve_poi(args["query"], POIS, city=args.get("city"))
        return {"status": result.status, "candidates": [c.poi_id for c in result.candidates]}

    poi = next(p for p in POIS if p.id == args["poi_id"])
    at = dt.time.fromisoformat(args["time"]) if "time" in args else None
    result = is_open(poi, args["date"], at)
    actual = result.model_dump()
    for key in ("open", "close", "last_entry"):
        actual[key] = actual[key].strftime("%H:%M") if actual[key] else None
    return actual


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_golden_case(case):
    if case["expect"] is None:
        pytest.skip(f"{case['id']}：待 Aaron 回官网核对后填写 expect")
    assert isinstance(case["expect"], dict), (
        f"{case['id']}：expect 要写成字段，例如 {{status: CLOSED, weekday: MON}}；"
        "判断理由写在 note 里"
    )
    assert case["source_url"] and case["checked_at"], "填了 expect 就要写 source_url 和 checked_at"

    actual = run_call(case["call"])

    mismatches = {
        key: {"expect": want, "actual": actual.get(key)}
        for key, want in case["expect"].items()
        if actual.get(key) != want
    }
    assert not mismatches, f"{case['id']} {case['question']}\n{mismatches}"
