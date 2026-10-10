@echo off
rem slides.cmd —— ELECTRON_RUN_AS_NODE 包装（cmd 版）
rem
rem Windows 坑：Electron exe 是 GUI 子系统程序，stdout 不直连控制台，
rem 必须重定向到文件再回显，否则调用方看不到任何输出。
rem
rem exe 查找顺序：%%SLIDES_EXE%% → find_client_exe.ps1 自动定位正在运行的客户端
setlocal
set ELECTRON_RUN_AS_NODE=1

if "%SLIDES_EXE%"=="" (
  for /f "usebackq delims=" %%P in (`powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0find_client_exe.ps1" 2^>nul`) do set "SLIDES_EXE=%%P"
)
if "%SLIDES_EXE%"=="" (
  echo [slides] 未找到正在运行的客户端 Electron exe；请 set SLIDES_EXE=^<路径^> 后重试 1>&2
  exit /b 127
)
if not exist "%SLIDES_EXE%" (
  echo [slides] SLIDES_EXE 指向的文件不存在: %SLIDES_EXE% 1>&2
  exit /b 127
)

set "OUT=%TEMP%\slides_o_%RANDOM%%RANDOM%.txt"
set "ERR=%TEMP%\slides_e_%RANDOM%%RANDOM%.txt"
"%SLIDES_EXE%" "%~dp0slides_client.js" %* >"%OUT%" 2>"%ERR%"
set CODE=%ERRORLEVEL%
type "%OUT%"
type "%ERR%" 1>&2
del /f /q "%OUT%" "%ERR%" >nul 2>&1
endlocal & exit /b %CODE%
