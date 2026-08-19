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
- 見`../webapp/`——用Flask把上面這些邏輯包成能實際操作的網頁，流程：填資訊→產生空白骨架→貼wafer bin資料→點選/框選座標(即時顯示對應到基板的哪個位置)→產生並下載`.strate`。已用Playwright實際跑過瀏覽器驗證。

**Phase 3：wafer bin地圖真正資料來源(FRM檔案) — 格式已用真實檔案100%驗證**
- `frm_reader.py`：`WaferCoordinate.exe`畫的那張綠色(bin1)/粉紅(bin7)wafer網格圖，真正的資料來源是一個**二進位FRM檔案**，2026/08/14用`ilspycmd`反編譯`WaferCoordinate.exe`直接讀原始碼(`DieAttachFmtRW.ReadMap()`)才挖出來的完整格式規格，不是猜的也不是靠SOAP API——那條路已確認是死路（見下方Phase 1c）
- 檔案位置也是反編譯得出的：`{FRM_PATH}\{LotNo}\{barcode前2碼}\{barcode第3~6碼}`，`frm_file_path()`照這個規則組路徑
- 支援兩種二進位格式(第一個byte兼做格式判斷碼跟`reverse_fixed`欄位本身)：格式0(較窄的row/col/qty欄位)、格式2(較寬)，欄位精確bytes offset都在`frm_reader.py`docstring裡
- **已用真實檔案(`F:\SMAP\FRM\8P065800A1\T3\DA62`)100%驗證**：LotNo/WaferID/Layout/Row/Column全部吻合，**BIN1=1635顆、BIN7=379顆跟目視檢查畫面上的數字完全一致**，渲染出來的圖形也跟WaferCoordinate.exe畫面上的橢圓形完全一樣。真實檔案存在`tests/fixtures/8P065800A1_T3_DA62.frm`，有專屬回歸測試。另外發現檔案結尾有2個`\xff\xff`結尾標記位元組，不影響解析(loop是靠`bin_kind_count`/`bin_qty`驅動，不會讀到那邊)，已記錄在測試裡
- `frm_to_wafer_bin_map()`把解析結果轉成`wafer_map.py`用的`WaferBinMap`，串上後面的框選/填入邏輯完全不用改

## 複製既有.strate為範本

`blank_generator.py`的`blank_from_positions()`：跟`generate_blank()`不同，不吃`convention`/`machine_type`，
直接吃呼叫者給的`positions`(已知順序的`sub_pos`字串列表)。這是給webapp的`/api/parse_strate`用的——
先把一份真實舊檔案parse出來，直接拿它自己`DIE_INFO`裡的`sub_pos`順序當作新blank的順序，完全不需要
猜測/重新判斷這份舊檔案當初是哪個機型產生的，從根本上避開DB/ESEC順序搞混的風險。

**Phase 4：誤吸偏移／BIN點除分析（移植自ESEC 2100參考工具）**
- `mispick_analysis.py`：已知機台偏移量時，反算哪些已上片位置實際落在壞BIN上，產出點除清單。邏輯完整移植自使用者提供的ESEC 2100參考工具（STRATE座標偏移點除工具v78）真正在跑的那條pipeline（該工具裡還有一大段沒被任何按鈕呼叫到的舊版死碼，已篩掉不搬）
- **鎖定NOTCH=270，不支援其他角度**：座標轉換公式（STRATE的wafer_xy要轉回原始wafer MAP座標用固定X反轉）是參考工具作者現場驗證過的經驗公式，不是憑幾何原理推導的，只對ESEC 2100SD這個NOTCH角度成立。NOTCH不是270的STRATE會直接拒絕分析(`UnsupportedNotchError`)，不會自己套公式硬猜——使用者明確提醒過這套工具是針對ESEC2100機台開發、規則跟通用bingomap系統不完全一樣
- 跟參考工具的差異（刻意改進）：有處理疊層(`DIE_INFO_OTHER_LAYER_*`)第二層資料，參考工具原本完全沒讀這段
- 原始wafer MAP讀的檔案格式已跟使用者確認**就是`frm_reader.py`已經byte-exact驗證過的FRM格式**，不是參考工具裡那段用「猜測」寫的heuristic binary scanner（那段掃描器完全沒有固定header、用85%機率門檻硬猜，已確認不採用）
- **尚未用真實已知誤吸案例驗證過端對端結果**——座標轉換公式本身是照參考工具忠實搬過來的，但這個分析流程還沒拿bingomap這邊的真實誤吸案例資料核對過，操作前務必先用已知案例試跑確認（這句仍只適用於`machine_type="ESEC"`；`"DB"`的座標對應關係已用真實資料核對，見下）
- **`machine_type`參數：`"DB"`(預設)或`"ESEC"`。2026/08/17使用者提供DB機型的真實案例後已確認並修正**：DB的STRATE `wafer_xy`就是wafer MAP自己的原始座標，**不需要任何轉換**(不像ESEC需要X反轉+NOTCH旋轉)，offset直接加在原始座標上。證據：ChipMOS內部「WaferCoordinate」工具截圖，機型選單明確選在「DB系列」，工具自己讀出來的X,Y,Bin清單跟同一份真實STRATE檔案的`wafer_xy`欄位逐筆對得上，另外還有對應的目視檢查wafer圖跟EAS「Bingo Map Query」報表互相印證。真實範例檔存在`tests/fixtures/2070_V32AWE6_Z26306101030_20260811072811.strate`，有專屬回歸測試(`test_mispick_analysis_real_db_sample.py`)驗證這個identity對應關係。DB模式也不限制NOTCH(這份真實檔案NOTCH=180)；ESEC模式維持原本鎖NOTCH=270的限制不變，因為DB confirm不代表ESEC那套經驗公式本身有問題，只是那套公式不適用這個系統的真實機台

