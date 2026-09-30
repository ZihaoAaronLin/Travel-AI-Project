# 旅行 AI 工作流（自建 MCP Server）落地路线

> 2026-09-29 立项。决定：**从零开始**（当作没做过，不沿用任何旧代码或旧库），**直接做完整版**，但按阶段交付，每个阶段结束都能演示。
> 分工：Aaron 定规格、录数据、核验金标准、审测试、做验收；Claude Code（下称 CC）写代码和测试；Cowork 带路，每阶段回来复盘、抽问。
> 八月的 Notion 版（v1）是真做过、真用过的，这次只作为评测里的对照组。
>
> **2026-09-30 定位调整：**
> - **不做「又一个行程规划器」，做「行程核验」。**输入任意来源的现成行程（小红书攻略、AI 排的、圆周旅迹导出的），输出体检报告：哪天闭馆、哪站晚于最后入场、哪个名字有歧义、哪条查不到，每条附官网来源
> - **数据采集和判定分层。**模型 + 搜索负责从官网抽取结构化规则（数据采集层），代码负责判定 OPEN / CLOSED / UNKNOWN（判定层），你人工抽检抽取结果、报抽取准确率（校准层）。景点数量由采集管线决定，不由手速决定
> - **「直接让模型联网搜不就行了？」不靠争论，靠评测回答：**新增对照组 A6（模型 + 联网搜索，不给本项目工具）
> - 这是面试作品，不和成熟产品比覆盖；比的是问题定义、方法、评测数字。「用户是否真的在乎核验」是未验证的假设，演示前找真实用户或评论区证据

## 总原则
1. **你定规格，CC 写实现。**规则语义、工具接口、SOP、评测题由你写，面试讲的就是这些。CC 写代码和测试，你审测试
2. **每阶段都能演示、能如实写。**任何阶段停下来都不亏
3. **数字只来自自己跑的评测；数据和金标准只能你核验**
4. **先用最笨的办法。**评测证明不够再加复杂度（Anthropic：「Find the simplest solution possible, and only increase complexity when needed」）
5. **沿用你的招牌方法：**对照组、人工抽检校准、配对比较

## 1. 终点：完整版长什么样

```
官网页面 ── scripts/extract（模型抽取，第 4 阶段起）──▶ status: draft 的 YAML ──▶ 你抽检 / 核验
                                                                    │
data/pois/*.yaml ──┐  你核验过的事实（唯一真相来源）  ◀──────────────┘
data/routes/*.yaml ┤
notes/*.md ────────┘
        │ scripts/build_db.py
        ▼
build/travelkb.sqlite（运行时只读）：事实表 + 笔记全文索引
        │
core/（纯 Python：消歧、规则引擎、行程校验，不依赖 MCP）
        │
server.py（MCP 薄适配层：tools / resources / prompts，stdio）
        │
  ┌─────┴────────────┬──────────────────┐
Claude Desktop     Claude Code        你自己的编排器
（日常用，SOP 在    （开发调试）       （流程写死在代码里，
 Project 指令里）                      兼作评测框架）
```

工具（窄接口，全部只读）：

| 工具 | 输入 | 返回 | 阶段 |
|---|---|---|---|
| resolve_poi | query, city? | MATCH / AMBIGUOUS / NOT_FOUND + 候选 | 1 |
| is_open | poi_id, date, time? | OPEN / CLOSED / UNKNOWN + 时段、最后入场、原因、rule_id、source_url、verified_at、代码算出的星期几 | 1 |
| check_day_plan | date, stops[{poi_id, arrive, leave?}] | 逐站结论 + 问题清单（BLOCKER / WARNING / UNKNOWN） | 2 |
| find_open_pois | city, date, time?, category? | 当天开放的景点（给模型替换用） | 2 |
| query_kb | sql | 只读结果；默认不注册，只给评测对照组用 | 2 |
| search_notes | query, city?, poi_id?, category? | 笔记片段 + note_id | 3 |
| last_departure | route_id, date | 末班 / 首班时间 + 来源 | 4 |

另有 resources（`note://{id}`、`poi://{id}`）和 prompts（`plan_trip`、`audit_itinerary`，即 SOP）。

核心循环：**模型排、代码验。**模型出草稿 → check_day_plan 找硬错误 → 模型改 → 再验，直到没有 BLOCKER；UNKNOWN 的站点在结果里标「未核验」。

