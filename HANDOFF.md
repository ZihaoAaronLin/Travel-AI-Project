# HANDOFF

## 2026-11-12（续三）· 四组试跑复盘

### 试跑（Aaron 本机，q01–q03，reps 1，四组共 12 次）
- **harness 全部验证通过**：0 次 harness 错误；system/init 里 A0 工具为空、A6 只有 WebSearch / WebFetch、A3 / A4 只有 travelkb 的 5 个工具且 status 为 connected；mcp.json 的 env 生效（server 起得来、日期钉住）；usage 的缓存字段名和 CC 的修正一致；没有任何 permission_denials
- 结果：A0、A6、A4 三题全对或该弃的弃了；**A3 在 q01、q02 答成 AMBIGUOUS（不该弃也弃了）**

### A3 退步的原因：CC 提议的 SOP 查询规则
- 轨迹：A4 传 query「布达佩斯美术馆」+ Budapest → MATCH → 答对；A3 传「美术馆」+ Budapest → AMBIGUOUS → 反问
- 「布达佩斯美术馆」是美术博物馆的正式中文名（data 里的 names.zh）。上一版 SOP 的例子写「query 只填景点名本身，严禁把城市名和景点名拼起来」，模型把它推广成了「名字里的城市一律删掉」
- 已改 docs/SOP.md 第 1 条：用户直接说出的名称原样传，即使带城市名；只有「城市 + 的 + 通称」才拆开。两个例子正反各一。eval/groups/A3/system.md 同步重新生成
- **没法在容器里验证**（这里不跑真的 claude）：要 Aaron 同步 Desktop 后，用 q01、q02、q03、q04 重跑 A3 / A4（新 run-id，q04 正是「布达佩斯的美术馆」的问法，金标准 AMBIGUOUS）

### 另外三条发现
1. **q03 本身有歧义**：「明年 1 月 12 日去圣史蒂芬大教堂的教堂大厅」没说城市，维也纳的 Stephansdom 中文也叫圣史蒂芬大教堂。A0、A6 都反问是哪座城市，合理。题目要写出布达佩斯（Aaron 改；金标准不变）
2. **A3、A4 在 q03 都自己挑了一个**：resolve_poi 返回 AMBIGUOUS（教堂 / 观景台与珍宝馆），模型按用户说的「教堂大厅」选了教堂。选得对，结论也对（UNKNOWN），但 A3 违反了 SOP 的「严禁自行挑选」
3. **根子在 resolve_poi 是精确匹配**：「圣史蒂芬大教堂的教堂大厅」「布达佩斯的美术馆」原样传进去都是 NOT_FOUND，全靠模型自己改写，SOP 只能缓解。提议（待 Aaron 定，先写测试）：resolve_poi 在 NOT_FOUND 时按「的」拆开、去掉开头的城市名再试一次，返回里标明用的是哪个说法。这样查询规则就能从 SOP 里拿掉，交给代码

### 其他改动
- run.py：git_dirty 不再把 eval/runs/ 算进去（试跑三次都显示 dirty，是因为上一轮的结果没提交）
- eval/questions.yaml：q11–q30 的空位题型按 DESIGN 配比重排。原来 7 个空位是普通开闭馆，试跑说明这类题裸模型就会，分不出组间差别；现在普通开闭馆共 6 道、同名共 6 道（q25–q29 + q04）

### 下一步
1. Aaron：Desktop Project 指令再同步一次 docs/SOP.md（只改了第 1 条第 2 点）
2. Aaron：git pull → `uv run python eval/run.py --model claude-opus-5-5 --run-id pilot2 --groups A3,A4 --only q01,q02,q03,q04 --reps 1` → score → 推上来
3. Aaron：定要不要做 resolve_poi 的「的 / 城市名」回退（要做的话 CC 先写测试）
4. Aaron：q03 补上城市；填 q11–q30 + Wayback；写 PREREG

## 2026-11-12（续二）· 红测试实现；SOP 定稿

### 做了什么
- Aaron 放行 16 条红测试 → 实现，tests/ 未改动，全部 286 条通过
  - server.py：TODAY_ENV、today_from_env、build_server(..., today=)；三个工具的「今天」都走同一个 today_for；钉住时往 stderr 打一条 warning；模块级 server 读 os.environ
  - 日期解析抽成 _iso_date，工具参数和环境变量共用（2026-02-30 这类写法对、日子不存在的也拒收）
  - evalkit/transcript.py：check_init 对每个 MCP server 检查 status 是不是 connected
