# 2d 评测设计（待 Aaron 审）

目标：拿到第一个真实数字——同一批题、同一个模型，比较「裸模型」「模型 + 联网搜索」「模型 + 本项目工具」答错多少。
设计原则照 ROADMAP 第 6 节；细节按 Claude Code CLI 文档（code.claude.com/docs/en/cli-reference、/headless）核对过，
并对照 Anthropic 的评测健康清单（eval-audit）自查过，下面标「清单」的地方是它要求的。

## 1. 这次评测回答什么

主指标是**答错率**：给了确定答案（OPEN / CLOSED）但错了，或者该追问、该说不知道的时候给了确定答案。
答错比答不上来代价高，所以不用「答对率」当主指标——一个全答 UNKNOWN 的系统答对率是 0 但答错率也是 0，要分开看。

第一次只跑三组（其余组等各自的前置条件）：

| 组 | 配置 | 回答什么问题 | 前置 |
|---|---|---|---|
| A0 | 裸模型：没工具、没搜索 | 基线：模型凭记忆答得怎样 | 无 |
| A6 | 模型 + 联网搜索（Claude Code 内置 WebSearch / WebFetch） | 「直接让模型全网搜不就行了」 | 无 |
| A3 | 模型 + travelkb 四个工具 + SOP | 主方案 | Aaron 的 SOP 存成 eval/groups/A3/system.md |
| A4 | 同 A3，不给 SOP | SOP 本身贡献多少 | 顺手就能跑，建议一起 |
| A2 | 只有 query_kb | 让模型自己写 SQL 行不行 | 2e 做完 |
| A5 | 代码编排（B 版） | 流程写进代码值多少 | 第 5 阶段 |

## 2. 题库 `eval/questions.yaml`

每题的字段：

```yaml
- id: q01
  type: weekly_closed            # 题型，也是报告里的分组键
  question: 10 月 12 日想去布达佩斯美术馆，开门吗？
  today: 2026-10-10              # 注入给模型的「今天」（布达佩斯当地），「下周一」这类说法才可判定
  gold:
    verdict: CLOSED              # OPEN / CLOSED / UNKNOWN / AMBIGUOUS
    facts: 周一闭馆               # 关键事实，一句话，供人工复核
  in_kb: true                    # 库里有没有这个景点（库外题 false）
  expected_tools: [resolve_poi, is_open]   # 有工具的组，下结论前至少该调过这些（算合规率用）
  gold_sources: [https://www.mfab.hu]
  gold_archive: null             # Wayback Machine 存档链接（web.archive.org）
  gold_checked_at: 2026-10-10
```

**gold.verdict 只有四个值**，和模型要输出的 VERDICT 一致：

| gold | 含义 | 哪些题 |
|---|---|---|
| OPEN / CLOSED | 能确定 | 普通开闭馆、换季、例外日、最后入场 |
| UNKNOWN | 不该给确定答案 | 库外景点、超出核验窗口的日期、官网没写的时段（渔人堡 20:30） |
| AMBIGUOUS | 该先问是哪一个 | 城内同名 |

**题型配比（30 题，第 2 阶段的数据能支撑的部分；末班车、软经验留到后面阶段）：**

| 题型 | 题数 | 备注 |
|---|---|---|
| 普通开闭馆 | 6 | 开、闭都要有（清单：要「两个方向」都覆盖，否则「永远答 UNKNOWN」会看起来很稳） |
| 换季边界 | 4 | 国会大厦 10/31 vs 11/1；2c 新景点补 |
| 每月循环 | 2 | 要 2c 找到真实的每月闭馆景点，找不到就并入例外日 |
| 例外日 | 5 | 11/1、12/24–26、11/13 调整 |
| 最后入场 | 3 | 到得晚于最后入场；到得早于开门 |
| 城内同名 | 6 | 美术馆、渔人堡、沃伊达奇城堡、大教堂各至少 1 |
| 库外 / 窗外 | 4 | 盖勒特温泉、2027 年 1 月中旬 |

**三条硬规则：**
1. 金标准独立于 data/：每题回官网核对，不从 YAML 抄；存 Wayback 链接。10 条 golden 的题可以直接搬，但 gold_archive 要补。
2. 问法像真人：「下周一」「这周末」「晚上八点半」，不要把 poi_id 或日期格式喂给模型。日期用 today 钉死。
3. 每题只考一件事（清单：一题考多项能力时，错了说不清是哪项错）。整日行程题不进这次（它要 LLM 判分），第 6 阶段再加。