## 2. 先弄懂的概念（面试也会问）
- **三种原语，控制权不同：**tools 由模型决定调用；resources 按协议设计由宿主（应用）控制，Claude Desktop 里要你手动选中才进上下文（Claude Code 另给了模型读 resource 的工具，但不能指望每个宿主都这样）；prompts 由用户触发（Claude Code 里是 `/mcp__travelkb__plan_trip` 这样的斜杠命令）。所以要让模型在任何宿主里都能自己查笔记，得做成 search_notes 工具
- **stdio：**Claude Desktop 按配置把 server 起成子进程，双方在 stdin / stdout 上收发 JSON-RPC。stdout 就是数据总线，print() 等于往总线上多挂一个驱动源，帧会被写坏。日志只能走 stderr
- **MCP 和 Function Calling：**MCP 是把工具暴露给宿主的协议，宿主底层仍然走模型的工具调用
- **SDK 已是 2.x：**`pip install mcp` 装到的是 2.x（2.2.0，2026-09-07），类名 `MCPServer`（`from mcp.server import MCPServer`）。Gemini 给的 `from mcp.server.fastmcp import FastMCP` 是 1.x 写法；CC 也容易写成 1.x，所以 CLAUDE.md 里要写死
- **2026-07-28 版规范：**协议核心改成无状态（去掉 initialize 握手和会话），需要状态就由工具返回句柄、让模型传回；roots、sampling、MCP 层的 logging 已弃用。本项目是本地 stdio 加无状态工具，基本不受影响
- **Workflow 还是 Agent：**Anthropic 的定义是 workflow 由「预先写好的代码路径」编排 LLM 和工具，agent 由 LLM 自己决定流程和工具调用。严格说，SOP 写在 Project 指令里，流程仍由模型执行，模型可以不照做（v1 里「模型常跳过检索」就是证据）。所以完整版两种都做：A 版 SOP 在提示词里，B 版流程写死在代码里，用评测比较
- **三值逻辑：**OPEN / CLOSED / UNKNOWN。UNKNOWN 就是数字电路里的 X 态：没有驱动就是 X，既不能当 0 也不能当 1。Gemini 示例「查不到就返回正常开放」就是把 X 当成 1 输出。这个项目的价值恰在于该说不知道时说不知道
- **窄接口 vs 让模型写 SQL：**窄接口把日期比较和规则优先级放进代码；让模型写 SQL，日期逻辑又回到模型手里。两种都做，评测里比答错率，检验「比较交给代码」这个论点

## 3. 和 CC 协作的方法
每一步都走这个循环：
1. 你按本文写好这一阶段的规格（「你来定」部分）
2. CC 先进 plan mode 出计划；你对照验收标准看，再放行
3. **CC 先写测试，你审测试。**测试是可执行的规格，最值得花时间的一步
4. CC 实现到全绿
5. 你亲手验收（Inspector、Claude Desktop 里实际问）
6. git commit；CC 更新 HANDOFF.md；换阶段时 `/clear` 开新会话
7. 回来找我：带上 CC 的计划或总结、测试输出、截图、卡住的地方。我按「学会检查点」抽问

三个反模式：
- CC 为了让测试通过去改测试。每次看 diff 都专门看 tests/
- CC 自己编开放时间填进数据。它只能起草、标 draft，由你核验
- 接受你讲不清的代码。面试会逐行追问，讲不清比没做还糟

CLAUDE.md 模板（第 0 阶段原样交给 CC）：

```markdown
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
```

## 4. 路线总览

| 阶段 | 做完能演示什么 | 做完可以如实写进简历的 | 时间 |
|---|---|---|---|
| 0 准备 | Claude Desktop 里能调 ping | — | 0.5 天 |
| 1 最薄通路 | 6 个景点；同名会追问；闭馆日答 CLOSED 并给来源；数据范围外答 UNKNOWN | 自建 Python MCP Server + SQLite 规则库，已接入 Claude Desktop 跑通工具调用 | 2–3 天 |
| 2 规则引擎 | 一座城约 20 个景点、7 类规则；整日行程校验和替换；只读 SQL；第一次基线评测 | 参数化工具与只读执行的模型生成 SQL；第一个真实数字 | 3–4 天 |
| 3 经验库 | Notion 攻略迁成 Markdown，按景点 / 城市检索 | Markdown 经验库 | 2 天 |
| 4 交通与多城市 | 官网抽取管线；四座城 60–80 个景点、跨城同名、末班车 | 模型抽取 + 人工抽检的数据管线（附抽取准确率）；多城市、交通规则 | 4–5 天 |
| 5 工作流层 | 同一任务两种跑法：提示词 SOP / 代码编排 | 代码编排的 workflow | 2–3 天 |
| 6 评测 | 50+ 题、多组对照、失败归因 | 全部评测数字 | 2–3 天 |
| 7 包装 | README、演示 GIF、简历条目 | — | 1–2 天 |

