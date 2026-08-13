# bingomap

BINGO MAP補資料工具的核心邏輯（`.strate`檔案格式讀寫 + 空白檔案產生器）。
目標：開軟體 → 輸入資訊 → 跑出mapping圖 → 點座標 → 出`.strate`，桌面版/網頁版共用這份core，不重寫兩套邏輯。

## 目前進度

**Phase 1a：格式與空白產生器**
- `strate.py`：`.strate`檔案的parse/序列化，格式已用真實範例檔案做byte-for-byte round-trip驗證
- `blank_generator.py`：依標頭參數（跟EAS「Create Golden SubstrateMap」表單同一組欄位）自動產生空白骨架，取代手動登入EAS網頁系統那一步。支援LOC(從1:1起)/EPOXY(從0:0起)兩種基板編號慣例

**Phase 1b：座標填入引擎**
- `assignment.py`：把操作員選的wafer座標(`DiePick`)填進空白骨架，未被選到的基板位置整筆省略、存活的DIE重新編號、時間戳依起始時間+間隔秒數遞增。數量防呆訊息(`DieCountMismatch`)沿用WaferCoordinate.exe對話框的原文「需要 Die 數量N，已選擇數量M，需減少/增加…顆」
- 已驗證：把真實範例檔的75筆實際選點依原順序餵回`generate_blank`+`assign_dies`，結構(座標、bin、順序)可完全重現

## 尚未實作

- 讀取/渲染wafer die mapping圖（bin值→顏色），讓使用者實際「點選」座標（目前`assignment.py`只接受已經決定好的`DiePick`清單，還沒有UI幫你產生這份清單）
- 「複製既有.strate為範本」模式
- 桌面/網頁介面本身

## 執行測試

```
pip install pytest
python3 -m pytest bingomap/tests/ -v
```