- 容器里实测：按 run.py 生成的 mcp.json 起真实 server，is_open 不给日期 → 2026-10-10、warnings 为空；TRAVELKB_TODAY=2026-10-1 → 启动即报错退出
- SOP：Aaron 同意五条建议。定稿在 docs/SOP.md（Desktop Project 指令照抄这个文件）；eval/groups/A3/system.md = docs/SOP.md + 所有组共用的 VERDICT 段，DRAFT 标记已删
- 定稿时多查出一条：resolve_poi 的 city 只认英文名，city=「布达佩斯」→ NOT_FOUND。SOP 第 1 条写明「城市用英文名」

### 待 A3 / A4 试跑确认
- system/init 里 MCP server 已连接时 status 的字符串是不是 "connected"。不是的话每题都会被记成隔离失败，errors.jsonl 的 detail 会写出实际值
- claude 启动 MCP server 时，mcp.json 里的 env 是叠加在本机环境变量上，还是替换掉。若是替换，uv 可能找不到 HOME，server 起不来，status 会是 failed

### 下一步
1. Aaron：Desktop Project 指令换成 docs/SOP.md 全文
2. Aaron：git pull → A3 / A4 试跑 3 题（run-id 仍用 pilot）→ score → 把 eval/runs/pilot 提交推上来
3. CC：读试跑轨迹，核对 init 的 tools 列表、MCP status、usage 字段名；A3 有没有按 SOP 先 resolve 再 is_open
4. Aaron：填 q11–q30（难题为主）+ Wayback；写 PREREG；然后全量
5. 可选：加一条测试保证 A3/system.md 始终等于 docs/SOP.md + VERDICT 段，防止两边改一边忘一边

## 2026-11-12（续）· SOP 审查 + A0 / A6 试跑

### A0 / A6 试跑 3 题（Aaron 本机，claude-opus-5-5，reps 1）
- harness 通了：6 次运行全部出结果，0 次 harness 错误；完整模型 ID 和 system/init 对得上
- 两组都是 0 错：q01、q02 答对，q03（2027-01-12，窗外）两组都弃答 = 该弃的弃了
- 这三题是常识题（美术馆周一闭馆），裸模型本来就会。H1 能不能成立取决于难题：换季、例外日、最后入场、同名、收费时段外。q11–q30 要往这几类压
- 用量：A0 平均 21 s、1 轮；A6 平均 41 s、2.7 轮。按这个估，全量 240 次大约 2 小时；订阅下 total_cost_usd 只是估算，不扣钱，但占用量额度，撞上限就用同一条命令续跑
- **发现 score.py 的问题，已修：** 输入 token 只读了 input_tokens（A0 每题 2 个），没算走缓存的部分。改成 input_tokens + cache_creation_input_tokens + cache_read_input_tokens。后两个字段名按 API 文档写，**待 Aaron 推上试跑轨迹后核对**

### 更正上一轮 CC 的建议
- 上一轮建议 resolve_poi 的描述写「传用户原话，不要改写」，**这条是错的**：实测「布达佩斯的美术馆」原样传进去是 NOT_FOUND
- 实测结果：「布达佩斯的美术馆」→ NOT_FOUND；「布达佩斯美术馆」→ MATCH（只命中美术博物馆，没追问）；「美术馆」+ city=Budapest → AMBIGUOUS
- 正确的写法是「query 只填景点名，城市放 city 参数，不要把城市名和景点名拼成新名字」。代码侧也可以让 resolve_poi 自己去掉「<城市>的」前缀，放到 2c 再议

### SOP 审查（Aaron 的 Project 指令）
已放进 eval/groups/A3/system.md，后面接所有组相同的 VERDICT 段；**DRAFT 标记保留**，Aaron 确认后删。A3 和 A4 的差别就是「SOP」对「一行通用人设」。

三处与工具实际字段不符，已改（不改的话模型会去找不存在的字段）：
1. 候选列表「含名称、城市、说明」→「含名称、城市、类别」：resolve_poi 的候选没有「说明」字段，模型会自己编
2. `close_time` / `last_entry_time` → `close` / `last_entry`：is_open 返回的字段叫这两个
3. 第 5 条「遇 NOT_FOUND 或 UNKNOWN」：resolve_poi 不会返回 UNKNOWN，UNKNOWN 来自 check_day_plan → 改成「遇 NOT_FOUND 或后面 check_day_plan 报出的 UNKNOWN」

