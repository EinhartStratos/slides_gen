#!/usr/bin/env node
/*
 * slides_client.js —— slides_gen_server 薄客户端（纯 Node 内置 API，零外部依赖）
 *
 * 运行方式：
 *   node slides_client.js <command> [args]
 *   ELECTRON_RUN_AS_NODE=1 <electron-exe> slides_client.js <command> [args]
 *
 * 环境变量（由桌面客户端注入；脚本只读取，禁止打印其值）：
 *   OPENAI_API_KEY    LLM API Key（→ 请求头 X-LLM-API-Key；csas parse 接口的 token 头）
 *   SLIDES_EHR        用户 EHR 号（可选 → 请求头 X-User-EHR；parse 接口的 User 头）
 *   SLIDES_BASE_URL   slides_gen_server 地址（默认 http://127.0.0.1:8000/api/v1）
 *   SLIDES_PARSE_URL  文件解析接口（默认 http://82.187.34.98/csas/api/parse/file）
 *
 * 输出纪律：parse 结果与下载产物一律落盘，stdout 只输出摘要（字符数/路径/状态），
 * 防止超长文本进入模型上下文。
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const BASE_URL = (process.env.SLIDES_BASE_URL || 'http://127.0.0.1:8000/api/v1').replace(/\/+$/, '');
const PARSE_URL = process.env.SLIDES_PARSE_URL || 'http://82.187.34.98/csas/api/parse/file';
const API_KEY = process.env.OPENAI_API_KEY || process.env.SLIDES_API_KEY || '';
const EHR = process.env.SLIDES_EHR || process.env.EHR_NO || '';

// ---------- 基础工具 ----------

function die(msg, code = 1) {
  console.error(`[slides] ${msg}`);
  process.exit(code);
}

function out(obj) {
  console.log(JSON.stringify(obj, null, 2));
}

function usage() {
  console.log(`用法: slides <command> [args]

命令:
  health                                      服务连通性检查
  parse <file> [--out x.txt]                  调 csas 文件解析，纯文本落盘（不回显）
  create --requirement-file f.txt [opts]      创建 v4 Generation（separated_body_diagram）
        --targets body,diagrams  --template-id <id>  --custom "..."  --no-auto-compose
  status <generation_id>                      查聚合状态
  wait <generation_id> [--interval 30] [--timeout 1800]
                                              轮询到终态，逐行打印进度
  tasks [--generation-id id] [--status s] [--limit 20]
                                              列子任务
  task <task_id>                              子任务详情
  events <task_id> [--limit 20]               任务事件（排障）
  pages <task_id>                             分页状态（排障）
  download <generation_id> [--out dir]        下载 composed/body.pptx 与 diagrams.zip`);
}

function parseArgs(argv) {
  const o = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const eq = a.indexOf('=');
      if (eq > 0) {
        o[a.slice(2, eq)] = a.slice(eq + 1);
      } else {
        const nxt = argv[i + 1];
        if (nxt !== undefined && !nxt.startsWith('--')) { o[a.slice(2)] = nxt; i++; }
        else o[a.slice(2)] = true;
      }
    } else {
      o._.push(a);
    }
  }
  return o;
}

function slidesHeaders() {
  const h = {};
  if (API_KEY) h['X-LLM-API-Key'] = API_KEY;
  if (EHR) h['X-User-EHR'] = EHR;
  return h;
}

/** fetch 包装：连接失败时带目标地址退出，便于排障 */
async function fetchOrDie(url, options) {
  try {
    return await fetch(url, options);
  } catch (e) {
    const cause = e && e.cause ? ` (${e.cause.code || e.cause.message || e.cause})` : '';
    die(`连接失败 ${url}: ${e.message}${cause}`);
  }
}

