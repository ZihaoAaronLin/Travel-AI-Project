"""同名消歧：名字或别名精确匹配，不做模糊匹配；多个候选就全部列出，交给用户选，绝不自动挑一个。

原词匹配不上时有一次「拆开再试」的回退，只处理两种说法，规则见 _fallback。
"""

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

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
    city: str | None  # 实际用来过滤的城市：调用方给的，或从「布达佩斯的…」里认出来的
    candidates: list[Candidate]  # 按 poi_id 排序，顺序不代表优先级
    matched_query: str | None = Field(
        default=None,
        description="原词没直接命中、拆开后才认出来时，实际用来匹配的说法；原词直接命中时为 null",
    )


@dataclass(frozen=True)
class _Hit:
    """回退找到的结果。ask=True 表示只认出了一部分：不管几个候选都要问用户。"""

    pois: list[Poi]
    matched_query: str
    city: str | None
    ask: bool = False


_DE = "的"
_LOCATIVES = ("里", "内")  # 「沃伊达奇城堡里的…」：方位词不是名字的一部分


def normalize(text: str) -> str:
    """统一写法后再比较：不分大小写、去变音符号、弯撇号改直撇号、合并多余空白。"""
    # NFKD 把 é 拆成 e + 一个「组合用重音符」，去掉组合符就只剩 e；中文字符不受影响
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    stripped = stripped.replace("’", "'").replace("‘", "'")
    return " ".join(stripped.split())


def resolve_poi(
    query: str,
    pois: Sequence[Poi],
    city: str | None = None,
    city_names: Mapping[str, Sequence[str]] | None = None,
) -> ResolveResult:
    """把用户说的景点名对应到 poi_id。city 为空时不按城市过滤。

    city_names 是城市的其他叫法（{"Budapest": ["布达佩斯"]}），只在回退时用来认出开头的城市名。
    """
    key = normalize(query)
    if not key:
        raise ValueError("query 不能为空")
    city_filter = city if city and city.strip() else None

    # 原词能直接命中就不拆：「布达佩斯美术馆」是一家馆的正式名称，不能当成「布达佩斯 + 美术馆」
    direct = _match(key, pois, city_filter)
    if direct:
        return _result(query, city, direct)

    hit = _fallback(key, pois, city_filter, _city_aliases(pois, city_names or {}))
    if hit is None:
        return _result(query, city, [])
    return _result(query, hit.city, hit.pois, hit.matched_query, ask=hit.ask)


def _fallback(key: str, pois: Sequence[Poi], city: str | None, aliases) -> _Hit | None:
    """原词 NOT_FOUND 之后的回退。宁可 NOT_FOUND，也不猜：

    1. 开头是认得的城市名（后面可跟「的」）→ 去掉，只在那座城市里查剩下的；和 city 参数冲突就放弃
    2. 剩下的是「A 的 B」→ 交给 _split_de
    """
    stripped = _strip_city(key, aliases)
    if stripped is not None:
        found_city, key = stripped
        if city is not None and normalize(city) != normalize(found_city):
            return None  # 说的是维也纳，却限定在布达佩斯里查：自相矛盾
        city = city or found_city
        direct = _match(key, pois, city)
        if direct:
            return _Hit(direct, key, city)
    return _split_de(key, pois, city)


def _split_de(key: str, pois: Sequence[Poi], city: str | None) -> _Hit | None:
    """「A 的 B」：A 必须本身是景点名（否则 A 可能是库里没有的城市，不能只拿 B 去查）。

    - 「AB」连写或 B 认得出、且落在 A 的候选里 → 就是它们
    - B 认不出 → 列出 A 的候选，但必须问（部分区域的开放时间可能和整体不同）
    - B 认得出却不在 A 的候选里 → 两半对不上，放弃
    """
    if _DE not in key:
        return None
    place, part = (piece.strip() for piece in key.split(_DE, 1))
    place = _drop_locative(place)
    if not place or not part:
        return None
    around = _match(place, pois, city)
    if not around:
        return None

    around_ids = {poi.id for poi in around}
    for candidate in (place + part, part):
        named = _match(candidate, pois, city)
        if named:
            inside = [poi for poi in named if poi.id in around_ids]
            return _Hit(inside, candidate, city) if inside else None
    return _Hit(around, place, city, ask=True)


def _strip_city(key: str, aliases: list[tuple[str, str]]) -> tuple[str, str] | None:
    """开头是城市名就返回 (城市, 剩下的部分)。长的叫法先试，免得短名字截掉长名字的一半。"""
    for alias, canonical in aliases:
        if not key.startswith(alias):
            continue
        rest = key[len(alias) :]
        # 拉丁字母的城市名后面必须断开：「budapesti」不是「budapest」+「i」
        if _is_latin(alias[-1]) and rest[:1] and _is_latin(rest[0]):
            continue
        rest = rest.strip()
        if rest.startswith(_DE):
            rest = rest[len(_DE) :].strip()
        if rest:
            return canonical, rest
    return None


def _city_aliases(pois: Sequence[Poi], city_names: Mapping[str, Sequence[str]]):
    """[(统一写法后的叫法, 城市英文名)]。景点的 city 字段本身也算一个叫法。"""
    pairs = {normalize(poi.city): poi.city for poi in pois}
    for canonical, names in city_names.items():
        pairs[normalize(canonical)] = canonical
        pairs.update({normalize(name): canonical for name in names})
    return sorted(pairs.items(), key=lambda pair: len(pair[0]), reverse=True)


def _drop_locative(place: str) -> str:
    return place[:-1] if place.endswith(_LOCATIVES) else place


def _is_latin(ch: str) -> bool:
    return ch.isascii() and ch.isalpha()


def _match(key: str, pois: Sequence[Poi], city: str | None) -> list[Poi]:
    matches = [poi for poi in pois if key in match_keys(poi)]
    if city is not None:
        matches = [poi for poi in matches if normalize(poi.city) == normalize(city)]
    return matches


def _result(query, city, matches, matched_query=None, ask=False) -> ResolveResult:
    matches = sorted(matches, key=lambda poi: poi.id)
    return ResolveResult(
        # ask：只认出一部分，哪怕只有一个候选也要用户确认
        status="AMBIGUOUS" if ask and matches else _status(len(matches)),
        query=query,
        city=city,
        candidates=[_candidate(poi) for poi in matches],
        matched_query=matched_query,
    )


def match_keys(poi: Poi) -> set[str]:
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