`eval/questions.yaml` 已建好：10 条 golden 搬成了 q01–q10（gold 照 cases.yaml，archive 待补），q11–q30 留了空位标好题型。

## 3. 跑法：`claude -p`

每题、每组起一个全新的 `claude -p` 进程，在**空的临时目录**里跑（清单：每次试验状态隔离），
系统提示整个替换掉（不要 Claude Code 默认的「编程助手」人设），流程结束后保存完整轨迹。

```bash
# A0：裸模型
claude -p "<question>" \
  --model <MODEL> \
  --system-prompt-file eval/groups/A0/system.md \
  --append-system-prompt "今天是 2026-10-10（布达佩斯当地日期）" \
  --tools "" --strict-mcp-config --disallowedTools "mcp__*" \
  --disable-slash-commands --no-session-persistence \
  --max-turns 6 --permission-prompts none \
  --output-format stream-json --verbose

# A6：联网搜索（只开这两个内置工具，并预先放行，否则无人应答的权限提示会被拒掉）
  ... --tools "WebSearch,WebFetch" --allowedTools "WebSearch,WebFetch" ...

# A3 / A4：本项目工具（只加载这一个 MCP server）
  ... --tools "" --mcp-config eval/groups/mcp.json --strict-mcp-config \
      --allowedTools "mcp__travelkb__resolve_poi,mcp__travelkb__is_open,mcp__travelkb__check_day_plan,mcp__travelkb__find_open_pois" ...
```

flag 都在 CLI 文档里核对过。几个要点：
- `--tools ""` 关掉内置工具，但**不影响 MCP 工具**（文档原话），所以 A0 还要加 `--disallowedTools "mcp__*"` 双保险。
- `--strict-mcp-config` 让它只认 `--mcp-config` 里的 server；A0 / A6 不给 `--mcp-config`，就一个都不加载。
- `--permission-prompts none`：没人在旁边点允许，会弹提示的一律拒绝，并告诉模型别重试。所以要用的工具必须在 `--allowedTools` 里。
- `--system-prompt-file` 替换整个系统提示，`--append-system-prompt` 再接一行「今天」——文档说两者可以同时用。
- `--max-turns 6`：正常流程 resolve → is_open → 回答用不到 6 轮；到上限算 harness 错误，不算答错。

**隔离怎么保证：** 不用 `--bare`（它不走订阅，要 API key；Aaron 定，见第 8 节）。非 bare 模式下 `~/.claude` 里的设置、`~/.claude/CLAUDE.md` 仍会加载，所以 runner 每次都检查第一条事件 `system/init`：
`model` 是不是指定的那个、`mcp_servers` 是不是只有 travelkb（A0 / A6 应为空）、`tools` 里有没有不该有的。
不符就把这次记成 harness 错误，不进结果。Aaron 跑之前把 `~/.claude/CLAUDE.md` 里和旅行有关的内容清掉或改名。

**轨迹：** 每次运行的 stream-json 原样存成 `eval/runs/<run_id>/<group>/<qid>_rep<k>.jsonl`。
最后一条 `result` 事件里有最终文本、`usage`、cost、耗时；中间的 `assistant` 事件里有 `tool_use` 块，工具名就在里面（MCP 工具叫 `mcp__travelkb__is_open`）。

## 4. 模型怎么作答：VERDICT 行

所有组的系统提示里都有这一段（内容完全相同，只规定输出格式，不规定策略）：

```
回答最后单独一行：VERDICT: OPEN | CLOSED | UNKNOWN | AMBIGUOUS
- OPEN / CLOSED：你确定那天（那个时刻）能 / 不能去
- UNKNOWN：你无法确定，包括：没有可靠信息、信息可能过期、问的时段没有依据
- AMBIGUOUS：有多个同名景点，需要先问清楚是哪一个
这一行只能出现一次，放在最后。
```

A3 的 SOP 另外加在 A3 的系统提示里（Aaron 写，就是 Desktop Project 指令那份）。A4 用和 A0 一样的最简提示 + 工具。

## 5. 判分：规则判分，不用 LLM

从最终文本里取**最后一行** `VERDICT:`。按 gold 和模型答案对照：