合计约 17–24 个工作日。**评测题从第 1 阶段起并行攒，不要等到第 6 阶段。**

**最低可交付：**做到第 2 阶段 + A0 / A3 / A6 三组评测，就已经有真实数字可写；后面都是加分项。

## 5. 各阶段

### 第 0 阶段：准备（半天）
**你来做**
- 装 uv（`brew install uv` 或官方安装脚本），`which uv` 记下绝对路径；`claude update`；Claude Desktop 更新到最新
- 建空目录 `travel-kb`，在里面启动 CC，贴第 0 阶段提示词（见聊天记录）
- 审 CC 的计划：SDK 用的是 2.x 的 MCPServer 吗？日志走 stderr 吗？给 Claude Desktop 的配置用的是绝对路径吗？
- 把 CC 给的 JSON 并进 `~/Library/Application Support/Claude/claude_desktop_config.json`，**完全退出**再打开 Claude Desktop，让 Claude 调一次 ping；连不上就看 `~/Library/Logs/Claude/` 里的 mcp 日志
- 为第 1 阶段选城市和 6 个景点：选笔记最全的一座。我倾向布达佩斯（城内同名、周一闭馆、每月循环都有）；换季规则先用假数据测，第 4 阶段加维也纳时补真实数据

**验收**
- `uv run pytest` 全绿；`uv run mcp dev src/travelkb/server.py` 打开 Inspector 能调 ping；Claude Desktop 里 travelkb 显示已连接、ping 成功

**学会检查点**
- Claude Desktop 启动时对你的 server 做了什么？
- print() 为什么会把连接搞坏？配置里 uv 为什么要写绝对路径？
- tools / resources / prompts 各由谁决定调用？

### 第 1 阶段：最薄通路（2–3 天）
**目标：**一座城、6 个景点，只做「固定周几闭馆」「有效期」两类规则；resolve_poi + is_open；接入 Claude Desktop；10 条金标准全过。

**你来定**
- 城市：布达佩斯（2026-09-30 定）。景点和来源：
  - 国会大厦 https://www.parliamentvisit.com（只能跟导览团进，国事活动临时取消 → UNKNOWN 的好案例）
  - 渔人堡 https://ticket.budavar.hu/en（**拆成两条**：收费的上层塔楼 / 下层露台）
  - 匈牙利国家美术馆 https://en.mng.hu
  - 布达佩斯美术馆（Szépművészeti）https://www.mfab.hu（和国家美术馆都能叫「美术馆」→ 城内同名金标准）
  - 沃伊达奇城堡 https://vajdahunyadcastle.com/（Aaron 确认为官方站；**拆成两条**：城堡庭院 / 室内博物馆）
  - 圣史蒂芬大教堂 https://bazilikabudapest.hu/
  - 拆分后共 8 条 poi 记录；「开放」对全天可进的露台 / 庭院意味着什么，写进规则语义
- 数据：上述景点的官方开放时间。**有效期只填官网公布的时间窗**（比如 2026-10 到 2027-03），窗外日期一律 UNKNOWN，不外推
- 10 条金标准（格式见第 7 节）：开馆日、闭馆日、窗外日期、城内同名、库外景点、带时间且晚于最后入场
- is_open **只收 poi_id、不收景点名**，逼模型先消歧
- 同名：多个候选就返回 AMBIGUOUS 加全部候选，不许自动挑第一个；带 city 能唯一确定才 MATCH

