"""同名消歧：名字或别名精确匹配（统一大小写、去变音符号）；多个候选就 AMBIGUOUS，绝不自动挑一个。"""

import pytest

from travelkb.core.resolve import resolve_poi


@pytest.fixture
def pois(make_poi):
    """三家假美术馆都叫「美术馆」：两家在布达佩斯，一家在维也纳。"""
    gallery = make_poi(
        id="demo-gallery",
        category="museum",
        names={"local": "Példa Galéria", "en": "Demo Gallery", "zh": "示例国家美术馆"},
        aliases=["美术馆", "Fisherman’s Demo"],
    )
    fine_arts = make_poi(
        id="demo-fine-arts",
        category="museum",
        names={"local": "Példa Múzeum", "en": "Demo Fine Arts", "zh": "示例美术博物馆"},
        aliases=["美术馆", "示例美博"],
    )
    vienna = make_poi(
        id="demo-vienna-museum",
        city="Vienna",
        country="AT",
        tz="Europe/Vienna",
        names={"local": "Beispielmuseum", "en": "Vienna Demo Museum", "zh": "维也纳示例馆"},
        aliases=["美术馆"],
    )
    return [gallery, fine_arts, vienna]


def ids(result):
    return [c.poi_id for c in result.candidates]


# ---- 唯一匹配 ----


def test_exact_chinese_name_matches(pois):
    result = resolve_poi("示例国家美术馆", pois)

    assert result.status == "MATCH"
    assert ids(result) == ["demo-gallery"]


def test_english_name_matches(pois):
    assert ids(resolve_poi("Demo Fine Arts", pois)) == ["demo-fine-arts"]


def test_alias_matches(pois):
    result = resolve_poi("示例美博", pois)

    assert result.status == "MATCH"
    assert ids(result) == ["demo-fine-arts"]


@pytest.mark.parametrize("query", ["pelda muzeum", "PÉLDA MÚZEUM", "  Példa   Múzeum "])
def test_matching_ignores_case_diacritics_and_extra_spaces(pois, query):
    result = resolve_poi(query, pois)

    assert result.status == "MATCH"
    assert ids(result) == ["demo-fine-arts"]


def test_curly_and_straight_apostrophes_are_the_same(pois):
    assert ids(resolve_poi("fisherman's demo", pois)) == ["demo-gallery"]


# ---- 同名 ----


def test_shared_alias_in_same_city_is_ambiguous_with_all_candidates(pois):
    result = resolve_poi("美术馆", pois, city="Budapest")

    assert result.status == "AMBIGUOUS"
    assert ids(result) == ["demo-fine-arts", "demo-gallery"]  # 按 id 排序，不暗示优先级


def test_shared_alias_without_city_lists_candidates_from_every_city(pois):
    result = resolve_poi("美术馆", pois)

    assert result.status == "AMBIGUOUS"
    assert ids(result) == ["demo-fine-arts", "demo-gallery", "demo-vienna-museum"]


def test_city_narrows_to_a_unique_match(pois):
    result = resolve_poi("美术馆", pois, city="vienna")  # 城市名同样不分大小写

    assert result.status == "MATCH"
    assert ids(result) == ["demo-vienna-museum"]


def test_candidates_carry_what_an_option_list_needs(pois):
    # 前端以后要把候选渲染成选项：每个候选要带 id、三种名字、城市、类别
    candidate = resolve_poi("美术馆", pois, city="Budapest").candidates[0]

    assert candidate.poi_id == "demo-fine-arts"
    assert candidate.name_zh == "示例美术博物馆"
    assert candidate.name_en == "Demo Fine Arts"
    assert candidate.name_local == "Példa Múzeum"
    assert candidate.city == "Budapest"
    assert candidate.category == "museum"


# ---- 找不到 ----


def test_unknown_name_is_not_found(pois):
    result = resolve_poi("不存在的博物馆", pois)

    assert result.status == "NOT_FOUND"
    assert result.candidates == []


def test_no_substring_or_fuzzy_matching(pois):
    # 「美术」是「美术馆」的子串，但不做模糊匹配：模糊匹配后自动选中正是要避免的错误
    assert resolve_poi("美术", pois).status == "NOT_FOUND"


def test_city_filter_can_exclude_every_candidate(pois):
    assert resolve_poi("维也纳示例馆", pois, city="Budapest").status == "NOT_FOUND"


@pytest.mark.parametrize("query", ["", "   "])
def test_blank_query_is_an_error(pois, query):
    with pytest.raises(ValueError):
        resolve_poi(query, pois)
