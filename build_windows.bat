@echo off
chcp 65001 >nul
rem ============================================
rem  项目启动精灵 · Windows 单文件打包脚本
rem  编码铁律：UTF-8 无 BOM + CRLF 行尾；chcp 65001 必须先于任何中文字符执行，二者缺一即碎行
rem  产物: dist\项目启动精灵.exe （约 10~15MB）
rem ============================================
setlocal

rem 构建前检查：exe 在跑就先提示关掉（docs/06 验收 #7）
tasklist /FI "IMAGENAME eq 项目启动精灵.exe" 2>nul | find /I "项目启动精灵.exe" >nul
if %errorlevel%==0 (
  echo [!] 检测到 项目启动精灵.exe 正在运行，请先关闭再打包。
  pause
  exit /b 1
)

python -m pip install -r requirements.txt
python -m pip install pyinstaller

python -m PyInstaller ^
  --onefile ^
  --noconsole ^
  --clean ^
  --name 项目启动精灵 ^
  main.py

echo.
echo 打包完成: dist\项目启动精灵.exe
echo 首次运行会在 exe 旁边生成 profiles.json / logs\
pause
