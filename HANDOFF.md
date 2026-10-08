# HANDOFF

## 2026-10-08（下午）· core 实现 + 金标准骨架

### 做了什么
- 数据：Aaron 核对完 12 个 YAML，全部改成 review: verified
  - 大教堂两条：verified_at 从 CC 抓取日 9/30 改成 Aaron 核对日 10/08，valid 重算为 2026-10-08 ~ 2027-01-06
  - 渔人堡 2025 按官网笔误处理（取 2026）；抹大拉的马利亚塔保留
- 实现 src/travelkb/core/：models.py、loader.py、resolve.py、hours.py
  - 单元测试 63 个函数（展开后 80 条）+ 数据加载 1 条，一次全绿；tests/ 在审过之后没有改动
- 金标准骨架：tests/golden/cases.yaml（10 题，只填了问题、调用、去哪查；expect 留空）+ test_cases.py（runner）
  - expect 为 null 的题自动跳过；CC 私下确认过 10 条调用都能执行、写错 expect 会失败，但没有看引擎答案，避免影响 Aaron 独立核对

### 没做完
- 10 条金标准的 expect 等 Aaron 回官网填写
- MCP 工具还没注册：server.py 里只有 ping
- build_db.py / validate_data.py 还没写

### 下一步
1. Aaron：按 cases.yaml 顶部说明填 10 条 expect，跑 `uv run pytest tests/golden -rs`
2. Aaron 定：第 1 阶段要不要上 SQLite（见下）
3. CC：写下一批测试（红）给 Aaron 审：server 的 resolve_poi / is_open 工具（内存 Client）、validate_data；审过再实现
4. 之后：Claude Desktop 里问「下周一去布达佩斯美术馆」，验收同名追问

### 待定：第 1 阶段要不要 SQLite
- ROADMAP 原计划第 1 阶段就 YAML → build_db.py → SQLite，运行时只读打开
- CC 建议：第 1 阶段 server 启动时直接 load_pois 读 YAML（12 条，毫秒级），SQLite 推迟到第 2 阶段 query_kb 真正需要 SQL 时再上。理由是总原则 4「先用最笨的办法」；core 不依赖存储方式，以后换 SQLite 只改加载那一层

## 2026-10-08（上午）· 第 1 阶段数据草稿