建议改、但没动（改变行为，等 Aaron 定）：
1. **第 5 条「直至 issues 清零」做不到。** check_day_plan 里只要有一站无法核验（UNKNOWN），ok 就永远是 false；WARNING 也算 issues。照字面执行，模型要么把用户想去的站删掉，要么一直调到轮数用完。建议：「改到没有 BLOCKER 为止；WARNING 转告用户；UNKNOWN 的站点标『未核验，请以官网为准』，不要为了清零删掉」
2. **第 1 条加 query 的写法**（对应 Desktop 观察 2）：「query 只填景点名，城市放 city 参数；不要把城市名和景点名拼成新名字（『布达佩斯的美术馆』→ query『美术馆』+ city『Budapest』）」
3. **第 2 条让代码比时刻：**「用户给了到达时刻，就作为 time 传给 is_open」。现在的写法让模型自己拿到达时间和 last_entry 比，这正是本项目要交给代码的事
4. 第 5 条补 find_open_pois：「闭馆的站点用 find_open_pois 找当天开放的替代」
5. 补 warnings 和 next_open_date：「warnings 里的提醒要转告；CLOSED 且有 next_open_date 就告诉用户哪天能去」（2a 时 Aaron 要的「例外之后给建议」）

定稿后 Desktop 的 Project 指令要换成同一份，A3 的数字才代表真实使用。

### 下一步
1. Aaron：审 16 条红测试（TRAVELKB_TODAY、check_init 看 status，上一节）
2. Aaron：SOP 五条建议逐条定；Desktop Project 指令同步
3. Aaron：把 eval/runs/pilot 提交推上来，CC 核对 init 的 tools 列表和 usage 字段名
4. CC：红测试放行后实现；删 DRAFT 标记；A3 / A4 试跑 3 题
5. Aaron：填 q11–q30（难题为主，含一道「布达佩斯的美术馆」问法）+ Wayback；写 PREREG；然后全量

## 2026-11-12 · 2d harness 实现；第 1 阶段 Desktop 验收通过

### 第 1 阶段 Desktop 验收（Aaron，截图）
- 通过：在 Project（带 SOP）里问美术馆 → resolve_poi 拿到 AMBIGUOUS → 先问是哪一家 → is_open、find_open_pois → 带来源的表格
- 两条观察（已记进 ROADMAP 第 1 阶段，算 H3 的先期证据）：
  1. 不建 Project 的普通对话：第一句不明说「用 travel-kb」，模型就不调工具
  2. 不建 Project：「布达佩斯**的**美术馆」被模型改写成「布达佩斯美术馆」再查 → MATCH，跳过了追问；同一句在 Project 里会先问。改写发生在模型这一侧，resolve_poi 收到的已经不是原话，代码拦不住
- 建议（没做，等 Aaron 定）：resolve_poi 的 query 参数描述加一句「传用户原话，不要改写或补全」；q11–q30 的同名题里放一道「布达佩斯的美术馆」这种问法

### 2d harness 实现（Aaron 放行 tests/evalkit 之后）
- src/travelkb/evalkit/：questions、groups、transcript、scoring、runner 五个模块；tests/evalkit 的 81 条没改动、全过。实现时 VERDICT 正则漏了「值两边带反引号」一格，被测试抓住
- eval/run.py、eval/score.py：薄命令行入口，逻辑都在 evalkit 里，没有单独的单元测试。用一个假的 claude（按参数吐 stream-json）端到端跑过：选题、断点续跑（第二次 0 次调用）、模型写别名 → 隔离失败进 errors.jsonl、score 出 summary.md
- eval/groups/base.md：所有组共用的最简提示 + VERDICT 格式（DESIGN 第 4 节原文）
- eval/groups/A3/system.md：**草稿**，第一行是 DRAFT 标记，run.py 见到标记拒跑 A3。Aaron 把「使用 travel-kb 的规则」换成 Project 指令原文，再删掉第一行
- run.py 每次启动往 runs/<run_id>/meta.jsonl 记一行：commit、有没有未提交改动、claude 版本、一条样例命令。PREREG 和结果靠它对上
- 有工具的组按 today 分批，每个 today 生成 eval/groups/mcp-<日期>.json（本机绝对路径，已 gitignore）。容器里从空目录用这条命令起 server、列出 5 个工具，确认能起
- 本机 claude CLI 认得 harness 用的全部 flag（--system-prompt-file、--max-turns 不在 --help 里，但解析器接受）
- 全部 270 条测试通过（不含下面新增的红测试）

