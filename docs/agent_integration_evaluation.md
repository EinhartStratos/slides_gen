# Agent 客户端接入方案评估：Skill vs MCP

> 日期：2026-10-09
> 目标：让桌面 Agent（Devin Desktop / Devin CLI）驱动 slides_gen_server 完成「导入模板 → 提交生成 → 跟踪进度 → 下载产物」全流程。
> 本文只做方案评估，不涉及代码改动。

---

## 0. 结论先行

**推荐「Skill + 内置薄客户端脚本」作为第一阶段接入**；当出现多人复用、非技术用户使用、或需要细粒度工具权限治理时，再演进到「远程 HTTP MCP（随 FastAPI 部署）」。

理由摘要：

- 服务端本来就是**异步任务 API**（提交返回 ID → 轮询状态 → 下载产物），两个方案的超时问题都不存在；
- Skill 方案**零服务端改动**，一个 SKILL.md 加一个 ~200 行的 Node 薄客户端脚本即可跑通（复用桌面端 Electron 自带 Node 运行时，`ELECTRON_RUN_AS_NODE` 执行，零外部依赖），当天可验证；
- MCP 方案体验更好（类型化工具、可发现、权限细粒度），但要新增一个需长期维护的组件，建议作为第二阶段；
- 凭据下发已确定为「桌面端注入环境变量」：模型永远接触不到 key，脚本运行时读环境变量塞进 HTTP 头；MCP 手工配置仅作兜底（详见第 6 节）。

> **落地状态**：第一阶段 Skill 已实现于 `.agents/skills/slides-gen/`（SKILL.md + slides_client.js），覆盖 parse 文件解析、generations/tasks 查询、产物下载；客户端需注入 `OPENAI_API_KEY`、`SLIDES_EHR`，可选 `SLIDES_BASE_URL`/`SLIDES_PARSE_URL`/`SLIDES_EXE`。

---

## 1. 先澄清两个顾虑

### 1.1 “模型请求次数过多”不影响 Agent 上下文

逐页规划、整页 SVG、单图 SVG、结构化填充等**全部 LLM 调用都发生在服务端**（`app/infrastructure/llm/openai_like_client.py`），由全局并发信号量和退避逻辑管理。

无论哪种接入方式，Agent 上下文里只有三类东西：

1. 请求参数（template_id、requirement 文件路径、custom_requirements）；
2. 轮询返回的状态 JSON（progress、current_stage、子任务状态，每次几百字节）;
3. 本地产物文件路径。

**不存在“把生成逻辑放进 Agent 上下文”的必要**，也就不需要“内嵌脚本里再请求大模型”——脚本只调 REST API，大模型调用永远留在服务端。

唯一要注意的是**上下文卫生**：

- `requirement_text` 最长 10 万字符，客户端必须支持**从文件读取**再提交，不要把全文贴进对话；
- `pages` / `artifacts` / `events` 接口返回列表可能很长，客户端脚本默认只回显摘要（数量 + 关键字段），需要明细时再显式拉取；
- 下载文件（pptx / svg / zip）一律**落盘返回路径**，不要把二进制内容回显到对话。

### 1.2 异步流程不会导致 MCP 超时

现状 API 已是最适合 Agent 的异步形态：

| 步骤 | 接口 | 耗时 |
|---|---|---|
| 提交生成 | `POST /api/v1/generations`（v4）或 `POST /api/v1/tasks`（legacy） | 毫秒级返回 `generation_id` / `task_id`，工作在后台线程执行 |
| 查询进度 | `GET /api/v1/generations/{id}`、`GET /api/v1/tasks/{id}`、`/pages`、`/events` | 秒级 |
| 下载产物 | `GET /generations/{id}/body/download`、`/tasks/{id}/download`、`/diagrams/download` 等 | 秒级 |

只要把 MCP tool 设计成对上述接口的**一一映射**（每次调用秒级返回），就不存在“一次 MCP 调用阻塞 20 分钟超时”的问题。**不要**把 MCP tool 设计成“submit 后内部死循环等到完成再返回”——那才会超时。