**交给 CC 的要点**
- YAML（第 7 节格式）→ build_db.py 编成 SQLite；运行时只读打开
- resolve：别名精确匹配，统一大小写、去变音符号（Szépművészeti 对上 szepmuveszeti）；不做「模糊匹配后自动选中」
- is_open：实现第 7 节规则语义的 0、1、3、4、5 步；返回里带代码算出的星期几（模型常把星期几算错）
- 返回值用 Pydantic 模型（SDK 据此自动生成 outputSchema 和 structuredContent）；参数错误抛 ToolError（`from mcp.server.mcpserver.exceptions import ToolError`），模型能看到并自己改
- 工具标 `ToolAnnotations(read_only_hint=True)`（`from mcp.types import ToolAnnotations`）
- 工具描述写清：什么时候调、日期格式、UNKNOWN 什么意思、下一步做什么。**工具描述就是给模型的提示词**
- 测试分两层：unit 用假数据测逻辑，golden 用真实数据跑你的 10 条；MCP 层用 `from mcp import Client` 的内存客户端测

**验收**
- pytest 全绿（含 10 条金标准）
- Inspector：「美术馆」+ Budapest → AMBIGUOUS 两个候选；闭馆日 → CLOSED 带 source_url；窗外日期 → UNKNOWN
- Claude Desktop 里问「下周一去布达佩斯美术馆」：模型先调 resolve_poi，拿到 AMBIGUOUS 后问你是哪一家。截图留给 README
- Claude Desktop 的 Project 指令里写一版最简 SOP（先 resolve 再 is_open；UNKNOWN 就说不确定），作为 A 版起点

**学会检查点**
- is_open 为什么只收 poi_id？Gemini 那段 `name LIKE ? + fetchone()` 错在哪？
- UNKNOWN 和 CLOSED 为什么不能合并？为什么绝不能默认 OPEN？
- 模型怎么知道该调哪个工具？
- structuredContent 比纯文本返回好在哪，对模型、对评测各有什么用？

### 第 2 阶段：规则引擎完整版 + 只读 SQL（3–4 天）
**目标：**7 类规则都能表达；第一座城补到约 20 个景点；check_day_plan、find_open_pois、query_kb、数据校验；题库攒到 30 题，跑第一次基线。

| 规则 | 你笔记里的例子（入库前回官网核对） | 表达方式 |
|---|---|---|
| 固定周几闭馆 | 珍宝馆周二、Szépművészeti 周一 | 基础规则 days |
| 分季节 | KHM 8 月周一开、9–5 月周一闭；上美景宫夏季延长 | 多条基础规则，各带有效期 |
| 每月循环 | 匈牙利国家美术馆每月最后一个周一闭 | 例外 + RRULE（`FREQ=MONTHLY;BYDAY=-1MO`） |
| 节假日 / 临时闭馆 | 平安夜、罢工 | 例外：单日或区间 |
| 最后入场 / 清场 | 维列特尼 17:40 | 基础规则 last_entry |
| 预约须提前到 | 最后的晚餐提前 30 分钟 | 景点属性 arrive_early_min |
| 永久停业 | — | 景点 status |

**你来定**
- 第 7 节的规则语义是项目的心脏：先读懂，改成你认同的版本，再交给 CC
- 数据过期策略：verified_at 超过多少天加 STALE 警告（建议 90 天）
- 录入、核验约 20 个景点，这是本阶段真正的大头
- 再写 15 条金标准，集中在边界：换季前后一天、每月最后一个周一及前后一周、例外日

**交给 CC 的要点**
- 引擎按第 7 节全部实现；同一天两条规则结论相反 → UNKNOWN，校验脚本同时报错
- validate_data.py：每条规则有 source_url 和 verified_at；逐日枚举有效期查冲突；列出别名撞车（每组撞车都要有对应金标准）；RRULE 能解析；时区合法；时间字段是字符串
- check_day_plan：闭馆、到早了、晚于最后入场、预约没提前到、站点时间重叠。**不算路上时间**，工具描述里写明
- query_kb（环境变量 `TRAVELKB_ENABLE_SQL=1` 才注册），多层防护：
  1. `sqlite3.connect("file:…?mode=ro", uri=True)` 只读打开（实测 DROP / UPDATE 报 attempt to write a readonly database）
  2. `PRAGMA query_only = ON`
  3. `set_authorizer` 只放行 SELECT / READ / FUNCTION（要支持递归 CTE 再加 RECURSIVE；实测 ATTACH、写 PRAGMA 被拒）。先执行第 2 步的 PRAGMA 再装 authorizer，装上之后 PRAGMA 也会被拒
  4. 一次一条语句（sqlite3 的 execute 本身就拒绝多条）
  5. `set_progress_handler` 超时中断（实测 0.5 秒打断无限递归的 CTE）
  6. 行数上限
  7. 另给 describe_schema，告诉模型有哪些表
  - 测试：上面每种攻击各一条