### 实现时发现两个会让 A3 / A4 结果失真的漏洞 → 新增红测试（等 Aaron 审）
1. **server 的「今天」用真实时钟。** 题目按「今天是 2026-10-10」出，数据 10-08 核验；在 11 月跑评测，server 每次都带 STALE 提醒（核验后 35 天以上），不给日期时还会查成真实的今天。A3 / A4 的弃答里就混进了「跑评测那天数据已过期」，和题目无关
   - 提议：环境变量 TRAVELKB_TODAY=YYYY-MM-DD 钉住 server 的今天。三个工具的缺省日期和过期判断都用它；它就是景点当地日期，不再按时区换算；格式不对启动即报错，不悄悄退回真实时钟
   - 为什么用环境变量不用工具参数：「今天」和「过期没有」不能交给模型决定。只在评测的 mcp.json 里设；Desktop 配置里不设，行为和现在完全一样
   - 测试：tests/unit/test_tools_pinned_today.py（14 条）+ tests/test_server.py 末尾 1 条（模块级 server 真的读了环境变量）
   - run.py 已按这个接口写好 mcp.json 的 env；server 没实现之前，run.py 拒跑 A3 / A4
2. **MCP server 起不来也会被当成隔离通过。** check_init 只看 server 名字；travelkb 启动失败时 init 里照样有它，只是 status 不是 connected → A3 实际没工具，答案却记在 A3 名下
   - 测试：tests/evalkit/test_transcript.py 末尾 1 条（status 为 failed 必须报问题）
- 现在 `uv run pytest` 会在收集阶段就停：新测试 import 了还不存在的 TODAY_ENV。看其余测试：`uv run pytest --ignore=tests/unit/test_tools_pinned_today.py`（270 过、2 红）

### 和 DESIGN.md 不一致的地方（都是小事）
- 轨迹路径多一层：runs/<run_id>/<组>/traces/<题>_rep<k>.jsonl
- DESIGN 第 5 节的 refusal（模型拒答）没单列：拒答没有 VERDICT 行，记成 no_verdict，不进答错率；要区分得读轨迹
- 配对检验按 (题, rep) 配对：同一题的两个 rep 不独立，p 值偏乐观；summary.md 里写明了
- 待试跑确认：--model 传别名（opus）时 system/init 报的很可能是完整 ID，字符串对不上就全部记成隔离失败。所以 --model 一律写完整 ID

### Aaron 试跑 3 题（A0 / A6 现在就能跑，不用等上面两条）
```bash
git pull && uv sync
# ~/.claude/CLAUDE.md 里和旅行有关的内容先清掉或改名（非 bare 模式会加载它）
uv run python eval/run.py --model <Desktop 里用的完整模型 ID> --run-id pilot --groups A0,A6 --only q01,q02,q03 --reps 1
uv run python eval/score.py --run-id pilot
```
- 读 eval/runs/pilot/A0/traces/q01_rep0.jsonl：第一行 system/init 有没有 model、tools、mcp_servers；最后一行 result 有没有 total_cost_usd、num_turns、usage、duration_ms。字段名不对就告诉 CC
- errors.jsonl 有内容先看 detail 那一栏

### 下一步
1. Aaron：审新增的 16 条红测试（重点：用环境变量钉今天合不合适；格式错就启动失败合不合适）
2. Aaron：A0 / A6 试跑 3 题，回报字段
3. CC：红测试放行后实现（server 钉住今天 + check_init 看 status），之后 A3 / A4 才能试跑
4. Aaron：A3 的 SOP 原文；填 q11–q30 + Wayback 存档；写 eval/PREREG.md（模型、组、reps、H1 / H3 / H5、主指标答错率）
5. 在跑的：Desktop 第 2 阶段验收；2c 新景点
6. 2e：query_kb + build_db（最后做）

### 已知问题
- 真实数据 10-08 核验，今天 11-12：Desktop 里每个回答都带 STALE 提醒。这是设计（14 天阈值），不是 bug；要消掉得回官网重新核验、更新 verified_at
- 同名撞车 4 组的金标准仍只有「美术馆」一组（2c 补）

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