**Phase 5：Crack位置回推（移植自ESEC 2100參考工具）**
- `crack_recovery.py`：只用已上片STRATE(不用wafer MAP、不套偏移)，讓操作員在基板圖上點選實物Crack格子，回推這些位置在原始wafer上的**相對**分布——跨多份STRATE、只要`wafer_ring`(完整Wafer ID)相同就會自動匯總在一起(一片wafer可能對應多片基板)
- 跟誤吸點除模式的關鍵差異：**接受任何NOTCH**(0/90/180/270皆可，不是270才行的公式`0=270`會落到跟0度一樣的預設分支)；沒有驗證bin正不正確的邏輯，每個已上片位置一律視為背景BIN1(CSV裡固定寫死`1`，不管那筆資料實際紀錄的bin是多少)——這是照參考工具本身的設計，Crack模式的目的只是回推位置，不是驗證良率
- **all-or-nothing**：任何一份STRATE缺NOTCH或幾何無效，整個操作直接失敗，不會像誤吸點除模式那樣個別跳過那份檔案——因為Crack模式的核心就是把多份STRATE匯總在一起，悄悄漏掉一份會讓局部分布看起來不完整卻沒有任何警示
- 局部分布座標(`local_view()`)**明確不是完整wafer絕對座標**，只是已匯入資料彼此的相對位置正規化——這是參考工具自己在說明文字裡講的限制，這裡原樣保留這個警語，不誇大輸出的意義
- wafer ID比對用`normalize_wafer_id()`(去頭尾空白+轉大寫)，這其實也是誤吸點除模式原本該有但漏掉的規則——移植Crack模式時往回讀v78原始碼才發現參考工具兩個模式都有做這個正規化，已經回頭把`mispick_analysis.py`也修正成一致的比對方式（原本是exact match，比參考工具本身還嚴格）
- 也支援`machine_type`參數(`"DB"`預設/`"ESEC"`)：DB模式下`output_position()`(基板顯示)跟`local_view()`(局部分布)都是identity(無反轉/無旋轉)，跟誤吸模式的DB結論一致(由延伸推論確認，不是Crack情境本身逐一驗證過)；ESEC模式維持照參考工具原樣的TX反轉+NOTCH旋轉

**Phase 6：STRATE補檔 XML合併（`secs_log.py`）**

2026/08/18使用者提供了機台真實的SECS/AFC交易紀錄log(BAB14站台)，想從裡面直接抓出基板資料跟wafer bin
map，不用透過FRM檔案或手動重新點座標。這不是SECS-II binary，是DEBUG/INFO log行跟內嵌XML片段交錯的
純文字log(檔案本身是UTF-16LE編碼、沒有BOM——`decode_secs_log()`會自動偵測)。

- `StrateMap`事件(`Type="Event"`)＝一枚完成上片的基板：`<DIE_INFO>`/`<DIE_INFO_OTHER_LAYER>`底下的
  `<Item>`內容**剛好就是**.strate檔案DIE_INFO那行9欄CSV格式，`DieInfo.from_line()`直接原樣解析，
  完全不用轉換
