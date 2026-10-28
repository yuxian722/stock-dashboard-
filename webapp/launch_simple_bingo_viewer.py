"""
SECS LOG BINGO MAP 檢視器（簡化版）- 一鍵啟動器

雙擊 launch_simple_bingo_viewer.bat 啟動。跟 launch_bingomap.py 用同一套
做法(中文訊息全部放Python處理，.bat只負責cd+呼叫python，理由見那支檔案
的docstring)，但這支額外多做一件事：啟動後自動開瀏覽器——使用者2026/
10/28明確要求「執行檔點進去就開啟這個軟體」，不要再多一步手動開瀏覽器
貼網址。

用獨立的埠號(5050，不是bingomap主程式的5000)，兩個工具可以同時開著跑
互不衝突。
"""
import os
import subprocess
import sys
import threading
import time
import webbrowser

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

PORT = 5050
URL = f"http://127.0.0.1:{PORT}/"


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


def _open_browser_after_delay():
    # Flask's app.run() blocks the main thread — open the browser from a
    # short-lived background thread instead, timed to give the server a
    # moment to actually start listening before the browser tries to
    # connect.
    time.sleep(1.2)
    webbrowser.open(URL)


if __name__ == "__main__":
    os.chdir(REPO_ROOT)
    _ensure_flask_installed()

    print("[提示] 啟動 SECS LOG BINGO MAP 檢視器...")
    print(f"[提示] 瀏覽器即將自動開啟 {URL}（沒有自動開的話手動貼這個網址）")
    print("[提示] 要停止請關閉這個視窗，或按 Ctrl+C")
    print("=" * 50)

    threading.Thread(target=_open_browser_after_delay, daemon=True).start()

    from webapp.simple_bingo_viewer import app

    app.run(port=PORT)