“中途没有输出”也不是问题：

- 每次轮询调用本身就会返回 `progress`、`current_stage`、`body_status/diagram_status/compose_status`，Agent 拿到后可以自然地向用户汇报“正文生成中，进度 62%”；
- 若用 Skill 方案，薄客户端脚本可以提供 `wait` 子命令在**单个 exec 调用内循环轮询并持续打印进度行**（Devin 的 exec 支持长时运行/后台运行），用户能实时看到滚动进度；
- 排障时还有 `GET /tasks/{id}/events` 事件流可拉取。

---

## 2. 方案 A：Skill（推荐第一阶段）

### 2.1 形态

```text
.agents/skills/slides-gen/          # 用 .agents 而非 .devin——本仓库 .gitignore 忽略了 .devin/
├─ SKILL.md                 # 工作流指令：何时触发、参数如何收集、调用哪个脚本、如何汇报
└─ scripts/                 # 实现脚本收进子目录，技能根目录只留 SKILL.md
   ├─ slides_client.js      # 薄客户端（纯 Node 内置 API：fetch/fs/FormData），子命令映射 REST API
   ├─ slides.sh / slides.cmd # ELECTRON_RUN_AS_NODE 包装（Win: 重定向+实时回显；Linux: 直接 exec）
   ├─ find_client_exe.ps1   # 定位运行中的客户端 exe —— Windows（进程树祖先 → app.asar 特征枚举）
   └─ find_client_exe.sh    # 同上 —— Linux/Unix（/proc 进程树 + app.asar 特征）
```

**运行时**：不用 Python，复用桌面端自带的 Electron 内嵌 Node——设 `ELECTRON_RUN_AS_NODE=1` 后客户端可执行文件即等价于 `node`（实测 Electron 36.0.0 / Node 22.14.0）。

两个 Windows 实测坑已封装进 `slides.sh` / `slides.cmd` 包装脚本，模型只需调包装脚本：

1. **GUI 子系统 stdout 不直连控制台**——直接执行 exe 看不到输出，必须重定向到临时文件再回显；
2. **安装路径不写死**——`$SLIDES_EXE` → 沿进程树找祖先中的 Electron 客户端（客户端拉起 Agent 时它就是祖先进程）→ 兜底枚举带 `resources\app.asar` 特征的运行中进程。

**第一阶段已实现命令**（对现有 API 的直接封装，全部为短调用；模板管理/stop/resume 等留作后续扩展）：

```text
slides health                                # GET /health
slides parse <file> [--out x.txt]            # POST csas /api/parse/file（multipart: file+fileId）
                                             # 需求源文件 → 纯文本落盘，只回显字符数与路径
slides create --targets body,diagrams \
       --requirement-file req.txt [--template-id X] [--custom "..."] [--no-auto-compose]
                                             # POST /generations → 打印 generation_id
slides status <generation_id>                # GET /generations/{id} → 摘要
slides wait <generation_id> [--interval 30] [--timeout 1800]
                                             # 循环轮询并打印进度行，直到终态
slides tasks [--generation-id id]            # GET /tasks?generation_id=
slides task <task_id>                        # GET /tasks/{id}
slides events <task_id> [--limit 20]         # GET /tasks/{id}/events（排障用）
slides pages <task_id>                       # GET /tasks/{id}/pages（排障用）
slides download <generation_id> --out ./out  # 下载 composed/body pptx 与 diagrams zip
```

**环境变量**（由桌面客户端在执行环境注入，脚本只读取、模型不可见）：