- 规则逻辑的单元测试用假数据，不依赖真实数据

**验收**
- 25 条金标准全过；validate_data 零报错；安全测试全过
- Claude Desktop：让它排某个周一的一日游 → check_day_plan 报出闭馆 → 模型用 find_open_pois 换掉 → 再验通过
- 题库 30 题，跑 A0（裸模型）和 A6（模型 + 联网搜索）；Notion 版还在就再跑 A1。拿到第一个基线数字

**学会检查点**
- 规则优先级和冲突怎么处理？为什么用有效期而不是「每年 6–8 月」？
- RRULE 怎么表达「每月最后一个周一」？
- 真正挡住 DROP 的是哪一层？其他几层各防什么？
- query_kb 为什么默认不注册？

### 第 3 阶段：经验库（2 天）
**目标：**Notion 攻略迁成本地 Markdown；search_notes；笔记作为 resources。

**你来定**
- 从 Notion 导出四篇（欧洲-维也纳 / 布拉格 / 布达佩斯 / 米兰篇），拆成一条笔记讲一件事；35 条「已知的坑」各一篇
- frontmatter：`id, city, poi_ids, category, tags, source, updated`；分类体系你定（交通 / 支付 / 治安 / 预约 / 餐饮 / 机位……）

**交给 CC 的要点**
- 导入脚本：Notion 导出 → 规范文件名和 frontmatter；校验 poi_ids 都存在
- SQLite FTS5，tokenizer 用 trigram：中文子串能搜，但少于 3 个字的查询词搜不到（实测「地铁」0 条），要退回 LIKE
- search_notes：返回片段、note_id、所属景点；可按 city / poi_id / category 过滤；默认 5 条
- resource 模板 `note://{id}`

**先不上向量库：**语料只有 MB 级，查的多是专名，关键词检索可解释、好调试。评测证明漏召回再加。

**学会检查点**
- 为什么不能指望模型自己读 resources，却能指望它调 search_notes？
- trigram 对中文的效果和限制？
- 出现什么证据你才加向量检索？

### 第 4 阶段：交通与多城市（3–4 天，大头是数据）
**目标：**扩到维也纳、布拉格、布达佩斯、米兰，60–80 个景点；跨城同名；末班 / 首班车。

**你来定**
- 路线只做你真踩过坑、答错代价高的：机场线、城际夜车、马尔彭萨那种半夜进城
- 跨城同名的候选（叫法自己核对）：「圣斯蒂芬大教堂」（维也纳、布达佩斯）、「国家美术馆」「国家博物馆」（布拉格、布达佩斯）
- 抽检方案：抽检比例（建议全部抽取结果先 100% 核对前 20 条，之后随机 20%）；抽取错误怎么分类（时间错 / 有效期错 / 漏规则 / 来源不是官网）
- 实时信息（罢工、临时停运）不做，工具描述和最终回答里明说

**交给 CC 的要点**
- 官网抽取管线 `scripts/extract_poi.py`：抓官网页面 → 模型按第 7 节格式抽成 YAML（`status: draft`，带 source_url、抓取日期、页面存档链接）→ validate_data 校验格式 → 等你核验后才改成正式。**抽取只产出草稿，判定永远只读核验过的数据**
- 记录抽取准确率（你抽检的结果 vs 模型抽取），作为评测的一部分
- 末班车本质上也是「带有效期的按星期规则 + 例外」：复用第 2 阶段的引擎，不另写一套
- 不给 city 时，resolve_poi 跨城返回候选
- 金标准扩到 40+

**学会检查点**
- 交通为什么能复用开放时间的引擎？复用的边界在哪？
- 景点从 20 个到 80 个，工具返回和模型行为会怎么变？
- 为什么模型可以做抽取，却不能直接做判定？抽取错了靠什么兜住？

