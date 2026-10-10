#!/usr/bin/env bash
# find_client_exe.sh —— 定位当前正在运行的桌面客户端（Electron）主程序路径（Linux/Unix 版）
#
# 策略1（最可靠）：沿 /proc 进程树向上找祖先——桌面端拉起 Agent/shell 时它就是祖先进程，
#                  祖先 exe 同目录存在 resources/app.asar 即判定为客户端。
# 策略2（兜底）：枚举 /proc/*/exe 中带 Electron 特征的（优先名字含 aixcoding）。
# 输出：stdout 第一行为 exe 绝对路径；找不到时退出码 1、无输出。
set -u

is_electron_exe() {
  local exe="$1"
  [ -n "$exe" ] && [ -f "$exe" ] && [ -f "$(dirname "$exe")/resources/app.asar" ]
}

exe_of()  { readlink -f "/proc/$1/exe" 2>/dev/null; }
ppid_of() { awk '/^PPid:/{print $2}' "/proc/$1/status" 2>/dev/null; }

# 策略1：祖先链
pid=$$
while [ -n "$pid" ] && [ "$pid" != "0" ] && [ "$pid" != "1" ]; do
  exe="$(exe_of "$pid")"
  if is_electron_exe "$exe"; then printf '%s\n' "$exe"; exit 0; fi
  pid="$(ppid_of "$pid")"
done

# 策略2：全部运行进程里带 Electron 特征的，aixcoding 优先
best=""
for e in /proc/[0-9]*/exe; do
  exe="$(readlink -f "$e" 2>/dev/null)" || continue
  if is_electron_exe "$exe"; then
    case "$exe" in
      *aixcoding*) printf '%s\n' "$exe"; exit 0 ;;
    esac
    [ -z "$best" ] && best="$exe"
  fi
done
[ -n "$best" ] && { printf '%s\n' "$best"; exit 0; }
exit 1
