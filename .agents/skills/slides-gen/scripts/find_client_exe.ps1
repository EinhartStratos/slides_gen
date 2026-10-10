# find_client_exe.ps1 —— 定位当前正在运行的桌面客户端（Electron）主程序路径
#
# 策略1（最可靠）：沿进程树向上找祖先——桌面端拉起 Agent/shell 时它就是祖先进程，
#                  祖先 exe 同目录存在 resources\app.asar 即判定为客户端。
# 策略2（兜底）：枚举所有运行进程中带 Electron 特征的（优先名字含 aixcoding）。
# 输出：stdout 第一行为 exe 绝对路径；找不到时退出码 1、无输出。

$ErrorActionPreference = 'SilentlyContinue'
$procs = Get-CimInstance Win32_Process
$byPid = @{}
foreach ($p in $procs) { if ($p.ProcessId) { $byPid[[int]$p.ProcessId] = $p } }

function Test-ElectronExe([string]$exePath) {
  return $exePath -and (Test-Path $exePath) -and `
    (Test-Path (Join-Path (Split-Path $exePath -Parent) 'resources\app.asar'))
}

# 策略1：祖先链
$cur = $byPid[[int]$PID]
while ($cur) {
  if (Test-ElectronExe $cur.ExecutablePath) { Write-Output $cur.ExecutablePath; exit 0 }
  $ppid = $cur.ParentProcessId
  $cur = if ($ppid -and $byPid.ContainsKey([int]$ppid)) { $byPid[[int]$ppid] } else { $null }
}

# 策略2：全部运行进程里带 Electron 特征的
$cands = foreach ($p in $procs) { if (Test-ElectronExe $p.ExecutablePath) { $p.ExecutablePath } }
$cands = $cands | Sort-Object -Unique
if ($cands) {
  $hit = $cands | Where-Object { $_ -match 'aixcoding' } | Select-Object -First 1
  if (-not $hit) { $hit = $cands[0] }
  Write-Output $hit
  exit 0
}
exit 1