/** 调 slides_gen_server，返回 ApiResponse.data；code!=0 或 HTTP 错误时退出 */
async function apiJson(method, urlPath, body) {
  const res = await fetchOrDie(BASE_URL + urlPath, {
    method,
    headers: { ...slidesHeaders(), ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let json = null;
  try { json = JSON.parse(text); } catch { /* 非 JSON 响应 */ }
  if (!res.ok) die(`HTTP ${res.status} ${method} ${urlPath}: ${(json && json.message) || text.slice(0, 300)}`);
  if (json && typeof json === 'object' && 'code' in json && json.code !== 0) {
    die(`业务错误 code=${json.code}: ${json.message}`);
  }
  return json && typeof json === 'object' && 'data' in json ? json.data : json;
}

function filenameFromDisposition(res, fallback) {
  const cd = res.headers.get('content-disposition') || '';
  let m = cd.match(/filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/);
  if (m) return decodeURIComponent(m[1].replace(/^"|"$/g, ''));
  m = cd.match(/filename\s*=\s*"?([^";]+)"?/);
  if (m) return m[1];
  return fallback;
}

/** 从 parse 响应里提取最长纯文本字段（兼容多种返回结构） */
function extractText(node, depth = 0) {
  if (depth > 4 || node == null) return null;
  if (typeof node === 'string') return node.trim() ? node : null;
  if (Array.isArray(node)) return node.map(x => extractText(x, depth + 1)).find(Boolean) || null;
  if (typeof node === 'object') {
    for (const k of ['text', 'content', 'markdown', 'result', 'data', 'body']) {
      if (node[k] !== undefined) {
        const t = extractText(node[k], depth + 1);
        if (t) return t;
      }
    }
  }
  return null;
}

// ---------- 命令实现 ----------

async function cmdHealth() {
  out(await apiJson('GET', '/health'));
}

async function cmdParse(args) {
  const file = args._[0];
  if (!file) die('用法: slides parse <file> [--out x.txt]');
  if (!API_KEY) die('缺少 OPENAI_API_KEY 环境变量');
  if (!fs.existsSync(file)) die(`文件不存在: ${file}`);

  const fd = new FormData();
  fd.append('file', new Blob([fs.readFileSync(file)]), path.basename(file));
  fd.append('fileId', crypto.randomUUID());

  const headers = { token: API_KEY };
  if (EHR) headers['User'] = EHR;

  const res = await fetchOrDie(PARSE_URL, { method: 'POST', headers, body: fd });
  const raw = await res.text();
  if (!res.ok) die(`HTTP ${res.status} parse: ${raw.slice(0, 300)}`);

  // 响应可能是 JSON 包装也可能是纯文本；提取文本部分
  let text = raw;
  let json = null;
  try { json = JSON.parse(raw); } catch { /* 纯文本响应 */ }
  if (json && typeof json === 'object') {
    if ('code' in json && Number(json.code) !== 0) die(`解析失败 code=${json.code}: ${json.message || ''}`);
    const found = extractText(json.data !== undefined ? json.data : json);
    if (found) text = found;
  }

  const outFile = path.resolve(args.out || `${path.basename(file)}.txt`);
  fs.writeFileSync(outFile, text, 'utf8');
  // 只回显摘要，不回显正文
  out({ ok: true, source: path.resolve(file), out: outFile, chars: text.length });
}

async function cmdCreate(args) {
  const reqFile = args['requirement-file'] || args._[0];
  if (!reqFile) die('用法: slides create --requirement-file <txt> [--targets body,diagrams] [--template-id X] [--custom "..."] [--no-auto-compose]');
  if (!fs.existsSync(reqFile)) die(`需求文件不存在: ${reqFile}`);
  const requirementText = fs.readFileSync(reqFile, 'utf8');
  if (!requirementText.trim()) die('需求文本为空');
  if (requirementText.length > 100000) die(`需求文本 ${requirementText.length} 字符，超过上限 100000`);

  const targets = String(args.targets || 'body,diagrams').split(',').map(s => s.trim()).filter(Boolean);
  const body = {
    generation_mode: 'separated_body_diagram',
    targets,
    requirement_text: requirementText,
    auto_compose: args['no-auto-compose'] ? false : true,
  };
  if (args['template-id']) body.template_id = args['template-id'];
  if (args.custom) body.custom_requirements = args.custom;

  const data = await apiJson('POST', '/generations', body);
  out({
    generation_id: data.generation_id,
    status: data.status,
    body_task_id: data.body_task_id,
    diagram_task_id: data.diagram_task_id,
    compose_task_id: data.compose_task_id,
  });
}

function compactSummary(d) {
  return {
    generation_id: d.generation_id,
    status: d.status,
    body_status: d.body_status,
    diagram_status: d.diagram_status,
    compose_status: d.compose_status,
    kept_page_count: d.kept_page_count,
    skipped_page_count: d.skipped_page_count,
    diagram_count: d.diagram_count,
    has_body_download: d.has_body_download,
    has_composed_download: d.has_composed_download,
    has_diagram_downloads: d.has_diagram_downloads,
    warning_message: d.warning_message,
    error_message: d.error_message,
  };
}

async function cmdStatus(args) {
  const id = args._[0];
  if (!id) die('用法: slides status <generation_id>');
  out(compactSummary(await apiJson('GET', `/generations/${id}`)));
}

async function cmdWait(args) {
  const id = args._[0];
  if (!id) die('用法: slides wait <generation_id> [--interval 30] [--timeout 1800]');
  const intervalMs = Math.max(5, parseInt(args.interval || '30', 10)) * 1000;
  const timeoutMs = parseInt(args.timeout || '1800', 10) * 1000;
  const t0 = Date.now();

  for (;;) {
    const d = await apiJson('GET', `/generations/${id}`);
    const ts = new Date().toTimeString().slice(0, 8);
    console.log(`${ts} status=${d.status} body=${d.body_status} diagram=${d.diagram_status} compose=${d.compose_status} kept=${d.kept_page_count ?? '-'} skipped=${d.skipped_page_count ?? '-'}`);

    if (d.status === 'completed' || d.status === 'completed_with_warnings') {
      console.log(`[slides] 终态: ${d.status}${d.warning_message ? ` 警告: ${d.warning_message}` : ''}`);
      console.log(`[slides] 下一步: slides download ${id} --out <目录>`);
      process.exit(0);
    }
    if (d.status === 'failed') {
      console.log(`[slides] 失败: ${d.error_message || '未知错误'}`);
      console.log(`[slides] 排查: slides tasks --generation-id ${id}，再 slides events <task_id>`);
      process.exit(2);
    }
    if (Date.now() - t0 > timeoutMs) {
      die(`等待超时（>${args.timeout || 1800}s），任务仍在进行；可再次执行 wait 继续跟进`, 3);
    }
    await new Promise(r => setTimeout(r, intervalMs));
  }
}

async function cmdTasks(args) {
  const q = new URLSearchParams();
  if (args['generation-id']) q.set('generation_id', args['generation-id']);
  if (args.status) q.set('status', args.status);
  q.set('limit', args.limit || '20');
  const list = await apiJson('GET', `/tasks?${q}`);
  if (!Array.isArray(list) || !list.length) { console.log('(无任务)'); return; }
  for (const t of list) {
    console.log(`${t.task_id}  ${t.task_type}  ${t.status}  ${t.progress ?? 0}%  ${t.current_stage || ''}`);
  }
}

async function cmdTask(args) {
  const id = args._[0];
  if (!id) die('用法: slides task <task_id>');
  const d = await apiJson('GET', `/tasks/${id}`);
  out({
    task_id: d.task_id, task_type: d.task_type, generation_id: d.generation_id,
    status: d.status, current_stage: d.current_stage, progress: d.progress,
    error_message: d.error_message, created_at: d.created_at, completed_at: d.completed_at,
  });
}

async function cmdEvents(args) {
  const id = args._[0];
  if (!id) die('用法: slides events <task_id> [--limit 20]');
  const q = new URLSearchParams({ limit: args.limit || '20' });
  const list = await apiJson('GET', `/tasks/${id}/events?${q}`);
  if (!Array.isArray(list) || !list.length) { console.log('(无事件)'); return; }
  for (const e of list) {
    console.log(`${e.created_at || ''}  ${e.event_type}  ${e.event_stage || ''}  p${e.page_no ?? '-'}  ${e.event_message || ''}`);
  }
}

async function cmdPages(args) {
  const id = args._[0];
  if (!id) die('用法: slides pages <task_id>');
  const list = await apiJson('GET', `/tasks/${id}/pages`);
  if (!Array.isArray(list) || !list.length) { console.log('(无分页)'); return; }
  for (const p of list) {
    console.log(`p${p.page_no}  ${p.page_name || ''}  ${p.status}  ${p.skip_reason || ''}`);
  }
}

async function cmdDownload(args) {
  const id = args._[0];
  if (!id) die('用法: slides download <generation_id> [--out dir]');
  const outDir = path.resolve(args.out || '.');
  fs.mkdirSync(outDir, { recursive: true });

  const s = await apiJson('GET', `/generations/${id}`);
  const jobs = [];

  // 组装产物：优先用 summary 里的 artifact_id，缺失时回退到 compose 任务产物列表
  if (s.has_composed_download) {
    let artifactId = s.composed_pptx_artifact_id;
    if (!artifactId && s.compose_task_id) {
      const arts = await apiJson('GET', `/tasks/${s.compose_task_id}/artifacts`);
      const a = (arts || []).find(x => x.artifact_type === 'composed_pptx' && x.is_final)
        || (arts || []).find(x => x.artifact_type === 'composed_pptx');
      if (a) artifactId = a.artifact_id;
    }
    if (s.compose_task_id && artifactId) {
      jobs.push([`/tasks/${s.compose_task_id}/artifacts/${artifactId}/download`, 'composed.pptx']);
    }
  }
  if (s.has_body_download) jobs.push([`/generations/${id}/body/download`, 'body.pptx']);
  if (s.has_diagram_downloads) jobs.push([`/generations/${id}/diagrams/download`, 'diagrams.zip']);

  if (!jobs.length) die(`当前没有可下载产物（status=${s.status}）`);

  const saved = [];
  for (const [urlPath, fallback] of jobs) {
    const res = await fetchOrDie(BASE_URL + urlPath, { headers: slidesHeaders() });
    if (!res.ok) die(`HTTP ${res.status} 下载失败: ${urlPath}`);
    const name = filenameFromDisposition(res, fallback);
    const buf = Buffer.from(await res.arrayBuffer());
    const fp = path.join(outDir, name);
    fs.writeFileSync(fp, buf);
    saved.push({ file: fp, bytes: buf.length });
  }
  out({ generation_id: id, saved });
}

// ---------- 入口 ----------

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  const args = parseArgs(rest);
  switch (cmd) {
    case 'health': return cmdHealth();
    case 'parse': return cmdParse(args);
    case 'create': return cmdCreate(args);
    case 'status': return cmdStatus(args);
    case 'wait': return cmdWait(args);
    case 'tasks': return cmdTasks(args);
    case 'task': return cmdTask(args);
    case 'events': return cmdEvents(args);
    case 'pages': return cmdPages(args);
    case 'download': return cmdDownload(args);
    case undefined:
    case 'help':
    case '--help': return usage();
    default: die(`未知命令: ${cmd}（执行 help 查看用法）`);
  }
}

main().catch(e => die(e && e.message ? e.message : String(e)));