### 2a 已实现（Aaron 放行后；tests/ 只按 Aaron 同意改了一个测试名）
- 全部 159 条测试通过；真实数据 validate_data 仍是 error 0、warning 0
- models.py：DayException 三选一（date / dates / rrule + valid），rrule 只收规则本身（带冒号或换行一律拒收，防 DTSTART 覆盖起点）；covers(day) / days() 两个方法，引擎和校验共用，三种写法不会各走各的逻辑
- hours.py：is_open(..., as_of=None)；OpenResult 新增 next_open_date、warnings；STALE_AFTER_DAYS = 14
- validate.py：区间 / rrule 覆盖的每一天都要在规则有效期内；不同写法撞同一天且结论不同 → 每组报第一天
- server.py：「今天」只取一次，既当缺省日期又当 as_of；输出 next_open_date、warnings
- ROADMAP 第 7 节：第 2 步改成三选一；新增第 5 步（建议与提醒）；YAML 示例补 dates 写法、修了原示例里只写 close 没写 open 的错；第 5 阶段记下 Aaron 的「自动排时间表」想法（之后再做）
- 真实数据演示：农业博物馆 2026-12-24（例外闭馆）→ next_open_date 2026-12-27

### 2b 已实现（Aaron 放行；新增 10 分钟缓冲要求 → 加了一条测试，其余 tests/ 未动）
- 全部 189 条测试通过；真实数据 validate_data 仍是 error 0、warning 0
- core/plan.py：check_day_plan（Stop / PlanIssue / StopVerdict / DayPlanReport）、find_open_pois（OpenHit / FindOpenResult）
  - 两站衔接：到达早于上一站离开 → BLOCKER OVERLAP；没重叠但不足 10 分钟 → WARNING TIGHT_TRANSFER（TRANSFER_BUFFER = 10 分钟）；建议都是「上一站离开 + 10 分钟后到达」
  - 实现时踩的坑：is_open 结论为 OPEN 时 reason_code 也是 WEEKLY_RULE（说明依据），判「整天闭馆」必须先看 status；写错后 7 条测试立刻红了——测试抓住了
- server.py：工具 check_day_plan（stops: [{poi_id, arrive, leave?}], date?）、find_open_pois（city, date?, time?, category?）；不给日期用第一站 / 该城市景点当地的今天；坏输入一律 ToolError
- 容器里按 Claude Desktop 方式（真实 stdio、真实数据）跑通 ROADMAP 的第 2 阶段验收场景：
  周一（2026-10-12）布达佩斯美术馆 10:00 + 大教堂 12:35 + 渔人堡 20:00
  → I1 BLOCKER CLOSED_DAY（改到 10-13 或换）、I2 WARNING TIGHT_TRANSFER（只留 5 分钟）、I3 UNKNOWN UNVERIFIED（收费时段外）
  → find_open_pois 周一 10:00：6 个开放、2 个 unverified → 换掉第一站、拉开间隔、渔人堡改 15:00 → ok=True
- ROADMAP 2b 行、check_day_plan 要点已补 10 分钟缓冲

### Desktop 验收脚本（第 2 阶段）
1. git pull；⌘Q 完全退出再打开 Claude Desktop（新工具要重启才加载）；工具菜单里 travelkb 应有 5 个工具
2. 在 travel-kb Project 里问：「10 月 12 日（周一）在布达佩斯排一天：上午美术馆，中午圣史蒂芬大教堂，晚上 8 点渔人堡」
3. 看模型会不会：先 resolve_poi 逐站消歧（美术馆、渔人堡都会 AMBIGUOUS，要追问）→ check_day_plan → 把 BLOCKER 换掉（find_open_pois）→ 再调一次 check_day_plan → 最终回答带 source_url，渔人堡那站说「未核验」
4. 截图；没按预期走的地方记下来（跳过工具 / 没照结果说 / 把 UNKNOWN 当成开放）

