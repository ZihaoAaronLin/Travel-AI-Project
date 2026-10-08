"""unit 测试的假数据。景点、时间、网址全是编的，和 data/ 里的真实数据无关。

日期速查（2026 年）：10-05 周一，10-06 周二，10-09 周五，10-11 周日。
假博物馆的规则有效期是 2026-10-01 ~ 2026-12-31。
"""

from datetime import date

import pytest

from travelkb.core.models import Poi

TUE_TO_SUN = ["TUE", "WED", "THU", "FRI", "SAT", "SUN"]
VALID = [date(2026, 10, 1), date(2026, 12, 31)]


def base_poi_dict() -> dict:
    """一个周二到周日 10–18 点开（17 点最后入场）、周一闭馆的假博物馆。"""
    return {
        "id": "demo-museum",
        "city": "Budapest",
        "country": "HU",
        "tz": "Europe/Budapest",
        "category": "museum",
        "status": "OPEN",
        "review": "draft",
        "names": {"local": "Példa Múzeum", "en": "Demo Museum", "zh": "示例博物馆"},
        "aliases": ["示例馆"],
        "rules": [
            {
                "id": "r1",
                "valid": VALID,
                "days": TUE_TO_SUN,
                "open": "10:00",
                "close": "18:00",
                "last_entry": "17:00",
            },
            {"id": "r2", "valid": VALID, "days": ["MON"], "closed": True},
        ],
        "exceptions": [],
        "source_url": "https://example.org/demo-museum/hours",
        "verified_at": date(2026, 10, 1),
    }


@pytest.fixture
def poi_dict() -> dict:
    """原始字典，给「坏数据应该被拒绝」的测试改着用。"""
    return base_poi_dict()


@pytest.fixture
def make_poi():
    """在假博物馆的基础上覆盖若干顶层字段，返回校验过的 Poi。"""

    def _make(**overrides) -> Poi:
        data = base_poi_dict()
        data.update(overrides)
        return Poi.model_validate(data)

    return _make