### 第 5 阶段：工作流层（2–3 天）
**目标：**同一个任务两种跑法。
- **A 提示词版：**SOP 写成 MCP prompt（plan_trip、audit_itinerary），也放进 Claude Desktop 的 Project 指令。模型自己按 SOP 调工具
- **B 代码编排版：**你自己的 Python 编排器。LLM 输出结构化行程（JSON Schema）→ 代码用 MCP 客户端调 check_day_plan（这一步不经过模型，跳不过去）→ 问题清单喂回 LLM 修改 → 最多 3 轮 → 代码渲染最终行程和核验表。遇到 AMBIGUOUS 就在命令行问你

**你来定**
- SOP 原文自己写：它就是简历上的「agent spec」
- B 版的循环上限；UNKNOWN 的站点是保留加警告还是强制替换

**交给 CC 的要点**
- 编排器用 SDK 的 MCP 客户端连本地 server；LLM 调用用 `claude -p --output-format json --json-schema …`（走你的订阅），或 API
- 每一步写 JSONL trace（输入、工具调用、结果、耗时）：评测里算「跳过工具」的证据，也是可观测性的例子

**学会检查点**
- A、B 各是 agent 还是 workflow？为什么？
- B 属于 evaluator-optimizer 模式，但 evaluator 是确定性代码而不是 LLM，好处和代价是什么？
- 什么场景你会选 A？

### 第 6 阶段：评测（2–3 天）
见第 6 节。

### 第 7 阶段：包装（1–2 天）
- 定位：**行程核验**。演示用一份真实的小红书攻略或 AI 排的行程，跑出核验报告（闭馆、晚于最后入场、同名歧义、查不到的站，每条附官网来源）
- README：问题 → 架构图 → 工具接口 → 规则语义 → 安全模型 → 评测结果（带置信区间）→ 失败案例 → 局限（数据时效、覆盖范围、无实时信息）→ 怎么跑
- 演示 GIF：粘贴一份现成行程 → 核验报告；Claude Desktop 里同名追问、闭馆替换
- 公开仓库前检查：没有 key、没有个人信息，来源链接齐全
- 回来找我，按真实数字改简历

## 6. 评测设计

**题库**（`eval/questions.yaml`，50+ 题）

| 题型 | 题数 | 正确做法 |
|---|---|---|
| 普通开闭馆 | 8 | 给出开 / 闭 |
| 换季边界 | 6 | 看日期落在哪一季 |
| 每月循环 | 4 | 判断是不是那个周一 |
| 例外日 | 6 | 节假日 / 临时闭馆 |
| 最后入场 / 预约提前到 | 4 | 给出时间约束 |
| 同名（城内 / 跨城） | 8 | 先问是哪一个，或按上下文唯一确定并说明 |
| 库外 | 6 | 说不确定，不编 |
| 末班 / 首班车 | 4 | 给出时间 |
| 软经验 | 4 | 引用笔记 |
| 整日行程审核 | 4 | 找出全部硬错误 |

- 题型来自八月真踩过的坑（35 条是种子），**日期改到官网能核验的时间窗里**：过去日期的临时闭馆，官网多半已经查不到
- **金标准独立于知识库：**每题回官网单独核对，不许从 YAML 抄；核对时把页面存进 Wayback Machine（web.archive.org），记下存档链接
- 字段：`id, type, question, context.today, in_kb, gold（verdict + 关键事实）, gold_sources, gold_checked_at`

**对照组**（同一模型、同一批题）

| 组 | 配置 | 回答什么问题 |
|---|---|---|
| A0 | 裸模型，无工具 | 基线 |
| A1 | Notion MCP + v1 SOP（Notion 版还在才跑） | v1 到底做到多少 |
| A2 | 只有 query_kb + SOP | 让模型自己写 SQL 行不行 |
| A3 | 窄接口 + SOP（提示词版） | 主方案 |
| A4 | 窄接口，不给 SOP | SOP 本身贡献多少 |
| A5 | 代码编排（B 版） | 把流程写进代码值多少 |
| A6 | 模型 + 联网搜索，不给本项目工具 | 直接让模型全网搜行不行 |
| A7（可选） | 圆周旅迹等现成产品，人工逐题问 | 成熟产品在这些题上表现如何 |

时间紧就先做 A0、A3、A6、A5。A7 无法自动化、模型不同，只做描述性对比，不进统计检验。

**指标**
- 答对率；**答错率**（给了确定答案但错了）是主指标，直接度量「答错比答不上来代价更高」；弃答率拆成「该弃的弃了」和「不该弃也弃了」
- 工具合规率（有工具的组）：下结论前有没有调 resolve / is_open / check_day_plan
- 可选：每题 token、耗时

