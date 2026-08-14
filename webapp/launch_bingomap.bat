@echo off
chcp 65001 >nul
cd /d "%~dp0\.."

echo [提示] 檢查套件安裝狀態...
python -m pip show flask >nul 2>&1
if errorlevel 1 (
    echo [提示] 首次執行，安裝需要的套件...
    python -m pip install -r webapp\requirements.txt
    if errorlevel 1 (
        echo [錯誤] 套件安裝失敗，請確認本機有Python、pip能連到網路
        pause
        exit /b 1
    )
)

echo [提示] 啟動 BINGO MAP 補資料工具...
echo [提示] 啟動後請開瀏覽器到 http://127.0.0.1:5000/
echo [提示] 要停止請關閉這個視窗，或按 Ctrl+C
echo ==================================================
python -m flask --app webapp.app run --port 5000

pause
