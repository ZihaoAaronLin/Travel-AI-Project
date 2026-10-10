"""travelkb 的 MCP 薄适配层：只把 core/ 的逻辑包装成 MCP 工具，本身不放业务逻辑。

这一层只做四件事：解析参数、把错误翻译成模型能读懂的 ToolError、
不给日期时按景点时区算「今天」、把结果整理成给模型看的写法（日期 YYYY-MM-DD、时刻 HH:MM）。

Claude Desktop 以 stdio 方式把本进程起成子进程：stdout 是 JSON-RPC 数据通道，
任何 print() 都会把协议帧写坏。日志一律走 stderr——MCPServer 构造时已把 root logger
配成写 stderr 的 RichHandler，这里不再重复配置。
"""

import datetime as dt
import logging
import re
from collections.abc import Callable, Sequence
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from travelkb.core.hours import Caveat, OpenResult
from travelkb.core.hours import is_open as judge_opening
from travelkb.core.loader import load_pois
from travelkb.core.models import Poi
from travelkb.core.resolve import ResolveResult
from travelkb.core.resolve import resolve_poi as resolve_name

logger = logging.getLogger(__name__)

# 版本号只在 pyproject.toml 维护一处，这里读已安装包的元数据
SERVER_VERSION = version("travel-kb")

# src/travelkb/server.py → 往上两级是项目根目录
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "pois"

READ_ONLY = ToolAnnotations(read_only_hint=True)

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# 返回「现在」的函数，必须带时区。只有 server 层取「现在」（铁律 3），测试里注入固定时刻
Clock = Callable[[], dt.datetime]


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class PingResult(BaseModel):
    ok: bool = Field(description="server 正常响应时为 true")
    server_version: str = Field(description="travel-kb 包的版本号")


class IsOpenOutput(BaseModel):
    """is_open 返回给模型的结论。字段含义见 core.hours.OpenResult，这里只换成文本写法。"""

    poi_id: str
    date: str = Field(description="判定用的景点当地日期，YYYY-MM-DD")
    date_source: Literal["caller", "poi_local_today"] = Field(
        description="caller：调用方给的日期；poi_local_today：没给日期，用了景点当地的今天"
    )
    weekday: str = Field(description="代码算出的星期几（MON…SUN），以它为准")
    time: str | None = Field(description="判定的当地时刻 HH:MM；没给时刻则为 null，表示判断整天")
    status: Literal["OPEN", "CLOSED", "UNKNOWN"]
    reason_code: str
    reason: str
    rule_ids: list[str]
    open: str | None
    close: str | None
    last_entry: str | None
    source_url: str | None
    verified_at: str | None
    next_open_date: str | None = Field(
        description="去不了时，下一个确定能去的日子 YYYY-MM-DD；可以据此建议改天"
    )
    warnings: list[Caveat] = Field(description="结论之外的提醒，要转达给用户（如数据可能过期）")


