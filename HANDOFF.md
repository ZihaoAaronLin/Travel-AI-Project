# HANDOFF

## 2026-10-08 · 第 1 阶段数据草稿

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

### 待 Aaron 定的规则语义（不定就没法写测试）
1. **收费时段 ≠ 开放时段**：渔人堡官网给的是 Payment periods。收费时段外问「能进吗」，该答 CLOSED 还是 UNKNOWN？建议规则加 `outside_hours: UNKNOWN`（默认 CLOSED）
2. **例外日要提前到第 1 阶段**：真实数据在有效期内就有例外（美术馆 10/9 改时间；农业博物馆和两座塔 11/1、12/24–26、1/1 闭馆）。第 1 阶段原计划不做第 2 步（例外），那样这些天会错答 OPEN。建议第 1 阶段就做「单日例外」，RRULE 留到第 2 阶段
3. **只列开放日、没明说闭馆的星期**：国家美术馆、使徒塔的周一没有规则 → 查出 UNKNOWN。确认这样处理，或者从官网找到明确的周一闭馆说明再补
4. 拆分的代价：「渔人堡」「沃伊达奇城堡」「圣史蒂芬大教堂」都会返回 AMBIGUOUS，模型每次都要追问是哪一部分。确认可以接受

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
1. Aaron：回答上面 4 条语义问题；逐条核对 12 个 YAML，核对完把 review 改成 verified
2. CC：按定下来的语义写 tests/unit（假数据）给 Aaron 审，再写 Pydantic 数据模型 + validate_data.py + build_db.py + core 的 resolve_poi / is_open
3. Aaron：用这批真实数据写 10 条金标准（城内同名用「美术馆」；闭馆日用 MFAB 周一；窗外日期用大教堂 12/30 之后；例外日用农业博物馆 11/1；晚于最后入场用国家美术馆 17:30）

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
