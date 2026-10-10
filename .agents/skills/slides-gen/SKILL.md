---
name: slides-gen
description: 调用 slides_gen_server 生成 PPT——文件解析成需求文本 → 创建 v4 生成 → 轮询进度 → 下载 PPTX/SVG 产物
argument-hint: "<需求描述或需求文件路径>"
allowed-tools:
  - exec
  - read
triggers:
  - user
  - model
---

# PPT 生成技能（slides_gen_server）

把用户需求变成 PPTX 文件。服务端是**异步任务 API**：提交后立即返回 `generation_id`，
后台耗时 10~20 分钟，需要轮询进度、终态后下载产物。所有 LLM 调用都在服务端完成，
本技能只负责编排 HTTP 调用，不要自己生成 PPT 内容。

## 运行方式

脚本位于本技能 `scripts/` 子目录：`scripts/slides_client.js`（纯 Node 内置 API，无外部依赖）。
桌面客户端是 Electron 应用（实测 `D:\efp\aixcoding.exe`，Electron 36.0.0 / 内置 Node 22.14.0，
满足 Node ≥ 18），设 `ELECTRON_RUN_AS_NODE=1` 后 exe 等价于 `node`。

**Windows 关键坑**：Electron exe 是 GUI 子系统程序，**stdout 不直连控制台**——
直接执行能看到的效果是"没有任何输出（其实在跑）"。必须重定向到文件再读回。
本技能的包装脚本已处理好这件事（`slides.sh` 在 Windows 下用「后台执行 + tail -f 实时回显」，

Linux/macOS 下 stdout 原生直连、直接 exec），**优先用包装脚本，不要直接调 exe**。

按顺序尝试以下入口，第一个能跑通 `health` 的即可用：

| 入口 | 用法 |
|---|---|
| 1. `slides`（PATH，客户端若提供则优先） | `slides <cmd>` |
| 2. bash 包装脚本（Devin exec 默认 Git Bash，**首选**） | `bash <skill目录>/scripts/slides.sh <cmd>` |
| 3. cmd 包装脚本 | `cmd /c <skill目录>\scripts\slides.cmd <cmd>` |
| 4. 纯 node（环境自有时） | `node <skill目录>/scripts/slides_client.js <cmd>` |

包装脚本按 `$SLIDES_EXE` → 自动定位的顺序找客户端 exe，**不写死安装路径**：
- Windows：`scripts/find_client_exe.ps1` —— 先沿进程树找祖先中的 Electron 客户端
  （客户端拉起 Agent 时它就是祖先进程），再兜底枚举带 `resources\app.asar` 特征的进程；
- Linux/Unix：`scripts/find_client_exe.sh` —— 同样两级策略，走 `/proc/<pid>/exe` +
  `resources/app.asar` 特征判定。

两级均优先名字含 `aixcoding` 的进程。自动定位失败时，手工定位后
`export SLIDES_EXE=<路径>` 重试：

```powershell
# Windows：查正在运行的客户端进程（最快；Git Bash 下用 powershell -Command "..." 执行）
Get-CimInstance Win32_Process -Filter "Name like '%aixcoding%'" |
  Select-Object -ExpandProperty ExecutablePath
```

```bash
# Linux：枚举带 Electron 特征的进程
for e in /proc/[0-9]*/exe; do
  p=$(readlink -f "$e" 2>/dev/null) && [ -f "$(dirname "$p")/resources/app.asar" ] && echo "$p"
done
```

先执行 `health` 验证连通，返回 `{"status":"ok",...}` 再继续。

## 环境变量（由桌面客户端注入，脚本自行读取）

| 变量 | 用途 |
|---|---|
| `OPENAI_API_KEY` | LLM API Key → `X-LLM-API-Key` 头 / parse 接口 `token` 头 |
| `SLIDES_EHR` | EHR 号 → `X-User-EHR` 头 / parse `User` 头（可选） |
| `SLIDES_BASE_URL` | 服务地址（默认 `http://127.0.0.1:8000/api/v1`） |
| `SLIDES_EXE` | 客户端 Electron exe 路径（可选覆盖；缺省时包装脚本自动定位正在运行的客户端） |
| `SLIDES_PARSE_URL` | 文件解析接口（默认 `http://82.187.34.98/csas/api/parse/file`） |

**禁止读取、打印、回显任何凭据值；不要向用户索要凭据。**

## 标准工作流

1. **准备需求文本**（服务端上限 10 万字符，必须走文件，不要把全文写进命令行或回复）：
   - 用户给了 docx/pdf/xlsx/pptx 等源文件 → `slides parse <文件>`，得到 `<文件名>.txt`
     （解析结果不回显，脚本只输出字符数与落盘路径）；
   - 用户给了 txt/md → 直接作为 requirement 文件；
   - 用户只有口头描述 → 先把整理后的完整需求写入一个 txt 文件。
2. **创建生成**：
   `slides create --requirement-file <txt> [--targets body,diagrams] [--template-id <id>] [--custom "附加要求"] [--no-auto-compose]`
   → 记下返回的 `generation_id`。
3. **跟踪进度**：
   - 首选 `slides wait <generation_id>`（默认 30s 轮询、30 分钟超时，逐行打印进度）；
   - 若执行环境不支持长命令，改用 `slides status <generation_id>` 每隔 30~60s 查一次；
   - 每次拿到进度后向用户简报（如“正文生成中，图形等待中”）。
4. **下载产物**：终态后 `slides download <generation_id> --out <目录>`，
   产物为 `composed.pptx`（组装后成品）、`body.pptx`（纯正文）、`diagrams.zip`（全部图形 SVG）。
   把保存的绝对路径告诉用户，不要复述文件内容。
5. **异常处理**：
   - `completed_with_warnings`：部分图形失败但成品可用，提示用户并用第 6 步排查；
   - `failed`：`slides tasks --generation-id <id>` 找到失败子任务 → `slides events <task_id>` 看错误 → `slides pages <task_id>` 定位失败页，再向用户汇报原因。

## 命令速查

| 命令 | 说明 |
|---|---|
| `slides health` | 服务连通性检查 |
| `slides parse <file> [--out x.txt]` | 调 csas 文件解析接口，纯文本落盘（不回显） |
| `slides create --requirement-file f.txt [opts]` | 创建 v4 Generation（新模式） |
| `slides status <generation_id>` | 查聚合状态（body/diagram/compose 三子状态） |
| `slides wait <generation_id> [--interval 30] [--timeout 1800]` | 轮询到终态，逐行打印进度 |
| `slides tasks [--generation-id id]` | 列子任务 |
| `slides task <task_id>` | 子任务详情 |
| `slides events <task_id> [--limit 20]` | 任务事件（排障） |
| `slides pages <task_id>` | 分页状态（排障） |
| `slides download <generation_id> [--out dir]` | 下载全部可得产物 |

## 纪律

- 只走 v4 `generations` 接口；**不要**用 legacy `POST /tasks` 创建任务。
- parse 结果、需求文本、产物内容**一律不回显**到对话中；需要引用时用文件路径。
- 不要修改 `scripts/slides_client.js`；接口变化应更新服务端或本技能说明。
