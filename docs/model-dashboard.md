# AI 模型能力看板

`model_dashboard/` 提供一个基于 `模型能力测试-20260623-展示优化版.xlsx` 数据整理的本地 HTML 看板。它展示人工测试、ModelTest、Arena WebDev、费用快照和原表综合分，支持看板/表格模式切换、搜索/筛选、全量排序后分页、归档/恢复、增加模型、Agent 使用人数手工录入与 CSV 导入，以及从第三方 JSON API 拉取数据。

页面右上角以“同步三方数据”为主按钮，会依次同步 Arena、Artificial Analysis、LLM Stats；某一源失败不影响其余来源，结束后给出汇总提示。旁边的“单项”菜单仍可单独同步某一个榜单。

- “同步 Arena 全榜”分页读取 [Arena WebDev 榜单](https://arena.ai/leaderboard/code/webdev) 的官方 `webdev/latest` Overall 快照，保存名次、Score、输入/输出 Price $/M 和官方来源。价格优先读取 Arena 页面及 LMArena 官方价格目录；Cloudflare 阻止页面读取或目录未覆盖当前模型时，横向总表会明确使用已匹配 AA 服务商配置的价格作为参考，不伪装成 Arena 原始字段。
- “同步 AA Model 全榜”读取 [Artificial Analysis Models](https://artificialanalysis.ai/models) 的公开加密 manifest，保存完整模型榜、Intelligence、Speed、Cost per Intelligence Index Task、Terminal-Bench 4.0 和服务商配置。解码使用 Node.js 内置加密与 gzip 能力，不需要 AA API key。
- “同步 AA Agent 全榜”读取 [Artificial Analysis Coding Agents](https://artificialanalysis.ai/agents/coding-agents) 的完整榜单，保存 Coding Agent Index、DeepSWE v1.1、Terminal-Bench 4.0、SWE-Atlas-QnA、Time per Task、Cost per Task 及底层模型标识；旧版字段继续兼容读取。
- “同步 LLM Stats 全榜”读取 [LLM Stats](https://llm-stats.com/) 官网使用的公开 `general` 指数榜单及 Coding 分项，保存完整排名、官方模型 ID、组织、14 天排名变化和参与评测数。

每个来源的成功同步都会保存不可变 SQLite 快照，默认对比最近两次，也可选择任意历史批次。页面分别标记名次和指标变化、新上榜、退出榜单及版本不可比；同步失败不会推进该来源的历史基线。

---

## 启动与数据缓存

直接启动（无需安装额外依赖）：

```bash
python3 -m model_dashboard.server
```

开发时可用 `--reload` 监听 `model_dashboard/**/*.py` 变更并自动重启（不监听 `data.local.json`，避免写入数据时误重启）：

```bash
python3 -m model_dashboard.server --reload
```

浏览器打开 <http://127.0.0.1:8765>。新增或导入的数据默认写入被 Git 忽略的 `var/sqlite/fox-airank-deepeval.db`；首次启动会从已有的 `model_dashboard/data.local.json` 自动导入，原 JSON 文件保留。可通过 `--data` 指定 SQLite 文件路径；静态页面每次请求都会重新读取，改 `static/index.html` 后刷新浏览器即可，无需重启。

数据缓存：本地实测结果（`/api/local-benchmarks`、模型榜单与 AI 分析读取的同一份数据）缓存在 SQLite 中，页面不再每次请求都重扫 `runs/`；当 `runs/` 或 `cases/*/*/case.json`、`TASK.md` 的文件指纹与缓存不一致时视为过期。三方榜单沿用已有 SQLite 快照，最近一次同步超过 `--cache-max-age-hours`（默认 24，必须大于 0）即视为过期。页面始终展示缓存数据（prompt-only）：有过期来源时顶部显示提示条，逐条列出过期来源、缓存时间与过期原因，点「全部更新」或单条「更新」手动刷新，不会自动同步；「更多 → 缓存状态」按来源列出缓存时间与状态，提供同样的更新入口；「刷新本地结果」按钮走同一条更新路径。多来源更新并发发起（各来源互不依赖，服务端写入由 `DashboardStore` 的锁串行化），单个来源失败不会中断其余来源；失败来源会保留提示条并附上错误原因与「重试」入口，直到该来源被判定为最新或下次更新成功。

---

## 聚合权重与归一化

Model 三方聚合分先在各来源当前完整快照内按原始得分做 0–100 min-max 归一化，再按默认的 Artificial Analysis 50%、Arena 35%、LLM Stats 15% 加权。顶部「配置」页面可以修改这三个来源的权重，单项允许为 0%，但合计必须为 100%；保存后持久化到本地 SQLite 并立即重新计算聚合分、排名和来源列顺序。每行按“模型版本 + 智能度（推理强度）”独立匹配与算分，中英文强度别名会统一，但 High、XHigh、Max、Ultra 等配置不会混合。没有披露智能度的成绩单列为“未注明”，不会填入已知智能度的配置。只有同模型、同智能度在同一来源存在多条记录时，才选择官方名次最高的一条参与聚合，其他记录仍可展开检查。权重大于 0 的来源缺失时不计算聚合分，缺失值不会按 0 分或重新分配权重；设为 0% 的来源不再作为完整性门槛。本地实测分按任务正确性 70%、稳健与安全 20%、交付证据 10% 计算；同任务重复运行先平均，再跨任务平均。实战综合分采用同模型、同智能度的三方聚合分 70% + 本地实测分 30%，只有共同测试集齐全且每题至少完成 3 次时进入正式排名，覆盖不足时仅展示试算值。

Model 榜单支持“纯 Artificial Analysis”模式。开启后只展示 AA 已发布的模型与智能度配置，按 AA 官方名次排序，并直接展示 Intelligence、Speed、Terminal-Bench 4.0、服务商配置和成本；Arena、LLM Stats 与三方聚合分不参与该视图。该模式可继续叠加搜索和“仅看 Legion”筛选，切回后恢复原三方综合榜单。

---

## 智力基线与「差」判定

看板有一条固定的智力基线口径：**AA Intelligence Index 低于 DeepSeek Flash 最新版本的配置判为「差」**。基线由 `model_dashboard/baseline.py` 从当前 AA Model 全榜快照动态解析，不写死分数、也不需要手工配置：

- 候选行取来源为 `artificial_analysis_model`、名称（含 AA release 名与 slug）同时命中 `deepseek` 与 `flash` 的记录，排除 Vision / Image / Audio / TTS / OCR 等多模态变体和已归档记录。
- 按名称中的版本号与四位日期（如 `V4.1`、`0420`）比较出最新版本，同版本内取 Intelligence Index 最高的配置作为基线分，即该模型最强档位；因此 Non-reasoning 档位不会把基线拉低。
- 同步「AA Model 全榜」后基线自动跟随官方数据；DeepSeek 发布更新版本时无需改动代码或配置。

判定规则：配置的代表性 AA Intelligence Index 低于基线为「差」，等于或高于为「达标」；缺该分数、或快照里没有可比的 DeepSeek Flash 最新版时**不判定**，不按 0 分处理，AI 参谋侧会给出「基线不可用」警告。

生效范围：

- **Model 三方榜单**（含「纯 Artificial Analysis」模式）：低于基线的配置在模型名下方显示红色「差」徽章，悬停可看具体分数与基线出处，页头同时说明当前基线口径。
- **效率与综合最优**：两张以 Intelligence Index 为纵轴的散点图画出红色虚线基线（纵轴定义包含基线，点全部高于或低于时也能看出差距），低于基线的点标红并在悬停标题中说明；图表表格新增「智力基线」列，三维平衡排名的 Model 组显示基线说明与「差」徽章。Coding Agent 侧的 Coding Agent Index 与智力不是同一量纲，不参与该判定。
- **AI 参谋**：分析快照带 `intelligence_baseline` 与 `intelligence_grading` 口径，提示词要求按该基线评价「差」，并且禁止自行设定阈值。

Agent 榜单与 Legion 推荐不显示该徽章，只在其底层模型列中沿用同一份 AA 数据。

---

## 页面导航与 hash 链接

顶部导航按用途拆分：「本地实测」展示本地运行评分、作品与人工能力剖面；「Agent 三方榜单」按 Agent 聚合 AA 配置，展开后展示各模型与智能度的 Coding Agent Index、成本、耗时及底层模型对照，Coding Agent Index 可直达官方指标区块，模型基线仅展示可比的 Terminal-Bench 4.0 分数并可跳转到对应模型页；「Model 三方榜单」横向合并 Arena、AA Models、LLM Stats 和本地实测；「Agent 使用人数」「订阅费用快照」和「配置」各自独立成页。Agent 榜单默认按组内最佳 Coding Agent Index 排序，也可切换为按组内最佳同配置 Terminal-Bench 4.0 提升效果排序；两种排序下分组摘要行都同时给出组内最佳 Coding Agent Index 原始分与组内最佳同配置 Terminal-Bench 4.0 提升（提升前 → 提升后，两个分数与提升幅度同源可核对），两项可能取自不同模型与智能度配置，因此各自标注所属配置；分数均可点击跳转 Artificial Analysis（基线缺失时只省略「提升前 / 提升后」而不改写提升幅度）；无有效值的 Agent 排在末尾且空白不按 0 分处理。费用快照拆成「Agent Plan」与「Token Plan」两个区块（原「Code Plan」已整体并入 Token Plan）：Agent Plan 对应 IDE / Agent 形态的订阅档位，Token Plan 对应按 token / Credits 额度计费的档位；页内顶部提供章节导航，锚点为 `/#pricing-agent` 与 `/#pricing-token`，旧 `/#pricing-code` 继续落到 Token Plan 区块；每个区块只展示已录入该形态价格的工具，全部为空时提示待补录。规范字段为 `agent_plans` 与 `token_plans`；旧 `ide_plans`、`coding_plans`、`code_plans` 和 `plans` 数据继续兼容读取，其中旧的 coding / code 档位归入 Token Plan（`pricing.normalize_pricing_kinds()` 可就地迁移，同名档位不重复追加）。档位可带 `detail` 小字（如额度说明），与月费同行展示。

页面可通过 `/#dashboard`、`/#agent-reference`、`/#reference`、`/#agent-usage`、`/#pricing`、`/#pricing-value`、`/#pricing-agent`、`/#pricing-token`、`/#settings` 直接打开，支持刷新和浏览器前进/后退；旧章节链接（含 `/#section-pricing-value`、已并入 Token Plan 的 `/#pricing-code`）继续进入迁移后的所属页面。

---

## 订阅费用快照

费用快照页最前面新增「统一坐标系 · 性价比」区块（章节 key 为 `value`，锚点 `/#pricing-value`）。它把各档位月费折算到可比口径，用于跨工具横向比较：

- 主坐标 `¥ / 百万 token`。档位需提供 `included_tokens`（月度额度，token）与 `token_basis`（折算依据原文，展示在该行下方）。
- 副坐标 `¥ / 美元额度`（`¥/USD`）。档位只提供 `included_usd_credit`（月度额度，美元）而没有 `included_tokens` 时使用，按 `price_cny_month / included_usd_credit` 计算。
- 两个坐标系**不做跨口径换算**：只有美元额度、未公布 token 数的档位记为 `—`，并在区块底部汇总「不做估算」的档位数量与原因，避免把「只公布美元额度」误算成「便宜」。
- 主表按 `¥/Mtok` 升序并给出「相对最优」倍数，最低值一行高亮；档位标注 `calibration_note`（如 Credits 折算口径与社区实测差异）会显示在工具卡片上，提醒不要只取表中最优值。
- 汇率沿用快照原值 1 USD = 6.75 CNY（`USD_TO_CNY`），前端 `planCnyPerMtok()` 与后端 `pricing.value_overview()` 口径一致。

每条条目都记录原始地址。条目可带 `sources` 数组（旧的 `official_url` 继续作为第一个来源回退读取），元素形如 `{"label": "GLM Coding Plan 订阅页", "url": "https://z.ai/subscribe", "snapshot_at": "2026-09-27", "status": "ok"}`；缺失 `label` 时用 URL 兜底。工具卡片底部渲染「采集日期 · 各来源链接 + 状态徽章 · ↻ 刷新」，点击刷新会重新抓取这些地址。来源状态：`ok`（正文 ≥ 200 字符）、`partial`（疑似纯 JS 渲染，正文过短）、`blocked`（命中反爬特征串）、`error`（抓取异常，附 `http_error`）。刷新采用内容指纹（归一化空白后取 sha256 前 16 位）比对：指纹变化才推进条目的 `snapshot_at` 与该来源的 `snapshot_at`，正文无变化时不推进，避免把「抓到了页面」误当成「价格已更新」。抓取默认沿用环境变量中的代理，代理 tunnelling 失败（如 `Tunnel connection failed`）时自动回退直连，而 403 / 404 等 4xx 属于对方明确应答，不再回退。相关接口为 `GET /api/pricing/sources`（汇总全部条目的来源记录）与 `POST /api/pricing/refresh`（请求体 `{"tool": "Z AI"}` 可只刷指定工具，返回 `{checked, updated, blocked, error, sources}`）。

---

## AI 参谋：总结与推荐

Vibe Coding Legion 首页的「AI 参谋：总结与推荐」面板可输入使用需求，点击生成模型数据总结、场景推荐、推荐依据和限制。它调用 [SenseNova Token Plan](https://www.sensenova.cn/token-plan) 的 OpenAI 兼容接口（`POST https://token.sensenova.cn/v1/chat/completions`），与 DeepEval 评测和本机 Codex 登录状态无关。请求体只带当前指标快照、需求文本与输出 JSON Schema；仅手动点击生成时调用模型，普通刷新只读取最近一次成功结果。旧链接 `/#ai-insights` 仍然有效：会打开 Legion 首页并展开、定位到该面板。

密钥只从环境变量读取，不写入数据文件，也不在页面或接口中返回。启动看板前设置：

```bash
SENSENOVA_API_KEY=... \
MODEL_DASHBOARD_AI_BASE_URL=https://token.sensenova.cn/v1 \
MODEL_DASHBOARD_AI_MODEL=sensenova-6.8-flash-lite \
MODEL_DASHBOARD_AI_TIMEOUT=180 \
python3 -m model_dashboard.server
```

- `SENSENOVA_API_KEY`：必填，缺失时面板显示「未配置 Key」且生成按钮不可用。
- `MODEL_DASHBOARD_AI_BASE_URL`：默认 `https://token.sensenova.cn/v1`，必须为 HTTPS（本机调试可用 `localhost` 的 HTTP）。
- `MODEL_DASHBOARD_AI_MODEL`：默认 `sensenova-6.8-flash-lite`。
- `MODEL_DASHBOARD_AI_TIMEOUT`：默认 180 秒，取值 10 至 1800。

未配置密钥时页面仍可查看已保存的分析。接口错误只回传分类提示（密钥无效、配额超限、HTTP 状态码、网络超时），不会把响应体或密钥透传到页面。

AI 接收当前未归档模型的指标、来源时间、按配置汇总的本地实测及覆盖信息，不发送原始日志、工作区代码或备注。缺失指标不补零，不混用不同推理强度或 Agent 的成绩；每条推荐的配置身份和引用指标由服务端从输入快照回填。文字结论仍是 AI 推断，页面提供原始证据供核对。超过单次输入上限时明确报错，不静默裁剪榜单。

最近一次成功分析单独保存在当前 SQLite 的 `ai_insights` 表中，记录需求、分析模型、生成时间和数据摘要；不会修改 Legion 手工推荐、发布版本或评分。数据变化后页面提示结果过期，生成失败保留上一次结果；同一服务进程同时只接受一次生成。接口为 `GET /api/ai-insights`（状态和结果）与 `POST /api/ai-insights`（JSON 请求体 `{"goal":"优先比较代码审查质量与成本"}`，空需求使用默认场景）。

---

## Vibe Coding Legion

「Vibe Coding Legion」是默认页面，顶部导航另有独立的「Legion 日志」页面；两页分别使用本地打包的军团出征图和技能冷却图，不依赖外部图片服务。Legion 页面先按主用途分组，再在用途内按建议中的 Agent/工具聚合；工具为空时回退使用 Agent Plan 或 Coding Plan 作为 Agent 名。存在同名费用快照的 Agent 分组会显示「订阅费用」链接，点击后进入费用页并定位、高亮对应工具；没有匹配费用记录时不显示空链接。默认用途类型为 `Ask`、`Plan`、`Build`、`Review` 和 `Ship`，每条建议的主用途与副用途都支持多选，副用途仅作为浅色标签展示，不建立页面分组。每张配置卡片按模型名称和工具匹配本地打包的简化家族标记，覆盖 GPT/OpenAI、Claude/Opus、Grok、DeepSeek、Cursor/Composer、Qwen、Kimi 与 Gemini，未知模型回退到模型首字符。只有主用途分组中的卡片支持在右上角用空心/实心星星执行“设为核心 / 取消核心”；核心卡片同时使用金色边框和浅色背景高亮，编辑弹窗中的复选框仍可维护同一字段。点击「编辑建议」可按模型、工具或推理强度搜索配置，复制已有配置，并用固定底部操作区保存；关闭有未保存修改的编辑器时会二次确认。用途类型支持 1 至 20 个逗号分隔值，并提供即时数量、重复与长度校验；每条建议可以分别多选主用途、副用途及修改说明，选择同一类型时会自动从另一用途角色移除。默认不自动标记任何配置。每条建议仍按工具、模型和推理强度优先匹配本地实测结果，展示该配置任务正确性最佳一次运行的三项能力分；没有本地结果时再匹配模型数据，仍无记录或尚未评分时明确显示为空，不按 0 分处理。模型必填，其他字段可留空；主用途留空时，Agent Plan 优先归入 `Plan`、Coding Plan 优先归入 `Build`，对应类型不存在时归入配置列表第一项。用途说明留空时按 Plan 归属和推理强度显示中性默认说明。保存后写入同一本地数据文件，刷新页面或重启服务后保留；取消不会保存。点击「发布 Vibe Coding Legion」会把已保存草稿固化为不可变版本，发布历史在「Legion 日志」页保留完整快照、SHA-256、发布说明和新增/更新/移除差异；内容未变化时不会重复生成版本。旧数据会把原用途数组的第一项读取为主用途、其余项读取为副用途，并继续提供旧字段兼容视图，但不会因读取而写回。建议独立于评分、费用和榜单同步，不参与排名计算。

星标实际按“用途 + 建议条目”独立保存；同一建议属于多个主用途时，只高亮用户点选的那个用途条目。旧数据中的整条 `is_core=true` 会兼容映射为该建议的全部主用途，并继续输出布尔别名供旧客户端读取。

Agent 与 Model 三方榜单都会高亮匹配的 Legion 配置并显示空心 / 实心星标及具体用途，支持“仅看 Legion”筛选。Model 按模型与智能度匹配；Agent 还要求工具一致，不借用其他 Agent 的成绩。Agent 聚合行汇总组内收藏状态、主用途和弱化展示的副用途，展开后的配置仍保留各自的精确星标与用途；启用“仅看 Legion”时只展示匹配配置，并仅用这些配置计算组内最佳排序值。保存建议或切换核心星标后，榜单同步更新。缺失的 Legion 配置会作为补充行展示已有的同配置模型数据，不伪造 Agent 分数或官方排名。点击“补齐 Legion 数据”会仅对有缺失项的来源重新获取完整官方目录并融合，保持归一化使用完整来源快照；单一来源失败时保留该源原有数据并继续其他来源。补拉后仍未发布的配置分数保持为空，且不会使用其他智能度补位。

---

## 本地实测

本地鹈鹕测试默认按「模型＋智力程度（推理强度）」合并多次运行，展示组内「任务正确性」得分最高的一次；同分取最新一次，有效的 0 分优先于未评分。同一模型不同智力程度分别展示；同一模型、同一智力程度使用不同工具时仍参与同组比较，评分表中的三项分数、耗时和明细来自选中的同一次运行。作品区只预览带有完整单文件 HTML 的运行；当评分表选中的运行没有可预览作品时，作品区会在当前筛选范围内回退到另一条可预览历史运行，并标明自己的 `run_id`、得分（未评分会明确显示）和耗时。仍可切换到「每个配置最新一次」或「全部运行（含失败）」查看历史；其他任务保持按配置展示最新结果，原始运行记录不变。

在「配置与评分明细」中点击「展开明细分」，可在模型行下方查看三项分数、通过阈值、状态和评分理由，再次点击即可收起；「查看完整明细」仍可打开包含裁判配置与评分来源的弹窗。

---

## Agent 使用人数导入

Agent 使用人数支持 CSV 文件导入（顶部「导入使用人数」、面板「导入 CSV」，或录入对话框内的「导入 CSV」）。表头需包含工具列和使用人数列，备注列可选，例如：

```csv
tool,user_count,notes
Claude Code,1200,Q2 内部统计
Codex,800,
```

也可用中文表头 `工具,使用人数,备注`。同名工具（大小写不敏感）会覆盖已有记录；文件内重复工具以最后一行为准。

---

## 第三方 JSON 接入

第三方接口必须返回 JSON。页面支持通过点号路径映射嵌套字段；例如接口返回：

```json
{
  "data": {
    "models": [
      {
        "agent": "Codex",
        "name": "GPT-X",
        "scores": {"model_test": 95, "arena": 1600}
      }
    ]
  }
}
```

可填写数组路径 `data.models`，并将 `tool` 映射到 `agent`、`model` 映射到 `name`、`scores.model_test_total` 映射到 `scores.model_test`。需要鉴权时，只在页面填写环境变量名，例如先运行 `export MODEL_API_TOKEN='...'`，再将该变量配置为 `Authorization` 请求头的 `Bearer ` 凭据；密钥本身不会写入页面或仓库。

---

## 计算口径

看板计算口径：

- 人工测试总分仍按兼容字段 Skill 调用、逻辑梳理分（原代码评审）、逻辑分析、功能修复四项之和计算；“本地实测”的人工能力剖面只展示逻辑梳理分，并把鹈鹕测试的任务正确性展示为功能实现分。
- 智力基线：AA Intelligence Index 低于 DeepSeek Flash 最新版（从当前 AA 快照动态解析）的配置判为「差」，缺值不判定；详见上文「智力基线与「差」判定」。
- ModelTest 总分按当前 case 数量加权：代码修正 3、代码生成 4、逻辑分析 8。
- 原表综合分沿用 Excel 公式：人工测试总分 + ModelTest 总分 + Arena WebDev。三者量纲不同，因此只用于还原原表排序，不代表归一化能力分。
