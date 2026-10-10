"""景点数据模型：YAML 里的每个字段都在这里校验，坏数据在加载时就报错，而不是等到查询时才答错。"""

import datetime as dt
import re
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.rrule import rrulestr
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Weekday = Literal["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

# 顺序和 date.weekday() 一致：周一是 0
WEEKDAYS: tuple[Weekday, ...] = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class _Strict(BaseModel):
    # 不认识的字段一律报错：写错字段名宁可加载失败，也不能被静默忽略然后答错
    model_config = ConfigDict(extra="forbid")


class Hours(_Strict):
    """某一天的结论：要么闭馆（closed），要么给出 open / close（可带 last_entry）。

    规则和例外共用这部分字段和校验。
    """

    closed: bool = False
    open: dt.time | None = None
    close: dt.time | None = None
    last_entry: dt.time | None = None
    # 官网只给了部分时段（如渔人堡只给收费时段）时设为 UNKNOWN：时段外答 UNKNOWN 而不是 CLOSED
    outside_hours: Literal["CLOSED", "UNKNOWN"] = "CLOSED"

    @field_validator("open", "close", "last_entry", mode="before")
    @classmethod
    def _parse_hhmm(cls, value: object) -> object:
        # YAML 里不加引号的 10:00 会变成整数 600，pydantic 又会把 600 悄悄当成 00:10。
        # 所以这里只收 "HH:MM" 字符串，其他一律报错
        if value is None:
            return None
        if not isinstance(value, str) or not _HHMM.match(value):
            raise ValueError(f'时间必须写成带引号的 "HH:MM"，收到 {value!r}')
        hour, minute = value.split(":")
        return dt.time(int(hour), int(minute))

    def verdict_key(self) -> tuple:
        """这条规则 / 例外的「结论指纹」：两条指纹相同才算结论一致。不含 id、有效期等元信息。"""
        return (self.closed, self.open, self.close, self.last_entry, self.outside_hours)

    @model_validator(mode="after")
    def _closed_or_full_hours(self) -> Self:
        has_hours = any(t is not None for t in (self.open, self.close, self.last_entry))
        if self.closed:
            if has_hours:
                raise ValueError("closed: true 的条目不能再写时段")
            return self
        if self.open is None or self.close is None:
            raise ValueError("不闭馆的条目必须同时写 open 和 close")
        if self.open >= self.close:
            raise ValueError("open 必须早于 close")
        if self.last_entry is not None and not self.open <= self.last_entry <= self.close:
            raise ValueError("last_entry 必须在 open 和 close 之间")
        return self


class Rule(Hours):
    """基础规则：有效期内，每逢 days 里的星期几，结论如何。"""

    id: str
    valid: tuple[dt.date, dt.date]  # 首尾两天都算在内
    days: list[Weekday] = Field(min_length=1)

    @model_validator(mode="after")
    def _valid_in_order(self) -> Self:
        start, end = self.valid
        if start > end:
            raise ValueError(f"有效期起点 {start} 晚于终点 {end}")
        return self


class DayException(Hours):
    """例外（节假日闭馆、某天改时间），优先于基础规则。三种写法恰好选一种：

    - date：单日
    - dates: [起, 止]：连续几天，首尾都算
    - rrule + valid: [起, 止]：按规律重复（如 FREQ=MONTHLY;BYDAY=-1MO），只在 valid 内生效
    """

    id: str
    reason: str = Field(min_length=1)
    date: dt.date | None = None
    dates: tuple[dt.date, dt.date] | None = None
    rrule: str | None = None
    valid: tuple[dt.date, dt.date] | None = None

    @model_validator(mode="after")
    def _exactly_one_kind(self) -> Self:
        kinds = [k for k in ("date", "dates", "rrule") if getattr(self, k) is not None]
        if len(kinds) != 1:
            raise ValueError(f"例外必须在 date / dates / rrule 里恰好写一个，收到 {kinds}")
        if (self.rrule is None) != (self.valid is None):
            raise ValueError("rrule 必须配 valid 写有效期；没有 rrule 就不能写 valid")
        for name in ("dates", "valid"):
            span = getattr(self, name)
            if span is not None and span[0] > span[1]:
                raise ValueError(f"{name} 起点 {span[0]} 晚于终点 {span[1]}")
        if self.rrule is not None:
            _check_rrule(self.rrule)
        return self

    def covers(self, day: dt.date) -> bool:
        """这条例外管不管 day。引擎和校验都只通过这个方法判断，三种写法不会各走各的逻辑。"""
        if self.date is not None:
            return self.date == day
        if self.dates is not None:
            return self.dates[0] <= day <= self.dates[1]
        return day in self.days()

    def days(self) -> list[dt.date]:
        """这条例外覆盖的全部日期（给校验用；rrule 只展开 valid 之内的）。"""
        if self.date is not None:
            return [self.date]
        if self.dates is not None:
            start, end = self.dates
            return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
        assert self.rrule is not None and self.valid is not None
        start = dt.datetime.combine(self.valid[0], dt.time())
        end = dt.datetime.combine(self.valid[1], dt.time())
        return [d.date() for d in rrulestr(self.rrule, dtstart=start).between(start, end, inc=True)]


def _check_rrule(rule: str) -> None:
    # 只收重复规则本身。dateutil 还接受 "DTSTART:...\nRRULE:..." 这种完整写法，
    # 并会悄悄用里面的 DTSTART 覆盖起点——起止只能写在 valid 里，所以带冒号 / 换行的一律拒收
    if ":" in rule or "\n" in rule:
        raise ValueError(f"rrule 只写重复规则本身（如 FREQ=MONTHLY;BYDAY=-1MO），收到 {rule!r}")
    try:
        rrulestr(rule, dtstart=dt.datetime(2000, 1, 1))
    except (ValueError, TypeError, KeyError) as err:
        raise ValueError(f"rrule 无法解析：{rule!r}（{err}）") from err


class Names(_Strict):
    local: str | None = None
    en: str
    zh: str


class Poi(_Strict):
    id: str
    city: str
    country: str
    tz: str
    category: str
    status: Literal["OPEN", "TEMP_CLOSED", "PERMANENTLY_CLOSED"]  # 营业状态
    review: Literal["draft", "verified"]  # 核验状态
    names: Names
    aliases: list[str] = []
    rules: list[Rule]
    exceptions: list[DayException] = []
    # 没有官方来源的记录（如渔人堡免费区域）两项都写 null；不给默认值，逼 YAML 里显式写出来
    source_url: str | None
    verified_at: dt.date | None

    @field_validator("tz")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as err:
            raise ValueError(f"未知时区 {value!r}") from err
        return value

    @model_validator(mode="after")
    def _ids_unique(self) -> Self:
        # rule_id 是返回给模型的审计线索，同一个景点里规则和例外不能重名
        ids = [r.id for r in self.rules] + [e.id for e in self.exceptions]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"规则 / 例外 id 重复：{duplicates}")
        return self
