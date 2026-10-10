"""行程核验：check_day_plan 逐站核验一天的行程并列出问题；find_open_pois 找当天开放的替代景点。

问题清单的设计目标是「能逐条解决」：每条带编号、站点、机器可读的 fix、带具体数值的 suggestion，
模型照着改完再调一次，直到没有 BLOCKER / UNKNOWN。不算路上时间，但两站之间至少留 10 分钟缓冲。
所有日期、时刻都是景点当地的；日期由调用方传入（铁律 3）。
"""

import datetime as dt
from collections.abc import Sequence
from typing import Literal, Self

from pydantic import BaseModel, model_validator

from travelkb.core.hours import OpenResult, ReasonCode, Status, is_open
from travelkb.core.models import WEEKDAYS, Poi
from travelkb.core.resolve import normalize

# Aaron 2026-10-10 定：不算路上时间，但两站之间至少留这么久
TRANSFER_BUFFER = dt.timedelta(minutes=10)

Severity = Literal["BLOCKER", "WARNING", "UNKNOWN"]
IssueCode = Literal[
    "CLOSED_DAY",
    "AFTER_LAST_ENTRY",
    "OVERLAP",
    "TIGHT_TRANSFER",
    "BEFORE_OPENING",
    "LEAVE_AFTER_CLOSE",
    "UNVERIFIED",
]
Fix = Literal["CHANGE_DATE", "ARRIVE_EARLIER", "ARRIVE_LATER", "LEAVE_EARLIER", "CHECK_OFFICIAL"]

# 这些 reason_code 说明「整天都去不了」，而不是「这个时刻去不了」
_DAY_CLOSED_CODES = {"EXCEPTION", "WEEKLY_RULE", "PERMANENTLY_CLOSED"}


class Stop(BaseModel):
    poi_id: str
    arrive: dt.time
    leave: dt.time | None = None

    @model_validator(mode="after")
    def _leave_after_arrive(self) -> Self:
        if self.leave is not None and self.leave <= self.arrive:
            raise ValueError(
                f"{self.poi_id}：离开时刻 {self.leave:%H:%M} 必须晚于到达 {self.arrive:%H:%M}"
            )
        return self


class PlanIssue(BaseModel):
    id: str  # I1、I2…按站点顺序编号
    severity: Severity
    code: IssueCode
    stop_index: int
    related_stop_index: int | None = None  # 重叠 / 衔接太紧时指向上一站
    fix: Fix
    suggestion: str  # 给模型看的一句话，含具体数值


class StopVerdict(BaseModel):
    index: int
    poi_id: str
    name_zh: str
    arrive: dt.time
    leave: dt.time | None
    status: Status
    reason_code: ReasonCode
    reason: str
    open: dt.time | None
    close: dt.time | None
    last_entry: dt.time | None
    next_open_date: dt.date | None
    source_url: str | None
    verified_at: dt.date | None


class PlanWarning(BaseModel):
    poi_id: str
    code: Literal["STALE"]
    message: str


class DayPlanReport(BaseModel):
    date: dt.date
    weekday: str
    ok: bool  # 没有 BLOCKER 也没有 UNKNOWN；WARNING 不影响通过
    stops: list[StopVerdict]
    issues: list[PlanIssue]
    counts: dict[str, int]
    warnings: list[PlanWarning]


