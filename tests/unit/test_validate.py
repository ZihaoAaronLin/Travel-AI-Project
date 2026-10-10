"""数据校验（validate_data 的核心逻辑）：查数据模型逐条校验查不出来的问题。

- error：数据会让引擎答错或答不出依据，必须改
- warning：能用，但还没人核对过
- info：不是错，但值得知道（比如永远答 UNKNOWN 的记录、同名撞车清单）
"""

from datetime import date

import pytest

from travelkb.core.validate import validate_pois

VERIFIED = date(2026, 10, 1)
WINDOW = [date(2026, 10, 1), date(2026, 12, 30)]  # 核验日起 90 天，正好用满


def rule(rule_id, days, valid=WINDOW, **hours):
    return {"id": rule_id, "valid": valid, "days": days, **hours}


OPEN_TUE_TO_SUN = rule(
    "r1", ["TUE", "WED", "THU", "FRI", "SAT", "SUN"], open="10:00", close="18:00"
)
CLOSED_MON = rule("r2", ["MON"], closed=True)


@pytest.fixture
def clean(make_poi):
    """一个挑不出毛病的景点：已核对、有效期正好 90 天、有来源。各测试在此基础上弄坏一处。"""

    def _make(**overrides):
        fields = {
            "review": "verified",
            "rules": [OPEN_TUE_TO_SUN, CLOSED_MON],
            "verified_at": VERIFIED,
        }
        fields.update(overrides)
        return make_poi(**fields)

    return _make


def found(issues, level=None):
    """把问题清单压成 (级别, 代码, poi_id) 方便断言。"""
    return [(i.level, i.code, i.poi_id) for i in issues if level is None or i.level == level]


def test_clean_poi_has_no_issues(clean):
    assert validate_pois([clean()]) == []


def test_draft_is_only_a_warning(clean):
    assert found(validate_pois([clean(review="draft")])) == [
        ("warning", "UNREVIEWED", "demo-museum")
    ]


# ---- 有效期必须落在「核验日起 90 天」之内 ----


@pytest.mark.parametrize(
    "valid",
    [
        [date(2026, 9, 30), date(2026, 12, 30)],  # 早于核验日开始
        [date(2026, 10, 1), date(2026, 12, 31)],  # 超过 90 天
    ],
)
def test_validity_outside_trust_window_is_an_error(clean, valid):
    poi = clean(rules=[rule("r1", ["MON"], valid=valid, closed=True)])

    assert found(validate_pois([poi]), "error") == [
        ("error", "VALIDITY_OUTSIDE_TRUST_WINDOW", "demo-museum")
    ]


@pytest.mark.parametrize("missing", ["source_url", "verified_at"])
def test_rules_without_source_or_verification_date_are_an_error(clean, missing):
    issues = validate_pois([clean(**{missing: None})])

    assert ("error", "MISSING_SOURCE", "demo-museum") in found(issues, "error")


def test_record_without_rules_is_info_not_error(clean):
    # 渔人堡免费区域这类：没有官方来源，故意不写规则，永远答 UNKNOWN
    poi = clean(rules=[], source_url=None, verified_at=None)

    assert found(validate_pois([poi])) == [("info", "NO_RULES", "demo-museum")]


# ---- 例外 ----


def test_exception_outside_every_rule_validity_is_an_error(clean):
    # 引擎第 1 步不会采信有效期外的例外：写了等于白写，必须报出来
    poi = clean(
        exceptions=[{"id": "e1", "date": date(2027, 1, 5), "closed": True, "reason": "闭馆"}]
    )

    assert found(validate_pois([poi]), "error") == [
        ("error", "EXCEPTION_NOT_COVERED", "demo-museum")
    ]


def test_conflicting_exceptions_on_same_date_are_an_error(clean):
    poi = clean(
        exceptions=[
            {"id": "e1", "date": date(2026, 10, 6), "closed": True, "reason": "闭馆"},
            {
                "id": "e2",
                "date": date(2026, 10, 6),
                "open": "12:00",
                "close": "16:00",
                "reason": "改时间",
            },
        ]
    )

    assert found(validate_pois([poi]), "error") == [("error", "EXCEPTION_CONFLICT", "demo-museum")]


# ---- 基础规则冲突：逐日枚举 ----


def test_conflicting_weekly_rules_are_reported_with_the_first_clash(clean):
    october_tuesdays_closed = rule(
        "r3", ["TUE"], valid=[date(2026, 10, 1), date(2026, 10, 31)], closed=True
    )
    poi = clean(rules=[OPEN_TUE_TO_SUN, CLOSED_MON, october_tuesdays_closed])

    issues = validate_pois([poi])

    assert found(issues, "error") == [("error", "RULE_CONFLICT", "demo-museum")]
    message = next(i.message for i in issues if i.code == "RULE_CONFLICT")
    assert "2026-10-06" in message  # 第一个撞车的日子：10 月第一个周二
    assert "r1" in message and "r3" in message


def test_overlapping_rules_with_same_conclusion_are_fine(clean):
    duplicate_tuesday = {**OPEN_TUE_TO_SUN, "id": "r3", "days": ["TUE"]}

    assert validate_pois([clean(rules=[OPEN_TUE_TO_SUN, CLOSED_MON, duplicate_tuesday])]) == []


# ---- 同名撞车清单：每组撞车都应该有对应的金标准 ----


def test_alias_collisions_across_pois_are_listed(clean):
    first = clean(aliases=["示例馆", "Példa"])
    second = clean(
        id="demo-other",
        names={"local": None, "en": "Other", "zh": "另一个馆"},
        aliases=["pelda"],  # 去掉变音符号后和「Példa」相同
    )

    issues = validate_pois([first, second])

    assert found(issues) == [("info", "ALIAS_COLLISION", None)]
    assert "demo-museum" in issues[0].message and "demo-other" in issues[0].message
