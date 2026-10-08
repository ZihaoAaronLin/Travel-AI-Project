"""开放判定，按 docs/ROADMAP.md 第 7 节的第 0–4 步。拿不准一律 UNKNOWN，绝不默认 OPEN。

所有日期、时刻都是景点当地的；日期由调用方传入，这里不调用 now()（铁律 3）。
"""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Literal

from pydantic import BaseModel

from travelkb.core.models import WEEKDAYS, DayException, Hours, Poi, Rule

Status = Literal["OPEN", "CLOSED", "UNKNOWN"]
ReasonCode = Literal[
    "PERMANENTLY_CLOSED",
    "TEMP_CLOSED",
    "NOT_COVERED",
    "EXCEPTION",
    "WEEKLY_RULE",
    "NO_RULE_FOR_WEEKDAY",
    "CONFLICT",
    "BEFORE_OPENING",
    "AFTER_LAST_ENTRY",
    "AFTER_CLOSING",
    "OUTSIDE_KNOWN_HOURS",
]

_WEEKDAY_ZH = dict(
    zip(WEEKDAYS, ["周一", "周二", "周三", "周四", "周五", "周六", "周日"], strict=True)
)


class OpenResult(BaseModel):
    """返回给模型的结论。reason_code 给程序判分用，reason 是给模型看的一句话。"""

    poi_id: str
    date: dt.date
    weekday: str  # 代码算出的星期几：模型常把星期几算错
    at: dt.time | None
    status: Status
    reason_code: ReasonCode
    reason: str
    rule_ids: list[str]  # 结论依据的规则 / 例外 id；营业状态导致的结论记为 "status"
    open: dt.time | None
    close: dt.time | None
    last_entry: dt.time | None
    source_url: str | None
    verified_at: dt.date | None


@dataclass(frozen=True)
class _Verdict:
    """判定过程中的中间结论，最后再拼上景点的来源信息变成 OpenResult。"""

    status: Status
    reason_code: ReasonCode
    reason: str
    rule_ids: list[str] = field(default_factory=list)
    hours: Hours | None = None  # 只有结论是 OPEN（或按时刻判出的 CLOSED / UNKNOWN）时才带时段


def is_open(poi: Poi, day: dt.date, at: dt.time | None = None) -> OpenResult:
    """判断 poi 在当地日期 day 开不开；给了当地时刻 at，就判断那一刻能不能入场。"""
    verdict = _day_verdict(poi, day)
    if at is not None and verdict.status == "OPEN":
        verdict = _entry_at(verdict, at)

    hours = verdict.hours
    return OpenResult(
        poi_id=poi.id,
        date=day,
        weekday=WEEKDAYS[day.weekday()],
        at=at,
        status=verdict.status,
        reason_code=verdict.reason_code,
        reason=verdict.reason,
        rule_ids=verdict.rule_ids,
        open=hours.open if hours else None,
        close=hours.close if hours else None,
        last_entry=hours.last_entry if hours else None,
        source_url=poi.source_url,
        verified_at=poi.verified_at,
    )


def _day_verdict(poi: Poi, day: dt.date) -> _Verdict:
    """第 0–3 步：只看日期，得出当天的结论。"""
    # 第 0 步：营业状态。永久停业不受日期影响；暂时关闭没写恢复日期，不敢下结论
    if poi.status == "PERMANENTLY_CLOSED":
        return _Verdict("CLOSED", "PERMANENTLY_CLOSED", "已永久停业", ["status"])
    if poi.status == "TEMP_CLOSED":
        return _Verdict("UNKNOWN", "TEMP_CLOSED", "暂时关闭，官方没写哪天恢复", ["status"])

    # 第 1 步：有效期是对整份数据的信任窗口，窗口外（包括窗口外的例外）一律不下结论
    in_force = [rule for rule in poi.rules if rule.valid[0] <= day <= rule.valid[1]]
    if not in_force:
        reason = "数据没有覆盖这一天（超出有效期或没有官方来源），请以官网为准"
        return _Verdict("UNKNOWN", "NOT_COVERED", reason)

    # 第 2 步：单日例外优先于基础规则
    exceptions = [exc for exc in poi.exceptions if exc.date == day]
    if exceptions:
        return _combine(exceptions, "EXCEPTION")

    # 第 3 步：当天星期对应的基础规则。没写的星期既不当闭馆、也不当开放
    weekday = WEEKDAYS[day.weekday()]
    todays = [rule for rule in in_force if weekday in rule.days]
    if not todays:
        reason = f"官方来源没写{_WEEKDAY_ZH[weekday]}开不开"
        return _Verdict("UNKNOWN", "NO_RULE_FOR_WEEKDAY", reason)
    return _combine(todays, "WEEKLY_RULE")


def _combine(entries: Sequence[Rule | DayException], code: ReasonCode) -> _Verdict:
    """同一天命中多条规则（或多条例外）：结论一致就采用，不一致说明数据自相矛盾，只能答 UNKNOWN。"""
    ids = [entry.id for entry in entries]
    if len({_conclusion(entry) for entry in entries}) > 1:
        return _Verdict("UNKNOWN", "CONFLICT", f"数据自相矛盾：{'、'.join(ids)} 的结论不同", ids)

    first = entries[0]
    note = f"{first.reason}：" if isinstance(first, DayException) else ""
    if first.closed:
        return _Verdict("CLOSED", code, f"{note}当天闭馆", ids)
    return _Verdict("OPEN", code, f"{note}当天开放 {_hours_text(first)}", ids, hours=first)


def _conclusion(entry: Hours) -> tuple:
    """用来比较两条规则结论是否相同的「指纹」，不含 id、有效期等元信息。"""
    return (entry.closed, entry.open, entry.close, entry.last_entry, entry.outside_hours)


def _entry_at(verdict: _Verdict, at: dt.time) -> _Verdict:
    """第 4 步：当天开放时，判断时刻 at 能不能入场。"""
    hours = verdict.hours
    assert hours is not None and hours.open is not None and hours.close is not None

    # 能入场的区间：有 last_entry 时是 [open, last_entry]（含当刻）；没有时是 [open, close)
    if at < hours.open:
        code, text = "BEFORE_OPENING", f"{at:%H:%M} 还没开门，{hours.open:%H:%M} 开门"
    elif hours.last_entry is not None and at > hours.last_entry:
        code, text = "AFTER_LAST_ENTRY", f"{at:%H:%M} 已过最后入场时间 {hours.last_entry:%H:%M}"
    elif hours.last_entry is None and at >= hours.close:
        code, text = "AFTER_CLOSING", f"{at:%H:%M} 已经关门（{hours.close:%H:%M} 关门）"
    else:
        return verdict

    # 官网只给了部分时段时，时段外到底能不能进没有依据，不能答 CLOSED
    if hours.outside_hours == "UNKNOWN":
        text = f"官方只写了 {_hours_text(hours)} 这段时间，{at:%H:%M} 能不能进没写"
        return replace(verdict, status="UNKNOWN", reason_code="OUTSIDE_KNOWN_HOURS", reason=text)
    return replace(verdict, status="CLOSED", reason_code=code, reason=text)


def _hours_text(hours: Hours) -> str:
    text = f"{hours.open:%H:%M}–{hours.close:%H:%M}"
    if hours.last_entry is not None:
        text += f"，最后入场 {hours.last_entry:%H:%M}"
    return text
