# HANDOFF

## 2026-09-30 · 定位调整 + 第 1 阶段准备

### 做了什么
- 第 0 阶段验收完成：Aaron 本机 pytest、Inspector、Claude Desktop 都调通了 ping
- 路线图进仓库：docs/ROADMAP.md（原 Cowork 版 + 本次调整）
- 定位调整（Aaron 已同意，细节见 ROADMAP 开头）：
  - 做「行程核验」，不做又一个规划器
  - 分层：模型 + 搜索做数据采集（只产出 draft）→ 代码判定 → 人工抽检校准，报抽取准确率
  - 评测新增 A6（模型 + 联网搜索）、可选 A7（圆周旅迹人工对比），假设 H5
  - 第 4 阶段加官网抽取管线 scripts/extract_poi.py
- 第 1 阶段城市定为布达佩斯，景点和官网见 ROADMAP 第 1 阶段；渔人堡、沃伊达奇城堡各拆两条（共 8 条 poi）；Aaron 确认 vajdahunyadcastle.com 是官方站

### 官网抓取结果（2026-09-30）
- 圣史蒂芬大教堂 bazilikabudapest.hu/nyitvatartas：已抓到。匈牙利语页比英文页完整（英文页漏了关门时间）；页面没写有效期
- 沃伊达奇城堡 vajdahunyadcastle.com：**证据显示不是官方站**（和 hungarianparliament.com、szechenyibath.com、budapestcards.com 同一批站点，用第三人称介绍博物馆）。官方应为匈牙利农业博物馆 mezogazdasagimuzeum.hu，被云端网络策略拦截（403）
- 渔人堡 ticket.budavar.hu：纯前端页面，开放时间要浏览器执行 JS 才出现；curl 拿不到，容器内浏览器因 TLS 证书信任问题没跑起来
- 两家美术馆 en.mng.hu、www.mfab.hu：网站本身返回 HTTP 451，拒绝云端访问
- 国会大厦：parliamentvisit.com 会跳到不带 www 的域名，被网络策略拦截（403）

### 没做完
- 除大教堂外，其余景点开放时间要 Aaron 在本机浏览器复制或截图
- 第 7 节规则语义第 0–5 步，Aaron 还没审定；拆分后「全天可进的露台 / 庭院」在 is_open 里怎么表达还没定
- 10 条金标准还没写

### 下一步
1. Aaron：发来 8 条 poi 的官网开放时间（含有效期、闭馆日、最后入场、来源页 URL）；审定规则语义
2. CC：按第 7 节格式起草 data/pois/*.yaml（全部 status: draft）+ tests/unit 单元测试，交 Aaron 审测试
3. 测试审过后实现 build_db.py、core 的 resolve_poi / is_open、server 工具

### 已知问题
- 日志配置依赖 SDK 的实现细节（MCPServer.__init__ 里的 configure_logging）；SDK 升级后若不再配置，INFO 日志会丢，但 WARNING 以上仍走 stderr，不会写到 stdout
- 「用户是否真的在乎核验」是未验证假设，演示前要找真实用户或评论区证据

## 2026-09-29 · 第 0 阶段骨架

- uv 包项目（Python 3.12，src 布局，import 名 travelkb）；依赖 mcp[cli] 2.2.0、pydantic、pyyaml、python-dateutil；dev：pytest、anyio、ruff
- server.py：MCPServer("travelkb")，只读 ping 工具返回 {ok, server_version}；脚本入口 travelkb-server
- 日志走 SDK 配好的 stderr handler；ruff 开 T20 禁 print
- tests/test_server.py：内存 Client 断言 structured_content 和 read_only_hint
- CLAUDE.md 铁律 3 改为：core 不调 now()，「今天」由 server 层按景点时区算好再传入