### 做了什么
- Aaron 定：拆分（渔人堡、沃伊达奇城堡、大教堂都拆）；草稿标记用 review 字段；有效期按核验后 90 天
- 官网原文存档：data/sources/2026-10-08-official-pages.md（Aaron 复制的 6 段 + CC 9/30 抓的大教堂匈语页）
- 起草 12 条 data/pois/*.yaml，全部 review: draft；时间全加引号；每条规则上方注释贴官网原文
  - 国会大厦 1；渔人堡 收费观景台 + 免费区域 2；抹大拉的马利亚塔 1；国家美术馆 1；布达佩斯美术馆 1
  - 沃伊达奇城堡：庭院 + 农业博物馆 + 使徒塔 + 城门塔 4；大教堂：教堂大厅 + 观景台与珍宝馆 2
  - 渔人堡免费区域、城堡庭院没有官方来源 → rules: []，查出来永远是 UNKNOWN；保留它们是为了让「渔人堡」「沃伊达奇城堡」返回 AMBIGUOUS
- 草稿自检通过（scratchpad 一次性脚本）：YAML 可解析、时间都是 "HH:MM" 字符串、valid 都在核验后 90 天内、例外日期都落在规则有效期内
- 有效期取法写进 ROADMAP 第 7 节：valid = [verified_at, verified_at + 90 天] ∩ 官网时间窗
- CLAUDE.md 铁律 6、ROADMAP 第 7 节：草稿标记改成 review: draft，status 只表示营业状态

### 规则语义（Aaron 2026-10-08 定，已写进 ROADMAP 第 7 节）
1. 规则加 `outside_hours: UNKNOWN | CLOSED`（默认 CLOSED）；渔人堡收费观景台用 UNKNOWN
2. 第 1 阶段就做单日例外；区间 / rrule 留到第 2 阶段，数据模型直接拒绝这类数据（不静默忽略）
3. 国家美术馆、使徒塔周一闭馆：Aaron 确认，已在 YAML 加 MON closed 规则。引擎的通用规则不变：没写的星期 → UNKNOWN
4. 拆分后的同名追问可以接受；候选按「选项」设计（id、三种名字、城市、类别），前端以后渲染成可点选项
5. CC 补充的两点，Aaron 审测试时一并确认：TEMP_CLOSED（没写恢复日期）→ UNKNOWN；原第 5 步 STALE 取消（90 天有效期已覆盖）

### 单元测试（红，等 Aaron 审）
- tests/unit/：test_models（20）、test_loader（4）、test_resolve（13）、test_is_open（26），共 63 个测试函数；tests/golden/test_data_files 1 个
- 目前全部因为 `No module named 'travelkb.core'` 收集失败——这是预期的红；test_server 的 2 个 ping 测试仍绿
- 测试定下的接口：core/models.py（Poi 等）、core/loader.py（load_pois）、core/resolve.py（resolve_poi）、core/hours.py（is_open）
- 结果里用 reason_code 给机器判分（评测用），reason 给模型看
- 发现：pydantic 默认把整数 600 悄悄转成 00:10，所以「时间必须是带引号的字符串」要在模型里显式校验（有专门的测试）
- pyproject：ruff isort 显式声明 travelkb 为本项目包

### 待 Aaron 核对的数据
- 渔人堡官网 Opening period 写的是「2025」，标题是「2026」，疑似官网笔误
- 抹大拉的马利亚塔（Magdolna-torony）不是渔人堡的一部分，只是共用售票站；已单独建一条，留不留由 Aaron 定
- 布达佩斯美术馆 10/9 的调整没写年份，按页面「Today, October 8」判定为 2026-10-09
- 大教堂两条的 verified_at 是 CC 9/30 的抓取日期，Aaron 还没核对；last_entry 用的是售票截止时间
- 国会大厦这页的时段是导览时段还是访客中心时段，页面没说明
- 使徒塔、城门塔的匈牙利语名官网没给（names.local: null）；几个中文名是 CC 的译名
- 第三方站 vajdahunyadcastle.com 写冬季 10–16 点，官网写全年 10–17 点：只用官方来源的现成例子
- ROADMAP 第 2 阶段用国家美术馆举「每月最后一个周一闭」，这次官网原文不支持，要换例子

### 下一步
1. Aaron：审 tests/unit/ 的测试（重点看 test_is_open.py 每条断言是不是你认同的语义）；要改哪条直接说
2. CC：测试审过后实现 core/models、loader、resolve、hours，跑到全绿；不改测试
3. 之后：build_db.py（YAML → SQLite）+ validate_data.py（例外是否落在有效期内、有效期是否超 90 天、别名撞车清单）+ server 注册 resolve_poi / is_open
4. Aaron：逐条核对 12 个 YAML（review 改成 verified）；写 10 条金标准

### 已知问题
- 日志配置依赖 SDK 的实现细节（MCPServer.__init__ 里的 configure_logging）；SDK 升级后若不再配置，INFO 日志会丢，但 WARNING 以上仍走 stderr，不会写到 stdout
- 「用户是否真的在乎核验」是未验证假设，演示前要找真实用户或评论区证据
- 云端抓不到大部分官网（451 / 前端渲染 / 网络策略），第 4 阶段的抽取管线要在 Aaron 本机跑，或换能访问的环境

## 2026-09-30 · 定位调整 + 第 1 阶段准备

- 第 0 阶段验收完成：Aaron 本机 pytest、Inspector、Claude Desktop 都调通了 ping
- 路线图进仓库：docs/ROADMAP.md
- 定位调整（细节见 ROADMAP 开头）：做「行程核验」；模型 + 搜索只做数据采集（产出 draft）→ 代码判定 → 人工抽检校准；评测新增 A6（模型 + 联网搜索）、可选 A7（圆周旅迹）
- 第 1 阶段城市定为布达佩斯
- 官网抓取：只有大教堂成功；两家美术馆返回 451，渔人堡要 JS 渲染，国会和农业博物馆被网络策略拦截；vajdahunyadcastle.com 查明不是官方站

## 2026-09-29 · 第 0 阶段骨架

- uv 包项目（Python 3.12，src 布局，import 名 travelkb）；依赖 mcp[cli] 2.2.0、pydantic、pyyaml、python-dateutil；dev：pytest、anyio、ruff
- server.py：MCPServer("travelkb")，只读 ping 工具返回 {ok, server_version}；脚本入口 travelkb-server
- 日志走 SDK 配好的 stderr handler；ruff 开 T20 禁 print
- tests/test_server.py：内存 Client 断言 structured_content 和 read_only_hint
- CLAUDE.md 铁律 3 改为：core 不调 now()，「今天」由 server 层按景点时区算好再传入