**判分：**要求回答末尾输出一行 `VERDICT: OPEN|CLOSED|UNKNOWN|AMBIGUOUS`（行程题输出核验表），规则判分；自由文本题用 LLM 判分，人工复核全部分歧加随机 20%，报一致率（同 VLM 项目抽 44 条）。

**统计：**配对设计，「答错」用 McNemar 精确检验；比例配 Wilson 95% 区间。50 题只能检出很大的差异，报告里写明样本量的限制。

**预注册：**跑之前把假设和主指标写进 `eval/PREREG.md` 并 commit（git 时间戳就是证据）。建议：
- H1：A3 答错率低于 A0
- H2：换季 / 每月 / 例外三类题上，A2 答错率高于 A3（模型自己写的日期 SQL 会错）
- H3：A4 工具合规率低于 A3
- H4：A5 工具合规率 100%，答错率不高于 A3
- H5：换季 / 每月 / 例外 / 同名四类题上，A6 答错率高于 A3（搜得到资料，但日期推算和消歧仍交给模型）

**失败归因：**每道错题归一类：数据本身错 / 引擎 bug / 没调工具 / 调了没照结果说 / 消歧错 / 日期换算错。数据错也算系统答错，这正是真实风险。

**跑法：**`claude -p` 逐题跑，每组一份 MCP 配置和系统提示文件：
- `--strict-mcp-config --mcp-config <组>.json`：只加载本组的 server
- `--tools ""`：关掉内置工具（不影响 MCP 工具）
- `--system-prompt-file <组>.md`：替换 Claude Code 默认的编程助手提示词
- `--allowedTools`：放行本组的 MCP 工具
- `--output-format stream-json --verbose`：拿到完整轨迹，算工具合规率
- `--no-session-persistence --model <固定> --max-turns <上限>`
- 隔离：`--bare` 最干净（不读 CLAUDE.md、hooks、自动发现的 MCP），但不用订阅登录，要 `ANTHROPIC_API_KEY`。用订阅就不加 `--bare`、在空目录跑，并用输出里的 `system/init`（model、tools、mcp_servers）确认本组只加载了该加载的东西；注意非 bare 模式下 `~/.claude/CLAUDE.md` 仍会加载
- 另在 Claude Desktop 人工跑 10 题 A3，确认结论能迁移到真实使用场景
- 参数以 `claude --help` 和官方文档为准，让 CC 先查再写

## 7. 数据格式与规则语义（示意，数值全是编的）

```yaml
# data/pois/demo-museum.yaml
id: demo-museum
city: Budapest
country: HU
tz: Europe/Budapest
category: museum
status: OPEN                 # OPEN / TEMP_CLOSED / PERMANENTLY_CLOSED
names: {local: Példa Múzeum, en: Demo Museum, zh: 示例博物馆}
aliases: [示例馆, 美术馆]      # 「美术馆」与另一家撞车 → 必须有同名金标准
booking: {required: true, arrive_early_min: 30}
rules:                       # 基础规则：有效期 × 星期 × 时段
  - id: r1
    valid: [2026-10-01, 2027-03-31]
    days: [TUE, WED, THU, FRI, SAT, SUN]
    open: "10:00"            # 必须加引号
    close: "18:00"
    last_entry: "17:00"
  - id: r2
    valid: [2026-10-01, 2027-03-31]
    days: [MON]
    closed: true
exceptions:                  # 优先级高于基础规则
  - id: e1
    date: 2026-12-24
    closed: true
    reason: 平安夜闭馆
  - id: e2
    rrule: "FREQ=MONTHLY;BYDAY=-1SU"
    valid: [2026-10-01, 2027-03-31]
    close: "14:00"
    reason: 每月最后一个周日提前闭馆
source_url: https://example.org/hours
verified_at: 2026-10-02
```

规则语义（你审定后交给 CC）：

```
is_open(poi, date, time=None):
  0  poi.status == PERMANENTLY_CLOSED             → CLOSED
  1  没有任何基础规则的有效期覆盖 date              → UNKNOWN「数据未覆盖该日期」
  2  命中例外（单日 / 区间 / rrule）：
       多条且结论矛盾                              → UNKNOWN「数据冲突」
       否则                                        → 用例外的结论
  3  否则取当天星期对应的基础规则：
       多条且结论矛盾                              → UNKNOWN「数据冲突」
       有 open/close                              → OPEN（附时段、最后入场）
       closed                                      → CLOSED
  4  给了 time：判断能否入场（open ≤ time ≤ last_entry；预约类再提前 arrive_early_min）
  5  verified_at 超过 N 天：结论不变，加 STALE 警告
  所有结论带 rule_id、source_url、verified_at、代码算出的星期几
```

