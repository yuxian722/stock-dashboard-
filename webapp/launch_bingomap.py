"""
BINGO MAP 補資料工具 - 一鍵啟動器

雙擊 launch_bingomap.bat（或在repo根目錄執行 python webapp/launch_bingomap.py）
啟動網頁版。中文訊息全部放在這支Python檔案裡處理、不是放在.bat裡——
Windows批次檔直接寫中文字元常常會亂碼、把中文誤判成指令片段導致
「不是內部或外部命令」這種錯誤，比照da_bot/launch_da_bot.py +
launch_da_bot.bat的既有作法：.bat只負責cd+呼叫python，中文輸出跟所有
邏輯都交給Python處理。
"""
import os
import subprocess
import sys

# Windows主控台預設編碼常常印不出中文，這裡強制轉成utf-8輸出，encode
# 不了的字元用errors="replace"跳過，不要讓輸出問題把程式弄當掉。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)


def _ensure_flask_installed():
    try:
        import flask  # noqa: F401

        return
    except ImportError:
        pass
    print("[提示] 首次執行，安裝需要的套件(flask)...")
    requirements = os.path.join(REPO_ROOT, "webapp", "requirements.txt")
    result = subprocess.run([sys.executable, "-m", "pip", "install", "-r", requirements])
    if result.returncode != 0:
        print("[錯誤] 套件安裝失敗，請確認本機有網路、pip能連到PyPI")
        sys.exit(1)


if __name__ == "__main__":
    os.chdir(REPO_ROOT)
    _ensure_flask_installed()

    print("[提示] 啟動 BINGO MAP 補資料工具...")
    print("[提示] 啟動後請開瀏覽器到 http://127.0.0.1:5000/")
    print("[提示] 要停止請關閉這個視窗，或按 Ctrl+C")
    print("=" * 50)

    from webapp.app import app

    app.run(port=5000)