- `ASSY_LOT`/`OPER`這份log完全沒有紀錄(不管哪個Transaction類型都沒有)；`MAPPING_LOT`也不在`StrateMap`
  裡(只有`WaferMap`/`WaferStart`才有，記的是整片wafer的，不是這枚基板的)——三個欄位都留空，讓使用者
  下載後自己人工補上(使用者2026/08/18明確指示：不要用猜的關聯去填)
- `WaferStart`事件＝一片實體wafer的bin map，`<BinList>`是一整條`ColCount*RowCount`字元的字串(一個
  字元一顆die，空白＝沒有die)——**這個座標系統的row/col對應方向，是拿同一個wafer_ring(frame)的真實
  `StrateMap` DIE_INFO資料交叉驗證出來的**：BinList的第X列(row)、字串內第Y個字元(column)，對應的就
  是DIE_INFO自己`wafer_xy`欄位的`X:Y`——196顆die交叉比對189顆(96%)完全吻合，剩下的差異是wafer-start
  當下記錄好的die、實際被撿取時已經被判定成別的bin(合理的現實情況，不是座標算錯)。`WaferUpload`的
  `<WAFER_INFO>`/`<ORG_WAFER_INFO>`乍看類似，但其實是稀疏的缺陷碼疊圖，不是完整bin map，**沒有用來
  做這個功能**
- 真實log的一小段存成`bingomap/tests/fixtures/secs_log_sample.log`(從使用者提供的完整log裁切、重新
  編碼回UTF-16LE)，專屬測試鎖定上面這些結論

**Phase 7：SECS格式化參數（`secs_params.py`）**

2026/08/19：同一份SECS/AFC log裡還有`S7F25FormattedPPRequest`(`Type="Reply"`)事件，記錄機台的一次
recipe參數快照——`PP_ID`/`MDLN`/`SOFTREV`加上一長串`<Item>`(每個`CCODE`＋固定6個`<PPARM>`：名稱/單位/
格式/數值/下限/上限)。真實log只有2次快照，各199組參數(不是使用者記憶中的181或計畫中的349，已回報
使用者)。目前只做了「列出log裡有什麼」，跟Excel參考清單比對的功能還沒做——等使用者提供範例Excel檔案，
不用猜欄位格式。

**開發過程中發現、修好一個影響`secs_log.py`跟`secs_params.py`共用的解析bug**：兩邊原本各自的
`_TRANSACTION_RE`正則式`<Transaction\b[^>]*>.*?</Transaction>`沒考慮自我封閉標籤
`<Transaction ... />`（每個Request那半內容是空的，都用這種寫法）——`[^>]*>`會把`/>`誤認成一般開始
標籤的`>`，接著非貪婪的`.*?</Transaction>`一路吃到**下一個**Transaction的結束標籤才停，把兩個不相干
的Transaction黏成一段無效XML，`ET.fromstring`解析失敗、兩個都被跳過、沒有任何錯誤訊息。平常log裡
Request跟自己的Reply中間通常還夾著別的Transaction(有自己的結束標籤讓正則式提早停下)，不容易踩到；
但真實log裡第二次S7F25快照(TID=58203)剛好是Request後面緊接著自己的Reply、中間沒有別的Transaction，
直接把整整199組參數的快照吃掉不留痕跡——如果沒有順手去對真實log的原始筆數(而是照單全收API回應)，
這個資料遺失不會被發現。修正成`<Transaction\b[^>]*/>|<Transaction\b[^>]*>.*?</Transaction>`(先試著
整段匹配自我封閉標籤，不行才退回配對結束標籤)，兩個模組都已修好，測試fixture也重建成刻意保留這個
「Request緊接自己Reply、中間沒有其他Transaction」的真實排列方式，鎖定回歸。

教訓：**用正則式抓「一對開始/結束標籤」時，一定要先確認這個標籤有沒有自我封閉的寫法，沒考慮到的話
表面上「看起來有解析出東西」也可能是靜默漏資料，不會報錯——尤其是log這種每個Transaction名稱重複
出現很多次的情況，光看「有抓到幾筆」的數量本身也未必能察覺少了一筆，要跟真實資料的已知數量核對。**

## 尚未實作

- ESEC以外、DB以外的其他機型(CM700等)排列規則尚未驗證
- 上片狀態人工確認/修正——ESEC參考工具裡的另一個功能，尚未移植
- Crack局部分布的PNG視覺化(參考工具的雙canvas對照圖)沒有搬，目前只有HTML表格版的基板圖+散點圖，功能等價但視覺效果較簡單
- SECS格式化參數：跟Excel參考檔案比對的功能——等使用者提供範例Excel檔案

## 執行測試

```
pip install pytest
python3 -m pytest bingomap/tests/ -v
```
