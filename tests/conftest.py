import pytest


@pytest.fixture
def anyio_backend():
    # anyio 的 pytest 插件默认会在多个后端上各跑一遍；这里只用 asyncio
    return "asyncio"
