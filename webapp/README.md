# BINGO MAP 補資料工具 — 網頁雛形

包著`bingomap` core的一個最小網頁介面，流程對應原始需求：開網頁 → 輸入資訊 → 產生空白骨架 →
點選/框選wafer座標 → 下載`.strate`。所有業務邏輯都留在`bingomap`裡，這裡只是HTTP+前端。

wafer bin資料（綠/粉紅那張圖）**已經可以自動讀取**：輸入LotNo+Barcode ID，`/api/frm`會用
`frm_reader.py`直接讀真實FRM二進位檔案（`{FRM_PATH}\{LotNo}\{barcode前2碼}\{barcode第3~6碼}`），
只有這個Flask process本身跑在連得到`F:\SMAP\FRM\`網路磁碟機的電腦上才會成功。連不到的話還是可以
用「貼上`x,y,bin`文字」手動輸入當備援，兩種方式最後都是同一份`waferCells`，後面流程完全一樣。

## 執行

**Windows雙擊執行**：直接雙擊 `webapp/launch_bingomap.bat`，第一次執行會自動裝套件，
之後每次雙擊就直接啟動（仿照`da_bot/launch_da_bot.bat`的做法）。

**手動執行**：
```
pip install -r webapp/requirements.txt
cd stock-dashboard-   # repo根目錄
python3 -m flask --app webapp.app run --port 5000
```

開瀏覽器到 `http://127.0.0.1:5000/`。

## 操作方式

1. 填基本資訊，按「產生空白骨架」
2. **Wafer Bin資料**：填LotNo+Barcode ID按「自動讀取FRM檔案」（能連F槽時）；連不到就改貼`x,y,bin`文字按「載入Wafer地圖(文字)」
3. 在網格上**點一下**加選單一顆，或**拖曳出一個矩形**自動依序選取範圍內所有綠色(bin1)的格子（跳過其他顏色跟已選過的），下方會即時顯示對應到基板的哪個位置
4. 已選數量會即時跟目標數量比對，不符合時是紅字
5. 數量對了之後按「產生檔案」，會直接下載`.strate`；數量不符會跳出跟WaferCoordinate.exe同樣文字的錯誤訊息

## 測試

```
python3 -m pytest webapp/tests/ -v
```

用Flask test client測API，也用Playwright實際開瀏覽器跑過一次完整流程（產生骨架→框選→
下載檔案），確認產出的檔案內容正確。

## 視覺設計

套用了使用者提供的另一套內部工具（ESEC 2100 STRATE補檔/座標偏移點除工具）的設計語言：深色漸層
Hero橫幅、步驟流程徽章(依操作進度顯示done/active)、卡片分區、notice提示框、色塊圖例。CSS變數
(`--blue`/`--green`等)照抄那套工具的配色。

## 尚未做的

- 「複製既有.strate為範本」模式
- 疊層(`DIE_INFO_OTHER_LAYER_*`)在UI上還沒有對應介面，`bingomap`核心也還沒串（見主README）