| gold \ 模型 | OPEN / CLOSED 且相同 | OPEN / CLOSED 且不同 | UNKNOWN | AMBIGUOUS |
|---|---|---|---|---|
| OPEN / CLOSED | 答对 | **答错** | 不该弃也弃了 | 不该弃也弃了 |
| UNKNOWN | **答错**（该说不知道却给了确定答案） | **答错** | 该弃的弃了 | 该弃的弃了（追问也算谨慎） |
| AMBIGUOUS | **答错**（自动挑了一个） | **答错** | 该弃的弃了（偏保守，但没答错） | 答对 |

**不是答错的几种情况，单独记，不进答错率**（清单：「没答」不等于「答错」，基础设施错误不能混进模型成绩）：
- `no_verdict`：没有 VERDICT 行或格式不对 → 记 no_verdict，报告里单列
- `harness_error`：进程非零退出、`result.is_error`、到 `--max-turns`、`system/init` 校验失败 → 写 `errors.jsonl`，不占结果行；限流类错误带抖动重试最多 2 次，重试次数记下来
- `refusal`：模型拒答 → 单独一类

**指标（每组）：**
- 答错率（主）、答对率、该弃的弃了 / 不该弃也弃了、no_verdict 数、harness 错误数
- 工具合规率（有工具的组）：下结论前，`expected_tools` 里的每个工具至少调过一次，且 resolve_poi 在 is_open 之前。
  这是诊断指标，不是主指标（清单：主指标应评结果不评路径）
- 每题：轮数、工具调用次数、输入 / 输出 token、cost、耗时（都从 `result` 事件读，不估算）

**统计：** 配对设计，每题在各组都跑。两组答错率之差用 McNemar 精确检验（只看「一组错另一组对」的题，二项检验，`math.comb` 就能算，不引新依赖）；每个比例配 Wilson 95% 区间。
30 题的噪声底线大约 ±18 个百分点（1/√n），跑 2 遍（R = 2）约 ±13；只能检出很大的差异。报告里写明。

## 6. 预注册 `eval/PREREG.md`

跑之前写好并 commit（git 时间戳就是证据）：主指标、各组配置、模型、题数、reps、假设：
- H1：A3 答错率低于 A0
- H5：换季 / 例外 / 同名三类题上，A6 答错率高于 A3（搜得到资料，但日期推算和消歧仍在模型手里）
- H3（如果跑 A4）：A4 工具合规率低于 A3

## 7. 文件和代码

```
eval/
  DESIGN.md            本文件
  PREREG.md            第一次跑之前写
  questions.yaml       题库（Aaron 填）
  groups/
    base.md            所有组共用的最简系统提示 + VERDICT 格式
    A3/system.md       base + Aaron 的 SOP
    mcp.json           travelkb 的 MCP 配置（绝对路径由 runner 生成）
  run.py               跑一组或全部：claude -p 子进程、保存轨迹、写 results.jsonl / errors.jsonl；可断点续跑（按 (题, 组, rep) 去重）
  score.py             读 results.jsonl 算指标、区间、检验，输出 summary.md
  runs/<run_id>/       轨迹和结果（建议进 git，30 题不大，而且是「跳过工具」这类结论的证据）
```

`run.py` 里调 `claude` 的那一层做成可替换的（传一个函数进去），测试用假的 runner 喂预先写好的 stream-json，
不花钱就能测：VERDICT 解析、判分矩阵的每一格、合规率提取、`system/init` 校验、Wilson、McNemar、
断点续跑；再加清单要求的两条「烟雾测试」：喂 gold 答案全对 → 答错率 0；喂空输出 → 全是 no_verdict 而不是答错。

## 8. 请 Aaron 定（括号是建议）

1. 第一次跑哪几组（A0、A3、A4、A6 一起；A3 / A4 的 harness 和 A0 一样，多跑只多花时间）
2. 模型（和 Desktop 里用的同一个，这样 A3 的数字能迁移到真实使用；在 Desktop 设置里看一眼是哪个，写进 PREREG）
3. reps（2；30 题 × 4 组 × 2 = 240 次运行，每次几秒到一分钟）
4. 订阅还是 API key（订阅、不加 `--bare`、靠 `system/init` 校验隔离；用 API key 就加 `--bare`，隔离更干净但要花钱）
5. 轨迹进不进 git（进）
6. `today` 怎么定（每题自己写，不统一；题里的日期都落在 2026-10-08 ~ 2027-01-06 核验窗口内）

定了之后：CC 先写 run.py / score.py 的测试给 Aaron 审 → 实现 → Aaron 填题库、写 PREREG → 先跑 3 题试一遍、读轨迹确认字段都在 → 全量。
