"""同名消歧：名字或别名精确匹配，不做模糊匹配；多个候选就全部列出，交给用户选，绝不自动挑一个。"""

import unicodedata
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel

from travelkb.core.models import Poi


class Candidate(BaseModel):
    """一个候选景点。字段够前端直接渲染成一个选项。"""

    poi_id: str
    name_zh: str
    name_en: str
    name_local: str | None
    city: str
    category: str


class ResolveResult(BaseModel):
    status: Literal["MATCH", "AMBIGUOUS", "NOT_FOUND"]
    query: str
    city: str | None
    candidates: list[Candidate]  # 按 poi_id 排序，顺序不代表优先级


def normalize(text: str) -> str:
    """统一写法后再比较：不分大小写、去变音符号、弯撇号改直撇号、合并多余空白。"""
    # NFKD 把 é 拆成 e + 一个「组合用重音符」，去掉组合符就只剩 e；中文字符不受影响
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    stripped = stripped.replace("’", "'").replace("‘", "'")
    return " ".join(stripped.split())


def resolve_poi(query: str, pois: Sequence[Poi], city: str | None = None) -> ResolveResult:
    """把用户说的景点名对应到 poi_id。city 为空时不按城市过滤。"""
    key = normalize(query)
    if not key:
        raise ValueError("query 不能为空")

    matches = [poi for poi in pois if key in _match_keys(poi)]
    if city and city.strip():
        matches = [poi for poi in matches if normalize(poi.city) == normalize(city)]
    matches.sort(key=lambda poi: poi.id)

    return ResolveResult(
        status=_status(len(matches)),
        query=query,
        city=city,
        candidates=[_candidate(poi) for poi in matches],
    )


def _match_keys(poi: Poi) -> set[str]:
    """一个景点能被叫出的所有名字（三种语言的正式名 + 别名），统一写法后的集合。"""
    names = [poi.names.local, poi.names.en, poi.names.zh, *poi.aliases]
    return {normalize(name) for name in names if name}


def _status(count: int) -> Literal["MATCH", "AMBIGUOUS", "NOT_FOUND"]:
    if count == 0:
        return "NOT_FOUND"
    return "MATCH" if count == 1 else "AMBIGUOUS"


def _candidate(poi: Poi) -> Candidate:
    return Candidate(
        poi_id=poi.id,
        name_zh=poi.names.zh,
        name_en=poi.names.en,
        name_local=poi.names.local,
        city=poi.city,
        category=poi.category,
    )
