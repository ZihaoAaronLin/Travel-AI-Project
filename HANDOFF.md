# HANDOFF

## 2026-10-10（夜）· 第 1 阶段收尾 + 第 2 阶段计划（待 Aaron 确认）

### 第 1 阶段验收
- Inspector 5 条全对（Aaron 2026-10-10）
- Claude Desktop 验收（同名追问、无 SOP / 有 SOP 各问一遍）：Aaron 稍后发截图和清单

### 第 2 阶段计划（Aaron 已确认，已同步进 ROADMAP 第 2 阶段）
- 顺序 2a → 2b → 2c → 2d → 2e；arrive_early_min 推迟到第 4 阶段；STALE 阈值 14 天
- CC 对两条要求的理解（Aaron 审测试时确认）：
  - 「例外之后给出相关建议」→ 结论 CLOSED 时附 next_open_date（下一个确定能去的日子）
  - 「check_day_plan 的问题能逐一解决」→ 每个问题带编号、站点、修复建议，模型逐条修完再验（2b 的测试里体现）
- 同名撞车组的金标准：Aaron 说先不补，放到 2c

### 2a 测试（红，等 Aaron 审）
- tests/unit/test_exception_kinds.py：date / dates / rrule 三选一；8 种写错要拒收（含 rrule 里夹 DTSTART——dateutil 会悄悄用它覆盖起点）；区间、每月最后一个周一、rrule 只在自己的 valid 内生效、不同写法撞在同一天算冲突
- tests/unit/test_suggestions.py：next_open_date（跳过连续闭馆日、绝不推荐 UNKNOWN 的日子、窗口外不推荐、还没开门/开着/UNKNOWN/永久停业时不给）；STALE（不给 as_of 不判断、第 14 天不算、第 15 天提醒且结论不变）
- tests/unit/test_validate_exceptions.py：区间 / rrule 覆盖到有效期外 → error；不同写法撞同一天且结论不同 → error
- tests/unit/test_tools_suggestions.py：工具输出 next_open_date、warnings；过期按景点当地日期判断（UTC 还是第 14 天、布达佩斯已是第 15 天）
- 现状：28 条红（未实现），8 条「写错要拒收」已经绿（现有模型本来就拒收不认识的字段）；原有 131 条照常通过
- 测试定下的接口：is_open(poi, day, at=None, as_of=None)；OpenResult 新增 next_open_date、warnings[{code, message}]；DayException 新增 dates、rrule、valid
- 旧测试 test_models.py::test_rrule_exception_is_rejected_in_stage_1 仍然成立（date + rrule 同时写违反三选一），但名字和注释已过时；要不要改名等 Aaron 定（铁律 5）

## 2026-10-10（晚）· MCP 工具上线 + 数据校验

### 做了什么
- 数据：布达佩斯美术馆补 11/13 调整（e2，Aaron 10/10 复制原文，已存进 data/sources/）
- 金标准：g08 改成 2026-11-13（原题 10/09 已过、官网删了没法复核）；expect 由 CC 按 Aaron 复制的原文填，**待 Aaron 确认**；10/10 全过
- 替 Aaron 审了上一批测试，实现前先修了 3 处（单独提交 c7a13e2，之后 tests/ 没再动）：
  1. city 测试太弱：「纽约示例馆」本来就唯一，工具丢了 city 也会过 → 改成限定纽约查「示例馆」应 NOT_FOUND
  2. 缺真实接线测试：单元测试全用假数据，模块级 server 不读 data/pois 也全绿 → test_server 加一条真实 server 查「美术馆」
  3. 冲突测试靠 issues[0] 碰巧取对 → 改成按 code 找
- 实现：
  - server.py：build_server(pois, clock)；工具 resolve_poi / is_open（只读）；不给日期按景点时区算今天；坏参数、未知 poi_id 用 ToolError 告诉模型；结果日期 YYYY-MM-DD、时刻 HH:MM；模块级 mcp 启动时读 data/pois/
  - core/validate.py + scripts/validate_data.py：真实数据 error 0、warning 0、info 13
  - 「两条规则结论是否相同」统一成 Hours.verdict_key()，引擎和校验共用
- 全部 123 条测试通过；容器里按 Claude Desktop 的方式（uv --directory、从 / 启动、真实 stdio）调通三个工具
- CLAUDE.md 常用命令：去掉 build_db.py（推迟到第 2 阶段）

### 第 1 阶段验收还差（都在 Aaron 那边）
1. git pull 后完全退出再打开 Claude Desktop（server 代码变了，要重启才会加载新工具）
2. Desktop 里问「下周一去布达佩斯美术馆」：模型应先调 resolve_poi，拿到 AMBIGUOUS 后问你是哪一家；截图留给 README
3. Inspector：「美术馆」+ Budapest → AMBIGUOUS；闭馆日 → CLOSED 带 source_url；窗外日期 → UNKNOWN
4. Claude Desktop 的 Project 指令里写最简 SOP（A 版起点）：先 resolve_poi 再 is_open；AMBIGUOUS 就问；UNKNOWN 就说不确定并给官网链接

