#!/usr/bin/env bash
# slides.sh —— ELECTRON_RUN_AS_NODE 包装：把桌面端 Electron exe 当 node 调 slides_client.js
#
# Windows 坑：Electron exe 是 GUI 子系统程序，stdout 不直连控制台，
# 所以 Windows 下改为「后台执行 + 重定向到文件 + tail -f 实时回显」，
# 保证 wait 子命令的进度行也能实时看到。
# Linux/macOS 没有这个问题，直接 exec，stdout 原生直连。
#
# exe 查找顺序：$SLIDES_EXE → 自动定位（Windows: find_client_exe.ps1 / 其他: find_client_exe.sh）
set -u
export ELECTRON_RUN_AS_NODE=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXE="${SLIDES_EXE:-}"

is_windows() {
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) return 0 ;;
    *) return 1 ;;
  esac
}

if [ -z "$EXE" ]; then
  if is_windows; then
    EXE="$(powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$SCRIPT_DIR/find_client_exe.ps1" 2>/dev/null | tr -d '\r' | head -n1)"
  else
    EXE="$(bash "$SCRIPT_DIR/find_client_exe.sh" 2>/dev/null | head -n1)"
  fi
fi

if [ -z "$EXE" ] || [ ! -f "$EXE" ]; then
  echo "[slides] 未找到正在运行的客户端 Electron 主程序；请 export SLIDES_EXE=<路径> 后重试" >&2
  exit 127
fi

if is_windows; then
  OUT="$(mktemp)"; ERR="$(mktemp)"
  "$EXE" "$SCRIPT_DIR/slides_client.js" "$@" >"$OUT" 2>"$ERR" &
  PID=$!
  tail -f "$OUT" & T1=$!
  tail -f "$ERR" >&2 & T2=$!
  wait "$PID"; CODE=$?
  sleep 0.3   # 等 tail 冲完尾部输出
  kill "$T1" "$T2" 2>/dev/null
  wait "$T1" "$T2" 2>/dev/null
  rm -f "$OUT" "$ERR"
  exit $CODE
else
  exec "$EXE" "$SCRIPT_DIR/slides_client.js" "$@"
fi
