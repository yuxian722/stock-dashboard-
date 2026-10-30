"""PyInstaller進入點——打包成桌機.exe專用，2026/10/30使用者要求「改成
桌機版可以使用」(跟AskUserQuestion當面確認過，是指「打包成不用裝Python
的執行檔(.exe)」，不是桌面捷徑、也不是別種意思)。

跟`webapp/launch_simple_bingo_viewer.py`(開發機用的.bat啟動器)刻意分成
兩支不同檔案，不是同一支改兩用：
- 開發機啟動器會檢查Flask裝了沒、沒裝就現場`pip install`——這在真正打包
  好的.exe裡完全沒必要(flask本來就已經被PyInstaller打包進執行檔裡)，
  硬塞這段邏輯只會讓.exe嘗試連網路pip install，離線的現場電腦反而會
  因為連不到PyPI而卡住或報錯。
- 開發機啟動器把repo根目錄插進`sys.path`——PyInstaller打包後執行時
  `sys.path`已經包含bundle本身，不需要也不能這樣做。

實際的Flask app/路由邏輯全部在`webapp/simple_bingo_viewer.py`本體(連同
frozen模式的templates/static/下載紀錄CSV路徑判斷，見該檔案`sys.frozen`
那段)，這支進入點只負責「用PyInstaller能理解的方式啟動它」。
"""
import sys
import threading
import time
import webbrowser

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PORT = 5050
URL = f"http://127.0.0.1:{PORT}/"


def _open_browser_after_delay():
    time.sleep(1.2)
    webbrowser.open(URL)


if __name__ == "__main__":
    print("[提示] 啟動 SECS LOG BINGO MAP 檢視器...")
    print(f"[提示] 瀏覽器即將自動開啟 {URL}（沒有自動開的話手動貼這個網址）")
    print("[提示] 要停止請直接關閉這個視窗")
    print("=" * 50)

    threading.Thread(target=_open_browser_after_delay, daemon=True).start()

    from webapp.simple_bingo_viewer import app

    app.run(port=PORT)