### 2d 评测设计（待 Aaron 审）
- eval/DESIGN.md：三组起步（A0 裸模型、A6 联网搜索、A3 本项目工具 + SOP；A4 顺手）；题库格式；`claude -p` 的完整命令（flag 按 CLI 文档核对：`--tools ""` 不影响 MCP 工具，所以 A0 要再加 `--disallowedTools "mcp__*"`；`--permission-prompts none` 下要用的工具必须预先 `--allowedTools`）；VERDICT 行格式；规则判分矩阵（答错 / 答对 / 该弃的弃了 / 不该弃也弃了 / no_verdict / harness_error 分开记）；McNemar + Wilson；预注册
- eval/questions.yaml：q01–q10 从 golden 搬入（gold_archive 待补），q11–q30 按题型留空
- 对照了 Anthropic 的评测健康清单：状态隔离（每次空目录新进程）、基础设施错误不混进模型成绩、「没答」≠「答错」、两个方向都覆盖、每题只考一件事、轨迹全存、烟雾测试（gold 全对 / 空输出全 no_verdict）
- 待 Aaron 定 6 件事（DESIGN.md 第 8 节）：跑哪几组、模型、reps、订阅还是 API key、轨迹进不进 git、today 的定法

### 2d 设计定稿（Aaron 2026-10-20 全部按建议）
- 第一次跑 A0 / A3 / A4 / A6；模型用 Desktop 同款（Aaron 去设置里看，写进 PREREG）；reps = 2；走订阅不加 --bare，靠 system/init 校验隔离；轨迹进 git；today 每题自写

### 2d harness 测试（红，等 Aaron 审）
- 布局：逻辑在 src/travelkb/evalkit/（可导入、可测），eval/run.py、eval/score.py 只是薄的命令行入口
- tests/evalkit/（全部用假的 claude 轨迹，一分钱不花）：
  - test_questions：题库格式——question 为 null 的空位跳过、id 不重复、gold.verdict 四选一、today 必填
  - test_command：每组的 `claude -p` 命令钉死——A0 `--tools ""` + `--disallowedTools mcp__*` + `--strict-mcp-config`；A6 `--tools/--allowedTools WebSearch,WebFetch`；A3/A4 `--mcp-config` + 四个 `mcp__travelkb__*` 放行；A3 用 SOP、A4 用 base 提示；公共 flag（模型、今天、stream-json、--permission-prompts none、--max-turns 6 …）
  - test_transcript：VERDICT 取最后一次出现、容忍加粗 / 反引号 / 大小写、非法值算 None；工具调用顺序（去 mcp__travelkb__ 前缀）；result 的 usage / cost / 轮数；错误分类（result_error / max_turns / no_result / no_init）；空回答是 no_verdict 不是错误；system/init 校验（模型、MCP server、每组禁止出现的工具；EndConversation 这类不算）
  - test_scoring：判分矩阵 4×4 每格 + None；工具合规（顺序也要对；无工具组为 None）；Wilson（3/10 → 0.108–0.603）；McNemar 精确（8:0 → 2/256）；配对不一致计数；汇总（答错率分母是全部有结果的行）
  - test_runner：每题一行 + 轨迹文件；每次新建空目录；reps 分行；crash → errors.jsonl；限流重试最多 3 次且每次留痕；隔离失败 / max_turns 是 harness 错误；断点续跑（跳过已有结果、重跑只出过错的）；烟雾测试：oracle 答错率 0、空输出全 no_verdict、常数 OPEN 基线全错
- 测试定下的接口：evalkit.questions.load_questions / Question；evalkit.groups.GROUPS / GroupConfig / build_command；evalkit.transcript.parse_transcript / extract_verdict / check_init；evalkit.scoring.classify / tool_compliant / wilson / mcnemar_exact / paired_discordant / summarize；evalkit.runner.run_group / Invocation
- 待实测确认：stream-json 的字段名（result 事件的 total_cost_usd / duration_ms / num_turns / subtype）按文档写，Aaron 跑 3 题试验时对一遍；解析器用 .get，缺字段不会崩

### 下一步
1. Aaron：审 tests/evalkit/（重点：判分矩阵、合规定义、哪些算 harness 错误）；第 1、2 阶段 Desktop 验收结果；2c 新景点
2. CC：设计定稿后写 run.py / score.py 的测试（假 runner，不花钱）给 Aaron 审 → 实现
3. Aaron：填 q11–q30 + Wayback 存档；写 eval/PREREG.md；先跑 3 题读轨迹，再全量
3. SOP（Project 指令）要加一段 check_day_plan 的用法：排整天行程时先 resolve 每站，再 check_day_plan，按 issues 逐条改，改完再验

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
