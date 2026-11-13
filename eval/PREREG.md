# 预注册：第 2 阶段基线评测

**状态：草稿，未冻结。** 方法部分 Aaron 2026-11-13 已全部定下（都按 CC 的建议）；题库填满、分析代码就绪之后，
把这一行改成「已冻结」并 commit。
那个 commit 就是冻结点：git 的时间戳证明下面这些是跑之前定的，不是看了结果才挑的。

## 1. 要回答的问题

给模型配上 travel-kb 的工具和 SOP，它在「景点某天某刻能不能去」这类问题上答错得更少吗？
和两个现成做法比：什么都不给（A0）、让模型自己联网搜（A6）。另外看 SOP 本身贡献多少（A4）。

## 2. 主指标

**答错率** = 答错的行数 / 有结果的行数。

答错指两种情况：给了确定答案（OPEN / CLOSED）但和金标准相反；或者金标准是 UNKNOWN / AMBIGUOUS
（该说不知道、该追问）时给了确定答案。判分矩阵见 eval/DESIGN.md 第 5 节，代码在 src/travelkb/evalkit/scoring.py。

不用「答对率」当主指标：全答 UNKNOWN 的系统答错率也是 0，所以答对率、弃答率一起报，但只有答错率参与检验。

## 3. 假设（验证性检验只有这三条）

| 编号 | 假设 | 比较 | 指标 | 题目范围 |
|---|---|---|---|---|
| H1 | A3 答错率低于 A0 | A3 vs A0 | 答错 | 全部题 |
| H5 | A6 答错率高于 A3 | A6 vs A3 | 答错 | 换季、每月循环、例外日、同名四类（题型清单见第 8 节） |
| H3 | A4 工具合规率低于 A3 | A4 vs A3 | 工具合规 | expected_tools 不为空的题 |

**工具合规**：expected_tools 里的工具都调过，并且第一次出现的先后和 expected_tools 一致（先 resolve_poi 再 is_open）。

其余所有数字（答对率、各类弃答、按题型的拆分、A6 vs A0、用量）都是探索性的，报告里标明，不做检验结论。

## 4. 统计方法

- **分析单位**：按题算，一题在一组里只要有一遍答错就算这题答错（2 遍里错 1 遍也算错，因为答错的代价高）。
  不按「题 × 遍」配对：同一题的两遍不独立，配成 60 对会让 p 值偏乐观
- **检验**：McNemar 精确检验，双侧。只看「一组错、另一组没错」的题
- **显著性**：α = 0.05；三条假设用 Holm 校正
- **方向**：p 达标且方向和假设一致，才算支持；方向相反照实报告
- **工具合规按题汇总**：一题在一组里两遍都合规才算合规（和「一遍错就算错」同一个口径）
- **不显著时**：写「这批题上没看出差别」，不写「没有差别」。30 题只检出得了很大的差异：
  不校正时，至少要 6 道题「只有 A0 错」、0 道题「只有 A3 错」才有 p < 0.05（6:0，p = 0.031）；
  Holm 校正后最先比较的那条门槛是 0.0167，要 7:0（p = 0.016）
- **区间**：每个答错率配 Wilson 95% 区间
- **分析代码**：冻结前 eval/score.py 要按本节实现（按题汇总、H3 的合规检验、H5 的题型子集），
  代码在 src/travelkb/evalkit/analysis.py（测试 tests/evalkit/test_analysis.py）。
  score.py 原有的「题 × 遍」配对表保留，只当描述性数字

## 5. 各组配置

| 组 | 系统提示 | 能用的工具 |
|---|---|---|
| A0 | eval/groups/base.md | 无（内置工具全关，MCP 全禁） |
| A6 | eval/groups/base.md | WebSearch、WebFetch |
| A3 | eval/groups/A3/system.md（= docs/SOP.md + 和其他组相同的 VERDICT 段） | travelkb：resolve_poi、is_open、check_day_plan、find_open_pois |
| A4 | eval/groups/base.md | 同 A3 |

- 完整命令行由 src/travelkb/evalkit/groups.py 生成，每次运行的第一条记录（meta.jsonl）里存了一条样例命令
- 每题每组每遍一个全新的 `claude -p` 进程，在空的临时目录里跑；最多 6 轮
- 每次运行检查 system/init：模型对、MCP server 只有该有的且已连接、没有本组不该有的工具；不对就算 harness 错误
- 有工具的组，travelkb server 的「今天」钉在题目的 today（TRAVELKB_TODAY），过期提醒按 today 算
- A2（只有 SQL）、A5（代码编排）这次不跑。以后补跑时用同一批题、同一个模型，先往本文件追加假设再 commit