电路类比：基础规则是默认时序，例外是高优先级中断；有效期像校准证书的有效期，过期的读数不可信；UNKNOWN 是 X 态。

金标准（`tests/golden/cases.yaml`）：

```yaml
- id: g001
  type: weekly_closed
  call: {tool: is_open, args: {poi_id: demo-museum, date: 2026-10-05}}
  expect: {status: CLOSED, weekday: MON}
  source_url: https://example.org/hours
  checked_at: 2026-10-02
```

## 8. 明确不做
- 实时数据（Google Places、罢工、临时停运）：成本、条款和确定性都有问题；回答里明说「不含实时信息」
- 运行时联网搜索来下结论：搜索只用在数据采集层（第 4 阶段抽取管线，产出草稿待核验），判定只读核验过的数据
- 又一个行程规划器：规划交给模型和现成产品，本项目只做核验
- 向量库：除非评测证明关键词检索漏召回
- Web 前端、多 Agent、远程部署（HTTP transport）：和要验证的论点无关；完整版做完有余力再说

## 9. 面试必问（做到哪阶段，准备到哪阶段）
- MCP 三原语和控制权；stdio 为什么不能 print；2026-07-28 版为什么改成无状态
- MCP 和 Function Calling 的关系
- 同名怎么处理，为什么不自动选第一个；is_open 为什么只收 poi_id
- UNKNOWN 的语义、有效期、数据过期
- 规则优先级、冲突检测、RRULE
- 模型生成 SQL 的每层防护各防什么
- workflow 和 agent 的区别；A、B 两版的评测差异说明了什么
- 金标准怎么保证独立；为什么主指标是答错率；样本量够不够
- 工具描述怎么写；工具多了模型会怎样
- （产品岗）数据维护成本：个人工具靠手工核验；做成产品就要接官方 / 商家数据源、众包加校验、时效监控

## 10. 做完之后
仓库链接和评测结果表发来，按真实数字改简历。条目模板（跑完填数，没跑出来的不写）：
- 技术岗：自建 Python MCP Server（SDK 2.x）+ SQLite 规则库，覆盖 x 城 y 个景点、7 类开放规则；窄接口工具与只读执行的模型生成 SQL 做对照；z 道官网核验的真题上，答错率由 a%（裸模型）降至 b%，代码编排版工具合规率 100%……
- 产品岗：定位「答错比答不上来代价更高」的时效与同名问题，把产品做成「行程核验」而不是又一个规划器 → 模型抽取官网规则 + 人工抽检（抽取准确率 c%）、判定下沉为代码、查不到就说不确定 → 真题评测答错率 a%（裸模型）/ d%（模型 + 联网搜索）→ b%……

## 参考
- MCP Python SDK 文档（2.x）：https://py.sdk.modelcontextprotocol.io/
  - 接入宿主：https://py.sdk.modelcontextprotocol.io/get-started/real-host/
  - 测试：https://py.sdk.modelcontextprotocol.io/get-started/testing/
  - 结构化输出：https://py.sdk.modelcontextprotocol.io/servers/structured-output/
  - 工具与注解：https://py.sdk.modelcontextprotocol.io/servers/tools/
  - 错误处理：https://py.sdk.modelcontextprotocol.io/servers/handling-errors/
  - v1 → v2 迁移：https://py.sdk.modelcontextprotocol.io/migration/
- PyPI mcp：https://pypi.org/project/mcp/
- 2026-07-28 版规范：https://blog.modelcontextprotocol.io/posts/2026-07-28/
- Claude Code MCP：https://code.claude.com/docs/en/mcp
- Claude Code CLI 参数：https://code.claude.com/docs/en/cli-reference
- Claude Code 非交互模式：https://code.claude.com/docs/en/headless
- Anthropic, Building effective agents：https://www.anthropic.com/engineering/building-effective-agents
- Anthropic, Writing effective tools for agents：https://www.anthropic.com/engineering/writing-tools-for-agents