def check_day_plan(
    pois: Sequence[Poi], day: dt.date, stops: Sequence[Stop], as_of: dt.date | None = None
) -> DayPlanReport:
    """逐站核验当地日期 day 的行程。stops 按到达顺序给。"""
    if not stops:
        raise ValueError("行程至少要有一站")
    by_id = {poi.id: poi for poi in pois}

    verdicts, issues, warnings = [], [], {}
    for index, stop in enumerate(stops):
        poi = by_id.get(stop.poi_id)
        if poi is None:
            raise ValueError(f"未知 poi_id {stop.poi_id!r}，先用 resolve_poi 消歧")
        result = is_open(poi, day, stop.arrive, as_of=as_of)
        verdicts.append(_verdict(index, poi, stop, result))
        issues += _stop_issues(index, stop, result)
        if index > 0:
            issues += _transfer_issues(index, stops[index - 1], stop, day)
        for caveat in result.warnings:
            warnings.setdefault(
                poi.id, PlanWarning(poi_id=poi.id, code=caveat.code, message=caveat.message)
            )

    for number, issue in enumerate(issues, start=1):
        issue.id = f"I{number}"
    counts = {
        level: sum(i.severity == level for i in issues)
        for level in ("BLOCKER", "WARNING", "UNKNOWN")
    }
    return DayPlanReport(
        date=day,
        weekday=WEEKDAYS[day.weekday()],
        ok=counts["BLOCKER"] == 0 and counts["UNKNOWN"] == 0,
        stops=verdicts,
        issues=issues,
        counts=counts,
        warnings=list(warnings.values()),
    )


def _verdict(index: int, poi: Poi, stop: Stop, result: OpenResult) -> StopVerdict:
    return StopVerdict(
        index=index,
        poi_id=poi.id,
        name_zh=poi.names.zh,
        arrive=stop.arrive,
        leave=stop.leave,
        status=result.status,
        reason_code=result.reason_code,
        reason=result.reason,
        open=result.open,
        close=result.close,
        last_entry=result.last_entry,
        next_open_date=result.next_open_date,
        source_url=result.source_url,
        verified_at=result.verified_at,
    )


def _stop_issues(index: int, stop: Stop, result: OpenResult) -> list[PlanIssue]:
    """这一站自己的问题：整天去不了 / 查不到 / 这个时刻进不去 / 待到关门之后。"""
    issue = lambda **kw: PlanIssue(id="", stop_index=index, **kw)  # noqa: E731 — id 最后统一编号

    if result.status == "UNKNOWN":
        where = f" {result.source_url}" if result.source_url else ""
        text = f"无法核验：{result.reason}。请看官网确认{where}"
        return [issue(severity="UNKNOWN", code="UNVERIFIED", fix="CHECK_OFFICIAL", suggestion=text)]

    # 结论是 OPEN 时 reason_code 也是 WEEKLY_RULE / EXCEPTION（说明依据），所以必须先看 status
    if result.status == "CLOSED" and result.reason_code in _DAY_CLOSED_CODES:
        change = f"改到 {result.next_open_date}，或" if result.next_open_date else ""
        text = f"当天去不了：{result.reason}。{change}用 find_open_pois 换一个当天开放的景点"
        return [issue(severity="BLOCKER", code="CLOSED_DAY", fix="CHANGE_DATE", suggestion=text)]

    if result.reason_code == "BEFORE_OPENING":
        wait = _minutes_between(stop.arrive, result.open)
        text = (
            f"{result.open:%H:%M} 才开门，{stop.arrive:%H:%M} 到要等 {wait} 分钟；"
            f"建议 {result.open:%H:%M} 后到达"
        )
        return [
            issue(severity="WARNING", code="BEFORE_OPENING", fix="ARRIVE_LATER", suggestion=text)
        ]

    if result.reason_code in ("AFTER_LAST_ENTRY", "AFTER_CLOSING"):
        deadline = result.last_entry or result.close
        label = "最后入场" if result.last_entry else "关门"
        change = f"，或改天（{result.next_open_date}）" if result.next_open_date else ""
        text = (
            f"{label} {deadline:%H:%M}，{stop.arrive:%H:%M} 到已进不去；"
            f"改到 {deadline:%H:%M} 之前到达{change}"
        )
        return [
            issue(
                severity="BLOCKER", code="AFTER_LAST_ENTRY", fix="ARRIVE_EARLIER", suggestion=text
            )
        ]

    # 能进。再看待到什么时候：关门之后还没走就会被清场
    if stop.leave is not None and result.close is not None and stop.leave > result.close:
        text = (
            f"{result.close:%H:%M} 关门，{stop.leave:%H:%M} 离开会被清场；"
            f"建议 {result.close:%H:%M} 前离开"
        )
        return [
            issue(
                severity="WARNING", code="LEAVE_AFTER_CLOSE", fix="LEAVE_EARLIER", suggestion=text
            )
        ]
    return []


