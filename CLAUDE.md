# travel-kb
个人旅行规划用的 MCP Server。模型排行程，本项目的代码核验硬事实：
景点某天开不开、几点最后入场、同名景点是哪一个、末班车几点。

## 技术栈
- Python 3.12 + uv；MCP Python SDK 2.x：`from mcp.server import MCPServer`
- 禁用 1.x API（FastMCP、mcp.server.fastmcp、get_context()）。拿不准先查 https://py.sdk.modelcontextprotocol.io/
- pydantic v2、pyyaml、python-dateutil（rrule）、zoneinfo、sqlite3；测试 pytest + anyio；lint 用 ruff

## 结构
- data/：事实源（YAML，人工核验），唯一真相来源；build/：scripts/build_db.py 生成的 SQLite，不进 git
- src/travelkb/core/：纯逻辑，不依赖 MCP；src/travelkb/server.py：MCP 薄适配层
- tests/unit/ 用 fixtures 假数据测逻辑；tests/golden/ 用真实数据跑金标准；eval/ 端到端评测

## 铁律
1. 拿不准就返回 UNKNOWN，永远不要默认 OPEN
2. server 代码禁止 print；日志只写 stderr 或 TRAVELKB_LOG_DIR 下的文件
3. 日期按景点所在时区的本地日期；core 里不许调用 now()，日期一律由调用方传入。需要「今天」时，由 server.py 按景点时区（ZoneInfo(poi.tz)）算出当地日期再传给 core
4. 返回给模型的每个结论都带 rule_id、source_url、verified_at
5. 先写测试再实现；不许为了通过测试去改测试，要改先问我
6. 不许编造数据。data/ 里的事实只来自我核验过的官方来源；你起草的条目标 status: draft
7. YAML 里的时间一律加引号（"10:00"）：不加引号会被解析成整数 600
8. 函数短小，不直观的逻辑写注释。我要能在面试里讲清每一行
9. 每次会话结束更新 HANDOFF.md：做了什么、没做完什么、下一步、已知问题

## 常用命令
- uv run pytest
- uv run mcp dev src/travelkb/server.py
- uv run python scripts/build_db.py && uv run python scripts/validate_data.py