| 变量 | 用途 | 对应 |
|---|---|---|
| `OPENAI_API_KEY` | LLM API Key（兼租户标识）——**客户端已确认注入此名** | 请求头 `X-LLM-API-Key`；csas parse 的 `token` 头 |
| `SLIDES_EHR` | 用户 EHR 号（暂定名，客户端按实际注入名调整） | 请求头 `X-User-EHR`；csas parse 的 `User` 头（服务端暂未消费，透传预留） |
| `SLIDES_BASE_URL` | slides_gen_server 地址 | URL 前缀，默认 `http://127.0.0.1:8000/api/v1` |
| `SLIDES_PARSE_URL` | csas 文件解析接口 | 默认 `http://82.187.34.98/csas/api/parse/file` |
| `SLIDES_EXE` | 客户端自身 exe 路径 | ELECTRON_RUN_AS_NODE 展开形式使用（可选） |

SKILL.md 中写清楚：收集需求文本来源（优先文件路径，源文件先 `parse`）→ `create` → `wait`/`status` → `download` → 汇报产物路径与告警页。已设置 `allowed-tools: [exec, read]`、`triggers: [user, model]`；必要时可加 `subagent: true` 在独立上下文窗口里跑，进一步隔离主会话。

### 2.2 优点

- **零服务端改动**：不动 FastAPI 任何代码，风险最低；
- **交付快**：Markdown + 一个只用 Node 内置 API 的脚本（`fetch`/`fs`/`FormData`，无需 `npm install`），工作量约一天；
- **可移植**：同样能用于其他支持 shell 的 Agent（不绑死 Devin）；
- **迭代便宜**：改提示词和脚本即可，无需协议层兼容；
- **二进制友好**：上传模板、下载 PPTX 都是脚本直接读写本地文件，无序列化问题。

### 2.3 缺点

- **可靠性依赖提示词质量**：流程顺序、参数组装靠模型遵守 SKILL.md；缓解办法是把复杂度都收进脚本子命令，SKILL.md 只编排；
- **权限粒度粗**：只能控制到 `exec` 级别，做不到“允许查状态但禁止 stop”；
- **入口约定**：依赖客户端注入环境变量，并提供可调用的 exe 路径或 PATH 入口（见第 6 节）；
- **无类型化工具面**：模型看到的是脚本用法说明而非结构化 tool schema，误用概率略高于 MCP。

---

## 3. 方案 B：MCP

### 3.1 两种部署形态

**B1 · stdio 本地 MCP**：每个客户端机器跑一个本地进程；也可复用 `ELECTRON_RUN_AS_NODE` 以 Node 实现，避免 Python 依赖。

- 优点：能直接把产物写到用户本地磁盘，下载体验最好；
- 缺点：分发和维护成本高（随客户端打包可缓解）——与 Skill 脚本重叠却没比它轻。

**B2 · 远程 HTTP MCP（推荐形态）**：用 fastmcp 之类把 MCP 端点**挂在现有 FastAPI 服务里**（如 `/mcp`），随服务一次部署。

- 客户端只需 `devin mcp add slides http://server:8000/mcp`，并在配置 `headers` 里放 `X-LLM-API-Key`（存 `.devin/mcp_config.local.json`，不进 git、不进会话）；
- 鉴权头可复用现有 `get_api_key` 依赖；
- 唯一的妥协：MCP 服务端拿不到客户端文件系统，`download_*` tool 只能返回**下载 URL**，由 Agent 用 exec/curl 拉文件——这步简单且可靠。

### 3.2 工具面设计（与异步 API 一一映射，全部秒级返回）

```text
slides_health()
slides_list_templates()
slides_import_template(name, file_path)          # B1 可直接读本地文件；B2 需先经由 Agent 上传
slides_create_generation(requirement_text | file, targets, template_id, custom_requirements, auto_compose)
                                                 # → 立即返回 generation_id
slides_get_generation(generation_id)             # 轮询进度
slides_list_diagrams(generation_id)
slides_get_task_events(task_id, limit)
slides_stop_task(task_id) / slides_resume_task(task_id)
slides_get_download_urls(generation_id)          # 返回 body/composed/diagrams-zip 的 URL
```

另外可以发布一个 MCP **prompt**，Devin 会自动暴露成斜杠命令，如 `/mcp__slides__new_deck <需求>`，体验接近原生功能。

### 3.3 优点

