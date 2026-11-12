"""resolve_poi 的回退：原词精确匹配不上时，再按「城市名 + 的 + 景点名」「A 的 B」拆开试一次。

为什么要：模型常把用户原话原样传进来（「布达佩斯的美术馆」「沃伊达奇城堡里的农业博物馆」），
精确匹配全是 NOT_FOUND，只能靠模型自己改写；改写错了（Desktop 里把「布达佩斯的美术馆」
并成「布达佩斯美术馆」）就会跳过追问。拆法交给代码，结果可测、可复现。

回退规则（只在原词 NOT_FOUND 时才走）：
1. 开头是已知城市名（后面可跟「的」）→ 去掉，只在那座城市里查剩下的部分；
   和 city 参数冲突 → NOT_FOUND。认不出的城市名不去掉（可能是库里没有的城市，不猜）
2. 剩下的是「A 的 B」（A 末尾的「里 / 内」去掉）：A 本身必须是景点名，否则 NOT_FOUND
   - B（或 A、B 连写）认得出、且在 A 的候选里 → 就是它们，按个数 MATCH / AMBIGUOUS
   - B 认不出 → 列出 A 的候选，状态一律 AMBIGUOUS：只认出一部分，必须问用户，哪怕只有一个候选
   - B 认得出但不在 A 的候选里 → NOT_FOUND（两半自相矛盾，不猜）

接口：
- resolve_poi(query, pois, city=None, city_names=None)
  city_names = {城市英文名: [其他叫法]}；景点的 city 字段本身也算一个叫法
- ResolveResult.matched_query：原词直接命中时为 None；回退命中时是实际用来匹配的说法（统一写法后）
- ResolveResult.city：实际用来过滤的城市；从「布达佩斯的…」认出来的也填上
"""

import pytest

from travelkb.core.resolve import resolve_poi

CITY_NAMES = {"Budapest": ["布达佩斯"], "Vienna": ["维也纳"]}


def names(zh: str, en: str) -> dict:
    return {"local": None, "en": en, "zh": zh}


@pytest.fixture
def pois(make_poi):
    """假数据，结构照着真实数据里的几组撞名：

    - 两家馆都叫「示例馆」，其中一家的正式中文名就带城市名（像「布达佩斯美术馆」）
    - 教堂和穹顶都能叫「示例大教堂」（像圣史蒂芬大教堂的教堂 / 观景台）
    - 农业馆和庭院都能叫「示例城堡」（像沃伊达奇城堡里的农业博物馆 / 庭院）
    - 维也纳也有一家叫「示例馆」
    """
    return [
        make_poi(
            id="demo-fine-arts", names=names("布达佩斯示例馆", "Demo Fine Arts"), aliases=["示例馆"]
        ),
        make_poi(
            id="demo-gallery",
            names=names("示例国家馆", "Demo National Gallery"),
            aliases=["示例馆"],
        ),
        make_poi(id="demo-church", names=names("示例大教堂", "Demo Basilica"), aliases=[]),
        make_poi(
            id="demo-dome",
            names=names("示例大教堂穹顶", "Demo Basilica Dome"),
            aliases=["示例大教堂"],
        ),
        make_poi(
            id="demo-castle-museum",
            names=names("示例农业馆", "Demo Agriculture Museum"),
            aliases=["示例城堡"],
        ),
        make_poi(
            id="demo-castle-yard",
            names=names("示例城堡庭院", "Demo Castle Yard"),
            aliases=["示例城堡"],
        ),
        make_poi(
            id="demo-vienna",
            city="Vienna",
            country="AT",
            tz="Europe/Vienna",
            names=names("维也纳示例分馆", "Vienna Demo"),
            aliases=["示例馆"],
        ),
    ]


def resolve(query, pois, **kwargs):
    kwargs.setdefault("city_names", CITY_NAMES)
    return resolve_poi(query, pois, **kwargs)


def ids(result):
    return [c.poi_id for c in result.candidates]


# ---- 原词直接命中：不走回退 ----


def test_direct_hits_report_no_matched_query(pois):
    result = resolve("示例馆", pois)

    assert result.status == "AMBIGUOUS"
    assert result.matched_query is None
    assert result.city is None


def test_exact_name_wins_even_if_it_contains_a_city(pois):
    # 试跑 A3 的教训：「布达佩斯美术馆」是一家馆的正式名称，去掉城市名就成了两家都叫的「美术馆」
    result = resolve("布达佩斯示例馆", pois)

    assert result.status == "MATCH"
    assert ids(result) == ["demo-fine-arts"]
    assert result.matched_query is None


