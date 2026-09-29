# HANDOFF

## 2026-09-29 · 第 0 阶段骨架

### 做了什么
- uv 包项目（Python 3.12，src 布局，import 名 travelkb）；依赖 mcp[cli] 2.2.0、pydantic、pyyaml、python-dateutil；dev：pytest、anyio、ruff
- src/travelkb/server.py：MCPServer("travelkb")，只有一个只读 ping 工具，返回 {ok, server_version}；脚本入口 travelkb-server
- 日志：MCPServer 构造时已把 root logger 配成写 stderr（RichHandler），server.py 不再自己配；ruff 开 T20，print 会报错
- tests/test_server.py：内存 Client 断言 structured_content 和 read_only_hint，2 个测试全绿
- 已在容器里验证：从 / 目录用 `uv --directory <项目> run travelkb-server` 真实 stdio 起进程，ping 正常，stdout 无多余输出
- CLAUDE.md 铁律 3 按讨论改回：core 不调 now()，「今天」由 server 层按景点时区算好再传入

### 没做完
- Inspector 界面里手动调 ping（容器里只确认了 Inspector 能启动）
- Claude Desktop 里接入并调 ping（需要 Aaron 在本机做）

### 下一步
- Aaron 本机验收第 0 阶段；选第 1 阶段城市和 6 个景点、录数据、写 10 条金标准
- 第 1 阶段：data/ YAML → scripts/build_db.py → core 的 resolve_poi / is_open

### 已知问题
- 日志配置依赖 SDK 的实现细节（MCPServer.__init__ 里的 configure_logging）；SDK 升级后若不再配置，INFO 日志会丢，但 WARNING 以上仍走 stderr，不会写到 stdout