- **类型化、可发现**：工具名和 schema 直接出现在 Agent 工具列表里，几乎不会调错；
- **权限细粒度**：`mcp__slides__*` 级别 allow/deny/ask，可按需禁用 stop/resume；
- **密钥不落地会话**：API Key 在 MCP config 里，Agent 看不到也不会复述；
- **集中部署（B2）**：服务端升级即所有客户端升级，没有逐机分发问题；
- 团队/多 Agent 客户端复用友好，是更“正式”的产品化接口。

### 3.4 缺点

- **新增一个要长期维护的组件**：协议封装、工具 schema 演进、测试都要跟上（引入 mcp/fastmcp 依赖，需满足 AGENTS.md 的“发布 ≥7 天稳定版”约束）；
- **分发配置仍有成本**：每个客户端要写一次 MCP 配置（虽然只有一次）；
- **二进制传输是短板**：PPTX/SVG 走 base64 会污染上下文，正确做法仍是返回 URL + 客户端落盘——即 MCP 并没有真正解决文件传输，只是把它推回给 exec；
- 对当前只有 REST 边界的项目来说，**初期投入产出比低于 Skill**。

---

## 4. 对比矩阵

| 维度 | Skill + 脚本 | MCP（stdio 本地） | MCP（远程 HTTP，随服务部署） |
|---|---|---|---|
| 服务端代码改动 | 无 | 无 | 新增 `/mcp` 端点（中等） |
| 客户端配置 | env 变量 ×2 | MCP 配置 + 本地 Python 环境 | MCP 配置（URL + header）一次 |
| 首次交付工作量 | 约 1 天 | 2–3 天 | 3–5 天（含测试） |
| 上下文占用 | 低（脚本回显摘要） | 低 | 低 |
| 超时风险 | 无（轮询或 `wait` 子命令） | 无（短调用映射） | 无（短调用映射） |
| 工具可靠性 | 中（依赖提示词遵守） | 高（类型化） | 高（类型化） |
| 权限粒度 | exec 级 | tool 级 | tool 级 |
| 文件上传/下载 | 最自然（本地脚本） | 最自然（本地进程） | 需 URL + exec 拉取 |
| 多人/多机分发 | 中（git 发 skill） | 差（逐机装环境） | 好（服务端集中升级） |
| 凭据自动下发 | env/会话文件（A/B） | env/会话文件（A/B） | env/会话文件，另可做 token 换凭据（C） |
| 跨 Agent 可移植 | 好 | 中 | 好（MCP 是通用协议） |
| 维护成本 | 低 | 中 | 中高 |

---

## 5. 推荐落地路线

```text
阶段 1（现在）          阶段 2（按需触发）
Skill + slides_client.js ──► 远程 HTTP MCP 挂在 FastAPI /mcp
（自用 / 小范围验证流程）     （团队推广 / 非技术用户 / 权限治理）
```

阶段 2 的触发信号（满足任一即可启动）：

- 使用者不只开发者本人，开始给产品/运营同事用；
- 需要在多个项目、多台机器上统一入口；
- 出现“误调用 stop/resume”“API Key 写进了聊天记录”这类治理需求；
- 想要 `/mcp__slides__new_deck` 这种一等公民式斜杠命令体验。

**不建议**先上 stdio 本地 MCP：它分发成本最高，能力上又与 Skill 脚本重叠；若将来确需“MCP 直接写本地文件”的体验，可把它作为 B2 之外的可选补充。

---

## 6. 用户凭据（X-LLM-API-Key / EHR）如何进入调用链

### 6.1 凭据在服务端的双重角色

`X-LLM-API-Key` 当前身兼两职：

1. **真实 LLM 凭据**：透传为 `Authorization: Bearer {api_key}` 调用 LLM（`openai_like_client.py`）；
2. **租户标识**：私有模板、任务记录按 api_key 归属隔离（`template_service.py`）。

EHR 号目前不在服务端字段中，属于前端门户侧的用户身份。

> 推论：不能用“服务端预置一把共享 LLM key”来绕过凭据下发——那样所有用户会共享同一个私有模板空间。除非后续把“LLM 凭据”与“用户身份”拆成两个独立字段。

