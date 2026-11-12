"""城市别名表 data/cities.yaml：resolve_poi 回退时用来认出「布达佩斯的…」里的城市名。

格式：{城市英文名（和景点的 city 字段一致）: [其他叫法]}。不是营业事实，不需要官网来源。
接口：travelkb.core.loader.load_city_names(path) -> dict[str, list[str]]
"""

import pytest

from travelkb.core.loader import load_city_names


def test_reads_mapping(tmp_path):
    path = tmp_path / "cities.yaml"
    path.write_text("Budapest: [布达佩斯]\nVienna: [维也纳, Wien]\n", encoding="utf-8")

    assert load_city_names(path) == {"Budapest": ["布达佩斯"], "Vienna": ["维也纳", "Wien"]}


@pytest.mark.parametrize(
    "text",
    [
        "- Budapest\n",  # 写成了列表
        "Budapest: 布达佩斯\n",  # 叫法要写成列表，不是单个字符串
        "Budapest: [布达佩斯, 600]\n",  # 叫法必须都是字符串
    ],
)
def test_bad_shape_names_the_file(tmp_path, text):
    path = tmp_path / "cities.yaml"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="cities.yaml"):
        load_city_names(path)