# ---- 规则 1：开头的城市名 ----


def test_city_de_generic_is_not_merged_into_a_name(pois):
    # Desktop 观察：「布达佩斯的美术馆」是城市 + 通称，不能并成「布达佩斯美术馆」只剩一家
    result = resolve("布达佩斯的示例馆", pois)

    assert result.status == "AMBIGUOUS"
    assert ids(result) == ["demo-fine-arts", "demo-gallery"]
    assert result.matched_query == "示例馆"
    assert result.city == "Budapest"


def test_city_prefix_without_de(pois):
    result = resolve("布达佩斯示例大教堂", pois)

    assert result.status == "AMBIGUOUS"
    assert ids(result) == ["demo-church", "demo-dome"]
    assert result.matched_query == "示例大教堂"


def test_city_prefix_limits_search_to_that_city(pois):
    result = resolve("维也纳的示例馆", pois)

    assert result.status == "MATCH"
    assert ids(result) == ["demo-vienna"]
    assert result.city == "Vienna"


def test_unknown_city_prefix_is_not_stripped(pois):
    # 「柏林」不在城市表里：去掉它就会把布达佩斯和维也纳的「示例馆」当成答案
    assert resolve("柏林的示例馆", pois).status == "NOT_FOUND"


def test_prefix_city_conflicting_with_city_param(pois):
    assert resolve("维也纳的示例馆", pois, city="Budapest").status == "NOT_FOUND"


def test_prefix_city_same_as_city_param(pois):
    result = resolve("布达佩斯的示例馆", pois, city="Budapest")

    assert ids(result) == ["demo-fine-arts", "demo-gallery"]


def test_poi_city_field_counts_as_a_city_name(pois):
    # 不用写进城市表：景点的 city 字段（英文）本身就是一个叫法
    result = resolve("Budapest Demo Basilica", pois, city_names=None)

    assert result.status == "MATCH"
    assert ids(result) == ["demo-church"]
    assert result.matched_query == "demo basilica"


def test_without_city_names_a_chinese_city_is_not_guessed(pois):
    # 没有城市表就认不出「布达佩斯」：宁可 NOT_FOUND，也不能并成「布达佩斯示例馆」只剩一家
    assert resolve("布达佩斯的示例馆", pois, city_names=None).status == "NOT_FOUND"


# ---- 规则 2：A 的 B ----


def test_de_joins_a_place_and_its_part(pois):
    result = resolve("示例大教堂的穹顶", pois)

    assert result.status == "MATCH"
    assert ids(result) == ["demo-dome"]
    assert result.matched_query == "示例大教堂穹顶"


def test_locative_suffix_on_the_place_is_dropped(pois):
    # 真实题 q07：「沃伊达奇城堡里的农业博物馆」
    result = resolve("示例城堡里的示例农业馆", pois)

    assert result.status == "MATCH"
    assert ids(result) == ["demo-castle-museum"]
    assert result.matched_query == "示例农业馆"


def test_unrecognized_part_lists_the_place_and_asks(pois):
    # 真实题 q03：「圣史蒂芬大教堂的教堂大厅」，「教堂大厅」不是哪个景点的名字
    result = resolve("示例大教堂的教堂大厅", pois)

    assert result.status == "AMBIGUOUS"
    assert ids(result) == ["demo-church", "demo-dome"]
    assert result.matched_query == "示例大教堂"


def test_unrecognized_part_asks_even_with_one_candidate(pois):
    # 只认出「示例国家馆」，「地下室」认不出：开放时间可能不一样，不能当成 MATCH 直接答
    result = resolve("示例国家馆的地下室", pois)

    assert result.status == "AMBIGUOUS"
    assert ids(result) == ["demo-gallery"]


def test_place_part_must_be_a_known_name(pois):
    # 「某个广场」不是景点名：不能只拿后半截「示例馆」去查
    assert resolve("某个广场的示例馆", pois).status == "NOT_FOUND"


def test_contradicting_parts_are_not_guessed(pois):
    # 「示例城堡」里没有「示例大教堂」：两半对不上，不挑任何一边
    assert resolve("示例城堡的示例大教堂", pois).status == "NOT_FOUND"


def test_city_prefix_then_de(pois):
    result = resolve("布达佩斯的示例大教堂的穹顶", pois)

    assert result.status == "MATCH"
    assert ids(result) == ["demo-dome"]
    assert result.city == "Budapest"
