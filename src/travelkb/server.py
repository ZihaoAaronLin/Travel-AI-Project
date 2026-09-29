"""travelkb 的 MCP 薄适配层：只把 core/ 的逻辑包装成 MCP 工具，本身不放业务逻辑。

Claude Desktop 以 stdio 方式把本进程起成子进程：stdout 是 JSON-RPC 数据通道，
任何 print() 都会把协议帧写坏。日志一律走 stderr——MCPServer 构造时已把 root logger
配成写 stderr 的 RichHandler，这里不再重复配置。
"""

import logging
from importlib.metadata import version

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# 版本号只在 pyproject.toml 维护一处，这里读已安装包的元数据
SERVER_VERSION = version("travel-kb")

mcp = MCPServer("travelkb")


class PingResult(BaseModel):
    ok: bool = Field(description="server 正常响应时为 true")
    server_version: str = Field(description="travel-kb 包的版本号")


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
def ping() -> PingResult:
    """连通性检查：确认 travelkb server 已启动并能响应。不读取任何数据。"""
    return PingResult(ok=True, server_version=SERVER_VERSION)


def main() -> None:
    """脚本入口（pyproject 里的 travelkb-server）。"""
    logger.info("travelkb %s starting on stdio", SERVER_VERSION)
    mcp.run()  # 默认 transport="stdio"


if __name__ == "__main__":
    main()