## 6. 模型和规模

- 模型：claude-opus-5-5（和 Claude Desktop 里用的同一个）
- 运行方式：Aaron 本机，Claude 订阅，不加 --bare；跑之前清掉 ~/.claude/CLAUDE.md 里和旅行有关的内容
- Claude Code 版本：跑的时候记进 meta.jsonl（试跑时是 2.1.311）
- 题数 30（eval/questions.yaml 冻结时的内容），覆盖布达佩斯、维也纳、布拉格、米兰、巴黎五座城；
  每题每组跑 2 遍，共 30 × 4 × 2 = 240 次
- 题型配比按 eval/DESIGN.md 第 2 节；每题 gold 回官网独立核对，存 Wayback 链接

## 7. 什么不算、什么要排除

- **harness 错误不进结果**：进程非零退出、限流、超时、到轮数上限、system/init 校验失败，只记进 errors.jsonl。
  用同一条命令续跑补齐；一题一组一遍最多试 3 次，还失败就算缺失，配对检验时这题在两组都去掉，报告里列出缺了哪些
- **没写 VERDICT 不算错，但占分母**：报告里单列。模型拒答也落在这一类
- **试跑不进结果**：eval/runs/pilot、pilot2 只用来检查框架，不参与任何检验

## 8. 已知的偏差来源（提前写明）

- **q01–q04 用来调过 SOP**：第一次试跑里 A3 在 q01、q02 上反问「哪一家」，因此改了 SOP 第 1 条的查询规则，
  第二次试跑 q01–q04 才全对。这四题对 A3 不是「没见过的题」。
  处理：主分析照常用全部 30 题，另报一次去掉 q01–q04 的结果（各自做 Holm 校正）；两个结论不一致时以去掉后的为准
- **H5 的题型清单**：season_boundary、monthly_rule、exception_closed、exception_changed_hours、
  same_name_in_city。2c 没有找到真实的每月循环景点，原计划的两道 monthly_rule 题已并入例外日，清单不变
- **q11–q30 是 CC 起草的**：CC 同时写了系统（工具、SOP 的修改），知道系统的弱点在哪，出题可能无意中避开它们。
  缓解：题型按 DESIGN 的配比分配；gold 由 Aaron 打开官网重新核对（不看 YAML、不看原文摘录）并存档；
  报告里把 q01–q10（Aaron 出题）和 q11–q30（CC 出题）的答错率分开列出（描述性，不做检验）
- **数据比题目新**：2c 新增景点的核验日期会晚于部分题目的 today。新题的 today 不早于对应景点的核验日期
- **金标准出错的可能**：每题 gold 由 Aaron 独立核对官网并存档。跑完后发现 gold 错了，改正它、在第 10 节记一笔，
  并同时报告改正前后的数字

## 9. 冻结什么

冻结点之后，下面这些不再改动（eval/runs/ 和本文件第 10 节除外）：

- eval/questions.yaml（题目、today、gold）
- eval/groups/ 下的系统提示，以及 docs/SOP.md
- data/ 下的全部数据
- src/ 下的全部代码

冻结前必须满足：data/drafts/ 里的景点全部核对完、移进 data/pois/、review 改成 verified；
questions.yaml 每题的 gold_checked_at 和 gold_archive 都不是 null；validate_data 零 error、零 warning。

核对办法：跑完后执行 `git diff <冻结点> HEAD -- . ':!eval/runs' ':!eval/PREREG.md'`，输出应为空；
每次运行 meta.jsonl 里的 git_commit 都应该是冻结点或它之后只改了 eval/runs/ 的 commit，git_dirty 为 false。

## 10. 偏离记录

冻结之后如果必须改动任何东西，先在这里写明日期、改了什么、为什么，commit 之后再继续跑。

（暂无）

## 附：Aaron 的预测（可选）

跑之前写下你猜的各组答错率。猜得准不准不重要，重要的是事后能对照「哪里出乎意料」。

| 组 | 预测答错率 |
|---|---|
| A0 | |
| A6 | |
| A3 | |
| A4 | |