### 已知问题 / 之后
- 同名撞车 4 组（渔人堡、沃伊达奇城堡、大教堂、美术馆），只有「美术馆」有金标准；ROADMAP 要求每组都有，第 2 阶段补
- 11/13 这件事说明 90 天有效期对「临时调整」太长：第 2 阶段设计复核策略
- 日志配置依赖 SDK 的 configure_logging（见下方更早的记录）

## 2026-10-10 · 金标准第一轮

### 做了什么
- Aaron 填了 10 条金标准（commit 42a6b6d），但 expect 写成了中文判断句，runner 读不了（10 条都报 AttributeError）
- CC 只做格式转换：每条结论按原意译成字段（status / weekday / reason_code / 时刻 / 候选），Aaron 原话原样保留在 note；checked_at 改成 ISO 日期
- runner：expect 不是字段时给出明确提示；模板说明补了一行可照抄的例子
- 结果：9 通过，g08 失败（期望 OPEN，引擎答 CLOSED）

### g08 失败的归因：金标准过期，不是引擎错
- Aaron 10/08 的官网原文（data/sources/2026-10-08-official-pages.md 第 63–65 行）写着「We are open on 9 OCTOBER from 12.00 to 20.00」→ 10/09 11:00 进不去，引擎对
- 10/10 再看官网时，10/09 已过去、这条被删，页面换成了下一个特殊日「Friday, 13 November」；按新页面推断 10/09 是常规时间，结论就错了
- 按铁律 5 没改 Aaron 的答案，g08 保持红，等 Aaron 定

### 新发现：数据已经过期了一处
- 官网 10/08 之后新公布了 2026-11-13（周五）的调整，data/pois/museum-of-fine-arts-budapest.yaml 里没有 → 引擎现在会按常规时间回答 11/13，可能答错
- 90 天有效期假设「核验后官网不会新增例外」，这次两天就被推翻：临时调整类信息需要更短的复核周期（第 2 阶段设计 STALE / 复核策略时用这个例子）

### 待 Aaron
1. g08 二选一：改成你按 10/08 原文的判断；或者（建议）把题改成 2026-11-13，因为 10/09 已经没法在官网复核了
2. 复制布达佩斯美术馆官网 13 November 的调整原文 → CC 补进 data/sources 和 YAML（e2）
3. 确认 CC 对 g09 的转换：你的原话先说「能进」，后说「找不到确切信息，须如实告知用户」，CC 译成 UNKNOWN
4. 审 test_tools.py、test_validate.py（上一批红测试）

## 2026-10-08（下午）· core 实现 + 金标准骨架

### 做了什么
- 数据：Aaron 核对完 12 个 YAML，全部改成 review: verified
  - 大教堂两条：verified_at 从 CC 抓取日 9/30 改成 Aaron 核对日 10/08，valid 重算为 2026-10-08 ~ 2027-01-06
  - 渔人堡 2025 按官网笔误处理（取 2026）；抹大拉的马利亚塔保留
- 实现 src/travelkb/core/：models.py、loader.py、resolve.py、hours.py
  - 单元测试 63 个函数（展开后 80 条）+ 数据加载 1 条，一次全绿；tests/ 在审过之后没有改动
- 金标准骨架：tests/golden/cases.yaml（10 题，只填了问题、调用、去哪查；expect 留空）+ test_cases.py（runner）
  - expect 为 null 的题自动跳过；CC 私下确认过 10 条调用都能执行、写错 expect 会失败，但没有看引擎答案，避免影响 Aaron 独立核对

### 下一批测试（红，等 Aaron 审）
- Aaron 定：SQLite 推迟到第 2 阶段，第 1 阶段 server 直接读 YAML（ROADMAP 已改）
- tests/unit/test_tools.py（12）：MCP 层接线——工具注册且只读、工具描述里写明先 resolve 再 is_open / AMBIGUOUS 要问 / UNKNOWN 的含义、结果里日期 "YYYY-MM-DD" 时刻 "HH:MM"、坏日期坏时刻和未知 poi_id 以 is_error 告诉模型、不给日期时按景点时区算「今天」（注入固定时钟，同一时刻布达佩斯已是周一、纽约还是周日）
- tests/unit/test_validate.py（10）：validate_data 的核心逻辑 core/validate.py——error / warning / info 三级
- tests/golden/test_data_validation.py（1）：真实数据零 error、零 warning
- 测试定下的接口：travelkb.server.build_server(pois, clock)；travelkb.core.validate.validate_pois(pois) → Issue(level, code, poi_id, message)
- 现在这 3 个文件因为 build_server / core.validate 不存在而收集失败——预期的红；其余 81 条照常通过

### 没做完
- 10 条金标准的 expect 等 Aaron 回官网填写
- 上面这批测试等 Aaron 审，审过再实现 build_server、core/validate.py、scripts/validate_data.py

### 下一步
1. Aaron：填 10 条金标准；审 test_tools.py、test_validate.py
2. CC：实现到全绿（不改测试）
3. Aaron：Claude Desktop 里问「下周一去布达佩斯美术馆」，验收同名追问；在 Project 指令里写最简 SOP（先 resolve 再 is_open；UNKNOWN 就说不确定）

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
