# bingomap

BINGO MAP補資料工具的核心邏輯（`.strate`檔案格式讀寫 + 空白檔案產生器）。
目標：開軟體 → 輸入資訊 → 跑出mapping圖 → 點座標 → 出`.strate`，桌面版/網頁版共用這份core，不重寫兩套邏輯。

## 目前進度（Phase 1a）

- `strate.py`：`.strate`檔案的parse/序列化，格式已用真實範例檔案做byte-for-byte round-trip驗證
- `blank_generator.py`：依標頭參數（跟EAS「Create Golden SubstrateMap」表單同一組欄位）自動產生空白骨架，取代手動登入EAS網頁系統那一步。支援LOC(從1:1起)/EPOXY(從0:0起)兩種基板編號慣例

## 尚未實作

- 讀取/渲染wafer die mapping圖（bin值→顏色），讓使用者點選座標
- 座標圈選 → 依LOC/EPOXY規則寫回`DIE_INFO`、未上片位置整筆省略（已用真實檔案驗證此行為）
- 數量防呆（已選數量 vs TOTAL_BOND_DIE_QTY 不符不給產出）
- 「複製既有.strate為範本」模式

## 執行測試

```
pip install pytest
python3 -m pytest bingomap/tests/ -v
```
