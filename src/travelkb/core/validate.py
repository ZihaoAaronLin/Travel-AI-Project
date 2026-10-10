"""数据校验：查数据模型逐条校验查不出来的、跨字段 / 跨条目 / 跨景点的问题。

- error：数据会让引擎答错，或答不出依据，必须改
- warning：能用，但还没人核对过
- info：不是错，但值得知道（永远答 UNKNOWN 的记录、同名撞车清单）
"""

import datetime as dt
from collections import defaultdict
from collections.abc import Iterator, Sequence
from typing import Literal

from pydantic import BaseModel

from travelkb.core.models import WEEKDAYS, Poi, Rule
from travelkb.core.resolve import match_keys

# 数据的信任窗口：核验日起这么多天（ROADMAP 第 7 节「有效期取法」）
TRUST_DAYS = 90


class Issue(BaseModel):
    level: Literal["error", "warning", "info"]
    code: str
    poi_id: str | None  # 跨景点的问题（同名撞车）没有单一的 poi_id
    message: str


def validate_pois(pois: Sequence[Poi]) -> list[Issue]:
    """返回全部问题；没有问题时返回空列表。"""
    issues = [issue for poi in pois for issue in _check_poi(poi)]
    return issues + _alias_collisions(pois)


def _check_poi(poi: Poi) -> list[Issue]:
    issues = []
    if poi.review == "draft":
        issues.append(_issue("warning", "UNREVIEWED", poi, "review: draft，还没人核对过官网"))

    if not poi.rules:
        text = "没有规则：任何日期都会答 UNKNOWN（通常是没有官方来源的部分）"
        issues.append(_issue("info", "NO_RULES", poi, text))
    elif poi.source_url is None or poi.verified_at is None:
        text = "有规则却缺 source_url 或 verified_at：结论没有可追溯的依据"
        issues.append(_issue("error", "MISSING_SOURCE", poi, text))
    else:
        issues += _outside_trust_window(poi, poi.verified_at)

    issues += _uncovered_exceptions(poi)
    issues += _exception_conflicts(poi)
    issues += _rule_conflicts(poi)
    return issues


def _outside_trust_window(poi: Poi, verified_at: dt.date) -> list[Issue]:
    """每条规则的有效期必须落在 [核验日, 核验日 + 90 天] 之内。"""
    limit = verified_at + dt.timedelta(days=TRUST_DAYS)
    return [
        _issue(
            "error",
            "VALIDITY_OUTSIDE_TRUST_WINDOW",
            poi,
            f"{rule.id} 有效期 {rule.valid[0]}~{rule.valid[1]} 超出信任窗口 {verified_at}~{limit}",
        )
        for rule in poi.rules
        if rule.valid[0] < verified_at or rule.valid[1] > limit
    ]


def _uncovered_exceptions(poi: Poi) -> list[Issue]:
    """引擎第 1 步不采信有效期外的例外：例外覆盖的每一天都得落在某条规则的有效期内。

    否则写了等于白写。
    """
    issues = []
    for exc in poi.exceptions:
        uncovered = [day for day in exc.days() if not _covered_by_a_rule(poi, day)]
        if uncovered:
            text = (
                f"{exc.id} 覆盖的 {uncovered[0]} 等 {len(uncovered)} 天"
                "不在任何规则的有效期内，引擎不会采信"
            )
            issues.append(_issue("error", "EXCEPTION_NOT_COVERED", poi, text))
    return issues


def _covered_by_a_rule(poi: Poi, day: dt.date) -> bool:
    return any(rule.valid[0] <= day <= rule.valid[1] for rule in poi.rules)


def _exception_conflicts(poi: Poi) -> list[Issue]:
    """不同写法的例外（单日 / 区间 / rrule）撞在同一天且结论不同。每组冲突只报第一天。"""
    by_date = defaultdict(list)
    for exc in poi.exceptions:
        for day in exc.days():
            by_date[day].append(exc)
    first_clash: dict[tuple[str, ...], dt.date] = {}
    for day, excs in sorted(by_date.items()):
        if len({e.verdict_key() for e in excs}) > 1:
            first_clash.setdefault(tuple(e.id for e in excs), day)
    return [
        _issue(
            "error",
            "EXCEPTION_CONFLICT",
            poi,
            f"{day} 的例外 {'、'.join(ids)} 结论不同，这天会答 UNKNOWN",
        )
        for ids, day in first_clash.items()
    ]


def _rule_conflicts(poi: Poi) -> list[Issue]:
    """逐日枚举有效期：同一天、同一星期命中多条规则且结论不同，就是冲突。每组冲突只报第一天。"""
    first_clash: dict[tuple[str, ...], dt.date] = {}
    for day in _days_spanned(poi.rules):
        weekday = WEEKDAYS[day.weekday()]
        todays = [r for r in poi.rules if r.valid[0] <= day <= r.valid[1] and weekday in r.days]
        if len({r.verdict_key() for r in todays}) > 1:
            first_clash.setdefault(tuple(r.id for r in todays), day)
    return [
        _issue(
            "error",
            "RULE_CONFLICT",
            poi,
            f"规则 {'、'.join(ids)} 从 {day}（{WEEKDAYS[day.weekday()]}）起结论不同，"
            "这些天会答 UNKNOWN",
        )
        for ids, day in first_clash.items()
    ]


def _days_spanned(rules: Sequence[Rule]) -> Iterator[dt.date]:
    """从最早的有效期起点到最晚的终点，逐日列出。"""
    if not rules:
        return
    day = min(rule.valid[0] for rule in rules)
    end = max(rule.valid[1] for rule in rules)
    while day <= end:
        yield day
        day += dt.timedelta(days=1)


def _alias_collisions(pois: Sequence[Poi]) -> list[Issue]:
    """同一个名字指向多个景点：resolve_poi 会返回 AMBIGUOUS。每组都应该有对应的金标准。"""
    owners = defaultdict(set)
    for poi in pois:
        for key in match_keys(poi):
            owners[key].add(poi.id)
    return [
        Issue(
            level="info",
            code="ALIAS_COLLISION",
            poi_id=None,
            message=f"「{key}」同时指向 {', '.join(sorted(ids))}",
        )
        for key, ids in sorted(owners.items())
        if len(ids) > 1
    ]


def _issue(level: Literal["error", "warning", "info"], code: str, poi: Poi, message: str) -> Issue:
    return Issue(level=level, code=code, poi_id=poi.id, message=message)
