# BINGO MAP 補資料工具 — 網頁雛形

包著`bingomap` core的一個最小網頁介面，流程對應原始需求：開網頁 → 輸入資訊 → 產生空白骨架 →
點選/框選wafer座標 → 下載`.strate`。所有業務邏輯都留在`bingomap`裡，這裡只是HTTP+前端。

wafer bin資料（綠/粉紅那張圖）目前還沒有自動來源，先用「貼上`x,y,bin`文字」代替——之後要換成
真實資料來源，只需要換掉這一步的輸入方式，後面`/api/generate`完全不用動。

## 執行

```
pip install -r webapp/requirements.txt
cd stock-dashboard-   # repo根目錄
python3 -m flask --app webapp.app run --port 5000
```

開瀏覽器到 `http://127.0.0.1:5000/`。

## 操作方式

1. 填基本資訊，按「產生空白骨架」
2. 貼上wafer bin資料（每行`x,y,bin`），按「載入Wafer地圖」
3. 在網格上**點一下**加選單一顆，或**拖曳出一個矩形**自動依序選取範圍內所有綠色(bin1)的格子（跳過其他顏色跟已選過的）
4. 已選數量會即時跟目標數量比對，不符合時是紅字
5. 數量對了之後按「產生檔案」，會直接下載`.strate`；數量不符會跳出跟WaferCoordinate.exe同樣文字的錯誤訊息

## 測試

```
python3 -m pytest webapp/tests/ -v
```

用Flask test client測API，也用Playwright實際開瀏覽器跑過一次完整流程（產生骨架→框選→
下載檔案），確認產出的檔案內容正確。

## 尚未做的

- 真實wafer bin資料來源（目前手動貼文字）
- 「複製既有.strate為範本」模式
- 疊層(`DIE_INFO_OTHER_LAYER_*`)在UI上還沒有對應介面，`bingomap`核心也還沒串（見主README）
- 樣式/易用性只是堪用程度，還沒有精修
