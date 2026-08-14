# bingomap

BINGO MAP補資料工具的核心邏輯（`.strate`檔案格式讀寫 + 空白檔案產生器）。
目標：開軟體 → 輸入資訊 → 跑出mapping圖 → 點座標 → 出`.strate`，桌面版/網頁版共用這份core，不重寫兩套邏輯。

## 目前進度

**Phase 1a：格式與空白產生器**
- `strate.py`：`.strate`檔案的parse/序列化，格式已用真實範例檔案做byte-for-byte round-trip驗證
- **疊層(一次上兩顆)支援**：`StrateFile.other_layer_die_info`——當機台一次動作同時吸取兩顆die疊在同一個基板位置時，檔案裡除了原本`[DIE_INFO_BEG]/[END]`那段，還會多一段`[DIE_INFO_OTHER_LAYER_BEG]/[END]`裝第二層資料，每列最後一欄(`f9`)是層數，兩段各自的層數不同(例如一段全部是2、另一段全部是1)。已用真實雙層範例檔的表頭+頭尾幾筆資料驗證結構；單層檔案(沒有第二段)行為不受影響，原本的byte-for-byte驗證仍然通過
- `blank_generator.py`：依標頭參數（跟EAS「Create Golden SubstrateMap」表單同一組欄位）自動產生空白骨架，取代手動登入EAS網頁系統那一步。支援LOC(從1:1起)/EPOXY(從0:0起)兩種基板編號慣例
- **機型(`machine_type`)支援DB/ESEC兩種排列規則**：2026/08/14用真實內部信件(DB vs ESEC 2100SD同產品比對)驗證——DB從`0:0`開始每欄遞增；ESEC從**最後一格**`COLUMN-1:ROW-1`開始、欄序反過來、每換欄列的方向蛇形交替。這兩套規則絕對不能混用(SOP原文警告COPY錯機型資料會讓BINGO MAP檔案異常)，其他機型(CM700等)排列規則尚未驗證，不要假設沿用這兩套之一

**Phase 1b：座標填入引擎**
- `assignment.py`：把操作員選的wafer座標(`DiePick`)填進空白骨架，未被選到的基板位置整筆省略、存活的DIE重新編號、時間戳依起始時間+間隔秒數遞增。數量防呆訊息(`DieCountMismatch`)沿用WaferCoordinate.exe對話框的原文——選多了「需減少N顆」、選少了「還需選擇N顆」（兩個方向用字不對稱，已用真實對話框截圖驗證）
- 已驗證：把真實範例檔的75筆實際選點依原順序餵回`generate_blank`+`assign_dies`，結構(座標、bin、順序)可完全重現

**Phase 1c：Mapping Lot查詢**
- `mapping_service.py`：呼叫ChipMOS內部SOAP服務(`http://tneas.tn.chipmos.com.tw:10000/Mapping/Service.asmx`)的`GetMappingLotNoByAssyLot`，依ASSY_LOT自動查出對應的MAPPING_LOT清單（一個母批號可能對應多片wafer/多筆MAPPING_LOT）
- 這個網址只有ChipMOS內網連得到，所以這裡只負責組請求/解析回應（單元測試用真實回應驗證），實際HTTP呼叫要在內網環境跑
- **關鍵眉角（已用真實環境驗證）**：查詢要用**去掉子批次尾碼的母批號**（例如`V32AWCW`，不是`V32AWCW01`或`V32AWCW02`）——用子批次全碼查詢，即使該子批當下確實在產線RUNNING，也會查無資料
- 同一份SOAP服務裡的`GetAOIBinData`原本以為是wafer逐顆bin資料的來源，但用正確格式的母批號實測仍回`STATUS=NG`，判斷不是我們要的API，已停損，不再追

**Phase 1d：框選揀選**
- `wafer_map.py`：`WaferBinMap`存wafer上每個座標的bin值，`scan_rectangle()`模擬框選矩形時的自動掃描（依序取bin1、跳過bin7跟沒資料的格子），`build_picks_from_scan()`把掃描結果跟要填入的基板位置清單依序配對成`DiePick`
- `DiePick.from_xy()`：貼合實際介面的X/Y/Bin表格輸入形狀（分開的X、Y欄位），不用自己拼"x:y"字串
- 掃描順序（column-major，X由小到大、每欄內Y由小到大）目前是合理預設，還沒有完整真實範例逐格驗證跟原軟體是否一致——但這不影響輸出正確性，因為`assign_dies()`是照給定順序配對，掃描順序只影響清單好不好讀

**Phase 2：網頁UI雛形**
- 見`../webapp/`——用Flask把上面這些邏輯包成能實際操作的網頁，流程：填資訊→產生空白骨架→貼wafer bin資料→點選/框選座標→產生並下載`.strate`。已用Playwright實際跑過瀏覽器驗證。

## 尚未實作

- **wafer die mapping圖的真正資料來源**：綠色(bin1)/粉紅(bin7)逐顆die的資料從哪裡自動抓進來，目前確定沿用現有軟體(WaferCoordinate.exe / 目視檢查 / P_map_image.exe)的下載/查詢方式，這步驟先保留人工操作，不強求自動化——只要有一份「座標→bin值」的資料餵進`WaferBinMap`，後面全部都已經串好了
- 疊層(`other_layer_die_info`)在`blank_generator.py`/`assignment.py`還沒有對應的產生/填入邏輯，`strate.py`的讀寫格式支援了但還不能真的補疊層資料
- ESEC以外、DB以外的其他機型(CM700等)排列規則尚未驗證
- 「複製既有.strate為範本」模式

## 執行測試

```
pip install pytest
python3 -m pytest bingomap/tests/ -v
```