def build_server(pois: Sequence[Poi], clock: Clock = utc_now) -> MCPServer:
    """用给定的景点数据和时钟组装 server。测试传假数据和固定时钟，正式运行传 data/pois/。"""
    pois = list(pois)
    by_id = {poi.id: poi for poi in pois}
    mcp = MCPServer("travelkb")

    @mcp.tool(annotations=READ_ONLY)
    def ping() -> PingResult:
        """连通性检查：确认 travelkb server 已启动并能响应。不读取任何数据。"""
        return PingResult(ok=True, server_version=SERVER_VERSION)

    @mcp.tool(annotations=READ_ONLY)
    def resolve_poi(
        query: Annotated[str, Field(description="用户说的景点名，中文、英文、当地语言都可以")],
        city: Annotated[
            str | None, Field(description="城市英文名，如 Budapest；不确定就不填")
        ] = None,
    ) -> ResolveResult:
        """把用户说的景点名对应到 poi_id。查任何景点开不开之前，先调这个工具。

        返回的 status：
        - MATCH：唯一确定，用 candidates[0].poi_id 去调 is_open。
        - AMBIGUOUS：有多个同名景点。不要自己挑，把 candidates 列给用户，问清楚是哪一个。
        - NOT_FOUND：知识库里没有。如实告诉用户「未收录，无法核验」，不要凭印象回答开放时间。

        只做精确匹配（不分大小写、忽略变音符号），不做模糊匹配；
        可以换个叫法（中文名 / 英文名 / 当地名）再试。
        """
        try:
            result = resolve_name(query, pois, city=city)
        except ValueError as err:
            raise ToolError(f"query 不能为空：{err}") from err
        logger.info("resolve_poi %r city=%r -> %s", query, city, result.status)
        return result

    @mcp.tool(annotations=READ_ONLY)
    def is_open(
        poi_id: Annotated[str, Field(description="resolve_poi 返回的 poi_id，不是景点名")],
        date: Annotated[
            str | None, Field(description="景点当地日期 YYYY-MM-DD；不填就用景点当地的今天")
        ] = None,
        time: Annotated[
            str | None, Field(description="景点当地时刻 HH:MM；填了就判断那一刻能不能入场")
        ] = None,
    ) -> IsOpenOutput:
        """核验某个景点某天（可选某个时刻）开不开。poi_id 必须来自 resolve_poi。

        返回的 status：
        - OPEN：可以去；open / close / last_entry 是当天的时段。
        - CLOSED：不能去；reason 说明原因（闭馆日、节假日例外、还没开门、过了最后入场）。
        - UNKNOWN：数据无法确定（超出核验有效期、官网没写、数据自相矛盾）。必须告诉用户「无法核验，
          请以官网为准」并给出 source_url，绝不能当成开放。

        weekday 是代码算出的星期几，以它为准。回答时带上 source_url 和 verified_at。
        本工具不含实时信息（罢工、临时闭馆以官网当天公告为准）。
        """
        poi = by_id.get(poi_id)
        if poi is None:
            raise ToolError(
                f"未知 poi_id {poi_id!r}：先调 resolve_poi 拿到 poi_id，不要直接传景点名"
            )

        # 「今天」只在这里取一次：不给日期时拿它当判定日期，另外用它判断数据有没有过期（铁律 3）
        today = _local_today(poi, clock)
        if date is None:
            day, date_source = today, "poi_local_today"
        else:
            day, date_source = _parse_date(date), "caller"
        at = None if time is None else _parse_time(time)

        result = judge_opening(poi, day, at, as_of=today)
        logger.info("is_open %s %s %s -> %s", poi_id, day, time, result.status)
        return _to_output(result, date_source)

    return mcp


def _local_today(poi: Poi, clock: Clock) -> dt.date:
    """景点当地的今天：同一时刻，布达佩斯可能已经是明天，纽约还是今天。"""
    return clock().astimezone(ZoneInfo(poi.tz)).date()


def _parse_date(value: str) -> dt.date:
    # 先用正则卡住写法：fromisoformat 还接受 20261006、2026-W41-2 等写法，这里只认 YYYY-MM-DD
    try:
        if not _DATE.match(value):
            raise ValueError
        return dt.date.fromisoformat(value)
    except ValueError:
        raise ToolError(f"date 要写成 YYYY-MM-DD（景点当地日期），收到 {value!r}") from None


def _parse_time(value: str) -> dt.time:
    if not _TIME.match(value):
        raise ToolError(f"time 要写成 HH:MM（24 小时制、景点当地时间），收到 {value!r}")
    hour, minute = value.split(":")
    return dt.time(int(hour), int(minute))


def _to_output(result: OpenResult, date_source: str) -> IsOpenOutput:
    def hhmm(value: dt.time | None) -> str | None:
        return value.strftime("%H:%M") if value else None

    return IsOpenOutput(
        poi_id=result.poi_id,
        date=result.date.isoformat(),
        date_source=date_source,
        weekday=result.weekday,
        time=hhmm(result.at),
        status=result.status,
        reason_code=result.reason_code,
        reason=result.reason,
        rule_ids=result.rule_ids,
        open=hhmm(result.open),
        close=hhmm(result.close),
        last_entry=hhmm(result.last_entry),
        source_url=result.source_url,
        verified_at=result.verified_at.isoformat() if result.verified_at else None,
        next_open_date=result.next_open_date.isoformat() if result.next_open_date else None,
        warnings=result.warnings,
    )


# Claude Desktop 启动的就是这个 server：启动时读一次 data/pois/，数据有错就直接启动失败
mcp = build_server(load_pois(DATA_DIR))


def main() -> None:
    """脚本入口（pyproject 里的 travelkb-server）。"""
    logger.info("travelkb %s starting on stdio", SERVER_VERSION)
    mcp.run()  # 默认 transport="stdio"


if __name__ == "__main__":
    main()