### 6.2 关键澄清：模型不需要“读到”凭据

Skill 模式下模型只负责执行 `slides_client.js`；**凭据由脚本在运行时从环境变量解析后直接塞进 HTTP 头，全程不进入对话上下文**。这不仅可行，反而比让用户把 key 粘贴到配置里更安全（key 不出现在任何模型可见的位置）。

因此真正的问题是：**凭据在客户端机器上有没有一个可自动读取的来源**。

### 6.3 四种下发机制（按自动化程度排序）

| 方式 | 说明 | 适用 | 用户操作 |
|---|---|---|---|
| A. 桌面端注入环境变量 **（已选定）** | 桌面客户端在执行环境注入 `SLIDES_API_KEY` / `SLIDES_EHR` / `SLIDES_BASE_URL`；skill 脚本与 stdio MCP 都能继承 | 桌面端（Electron） | 零 |
| B. 读客户端持久化会话文件 | 登录接口返回值已落盘（`%APPDATA%` 会话存储 / 系统凭据管理器）；`slides_client.js` 或本地 MCP 进程直接读取 | 客户端有稳定可读的本地会话存储 | 零 |
| C. 令牌 + 服务端解析 | 客户端只配置登录 token；远程 `/mcp` 端点调用用户服务，用 token 解出 ehr → LLM key | 远程 MCP，多用户正式化 | 配一次 token |
| D. 手工配置 | 用户把 ehr + key 写进 `.devin/mcp_config.local.json`，或 `slides config` 落盘 `~/.slides-client.json` | 兜底方案 | 手工一次 |

### 6.4 对方案选择的影响

- **已选定 A（客户端注入环境变量）**：对 skill 脚本与 stdio MCP 同样有效，用户零操作；
- **手工方案（D）仅作兜底**：编辑 MCP 配置 vs 执行一次 `config` 子命令，两者摩擦相同——凭据问题本身不构成 MCP 的相对优势；
- **若未来走 C（token 换凭据）**：明显利好远程 MCP——凭据不下发、不落地客户端、可集中轮换，EHR 也能在服务端补全进任务记录；
- EHR 目前服务端不消费，脚本以 `X-User-EHR` 透传预留，待服务端需要时直接生效；
- 无论选哪种方式，SKILL.md / MCP 工具描述中都必须写明：**禁止在对话中回显凭据值**。

---

## 7. 风险与注意事项

1. **API Key 安全**：`X-LLM-API-Key` 会被服务端透传给 LLM 调用，等同于 LLM Key——只允许出现在 env 变量或 `mcp_config.local.json`（已 gitignore），SKILL.md 里写明禁止打印、禁止回显。
2. **需求文本走文件**：`requirement_text` 上限 10 万字符，客户端必须支持 `--requirement-file`，Agent 只传路径不传全文，避免上下文爆炸和转义问题。
3. **重复提交防护**：服务端创建接口无幂等键，客户端脚本/提示词应先 `GET /generations` 查重（同模板+同文本指纹）或让用户确认后再提交。
4. **轮询节奏**：建议 30–60s 间隔、总超时 30 分钟；`wait` 子命令打印单行进度（`status / stage / progress`），不要每次打印完整 JSON。
5. **Node 运行时约束**：`ELECTRON_RUN_AS_NODE=1` 下脚本是纯 Node 环境——**不能** `require('electron')`、无 DOM；只用内置 API（`fetch`/`FormData`/`Blob`/`fs`），要求客户端 Electron 内置 Node ≥ 18（现代 Electron 均满足，接入时验证一次版本即可）。
6. **终态≠成功**：`completed_with_warnings` 要提示用户检查告警页与失败 diagram；`failed` 时引导拉 `events` 接口定位失败页面。
7. **SVG 预览安全**：如未来在客户端预览 diagram SVG，沿用服务端的净化策略（`Content-Security-Policy: default-src 'none'`，不在不可信页面内联渲染）。