def _transfer_issues(index: int, previous: Stop, stop: Stop, day: dt.date) -> list[PlanIssue]:
    """和上一站的衔接：到达早于上一站离开是重叠；没重叠但不到 10 分钟是太紧。不算路上时间。"""
    prev_end = previous.leave or previous.arrive  # 没写离开时刻就按到达算
    earliest = (dt.datetime.combine(day, prev_end) + TRANSFER_BUFFER).time()
    common = {"stop_index": index, "related_stop_index": index - 1, "fix": "ARRIVE_LATER"}

    if stop.arrive < prev_end:
        text = (
            f"上一站（第 {index} 站）{prev_end:%H:%M} 才离开，{stop.arrive:%H:%M} 到不了；"
            f"建议 {earliest:%H:%M} 后到达（含 10 分钟缓冲，不含路上时间）"
        )
        return [PlanIssue(id="", severity="BLOCKER", code="OVERLAP", suggestion=text, **common)]
    if stop.arrive < earliest:
        gap = _minutes_between(prev_end, stop.arrive)
        text = (
            f"上一站 {prev_end:%H:%M} 离开、{stop.arrive:%H:%M} 到，只留了 {gap} 分钟；"
            f"建议至少留 10 分钟缓冲，{earliest:%H:%M} 后到达（不含路上时间）"
        )
        return [
            PlanIssue(id="", severity="WARNING", code="TIGHT_TRANSFER", suggestion=text, **common)
        ]
    return []


def _minutes_between(start: dt.time, end: dt.time) -> int:
    today = dt.date(2000, 1, 1)  # 只是为了做减法，日期无所谓
    return int(
        (dt.datetime.combine(today, end) - dt.datetime.combine(today, start)).total_seconds() // 60
    )


# ---- find_open_pois ----


class OpenHit(BaseModel):
    poi_id: str
    name_zh: str
    name_en: str
    category: str
    open: dt.time | None
    close: dt.time | None
    last_entry: dt.time | None
    source_url: str | None
    verified_at: dt.date | None


class FindOpenResult(BaseModel):
    date: dt.date
    weekday: str
    open: list[OpenHit]  # 只列结论是 OPEN 的，按 poi_id 排序
    unverified: list[str]  # 说不准的：不是没有，是没法核验


def find_open_pois(
    pois: Sequence[Poi],
    city: str,
    day: dt.date,
    at: dt.time | None = None,
    category: str | None = None,
) -> FindOpenResult:
    """某城某天（某时）确定能去的景点。给了 at 就要求那一刻能入场。"""
    if not city.strip():
        raise ValueError("city 不能为空")
    candidates = [
        poi
        for poi in sorted(pois, key=lambda p: p.id)
        if normalize(poi.city) == normalize(city)
        and (category is None or normalize(poi.category) == normalize(category))
    ]

    hits, unverified = [], []
    for poi in candidates:
        result = is_open(poi, day, at)
        if result.status == "OPEN":
            hits.append(_hit(poi, result))
        elif result.status == "UNKNOWN":
            unverified.append(poi.id)
    return FindOpenResult(
        date=day, weekday=WEEKDAYS[day.weekday()], open=hits, unverified=unverified
    )


def _hit(poi: Poi, result: OpenResult) -> OpenHit:
    return OpenHit(
        poi_id=poi.id,
        name_zh=poi.names.zh,
        name_en=poi.names.en,
        category=poi.category,
        open=result.open,
        close=result.close,
        last_entry=result.last_entry,
        source_url=result.source_url,
        verified_at=result.verified_at,
    )
