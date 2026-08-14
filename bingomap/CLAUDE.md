# bingomap 開發筆記

BINGO MAP補資料工具開發過程中踩過的坑跟確認過的規則，避免下次重複犯錯、
繞遠路。格式細節見`README.md`，這份文件記重要的「為什麼」。

## .strate格式的規則都是逆向真實檔案得出的，不是猜的

每一條規則背後都有真實範例檔案或截圖佐證（見`tests/`裡的測試案例跟
commit history），改動格式相關邏輯前，先確認有沒有真實資料支持，不要
憑直覺調整。目前已確認：

- **未上片的基板位置整筆省略**，不是留著寫`bin=0`——用真實檔案比對
  ROW×COLUMN理論滿版數 vs 實際筆數（TOTAL_BOND_DIE_QTY）反推出來的
- **LOC製程從1:1起編號，EPOXY製程從0:0起編號**——SOP文件明確警告這是
  最容易出錯、錯了會整批報廢的地方，兩種慣例不可混用
- CRLF換行、`[DIE_INFO_END]`後面固定兩個空行結尾——byte-for-byte驗證過
- DIE_INFO最後一欄不是恆定的`1`，是**層數**（見下面疊層那段）

## 疊層(一次上兩顆)：`[DIE_INFO_OTHER_LAYER_BEG/END]`

2026/08/14發現：機台一次動作同時吸取兩顆die疊在同一個基板位置時，
`.strate`檔案裡`[DIE_INFO_END]`後面會再接一段`[DIE_INFO_OTHER_LAYER_BEG]/
[DIE_INFO_OTHER_LAYER_END]`，裝另一層的資料，兩段DIE_INFO每列最後一欄
(層數)不同。這個結構在最初那份單層範例檔裡完全不會出現(尾欄固定`1`)，
是後來拿到雙層真實範例才發現的——**看到`f9`固定是`1`的樣本，不代表這個
欄位本來就是常數，只代表那份樣本剛好是單層。**

`blank_generator.py`/`assignment.py`目前都還只處理單層(`die_info`)，
`other_layer_die_info`還沒有對應的空白產生/填入邏輯——真的要補疊層資料
時要記得擴充這兩個檔案，不是只有`strate.py`的parse/write支援了就沒事。

（2026/08/14後續更新：`assignment.py`的`assign_two_layers()`跟webapp的
UI(疊層checkbox+主層/次層切換按鈕)都已經補齊，兩層各自獨立計數、各自
補滿才能產生檔案，已用真實雙層範例資料+Playwright端對端測試驗證過。）

## Mapping SOAP服務(`mapping_service.py`)：母批號要去掉子批次尾碼

`http://tneas.tn.chipmos.com.tw:10000/Mapping/Service.asmx`的
`GetMappingLotNoByAssyLot`，傳入帶子批次尾碼的批號（例如`V32AWCW02`）
會回傳空結果——**即使那個子批次當下確實在產線上RUNNING**，也查無資料。
一定要先用`strip_sub_lot_suffix()`去掉尾碼（`V32AWCW02` -> `V32AWCW`）
才查得到。這個規則是連續測試了`V32AWCW01`、`V32AWCW`(第一次，沒查到)、
`V32AWCW02`才發現的——後來確認第二次測`V32AWCW`(去尾碼)其實有效，第一次
會失敗可能是別的原因，重點是**去尾碼的母批號查得到，帶尾碼的查不到**，
這是唯一穩定重現的規律。

同一份服務裡的`GetAOIBinData`，即使傳入正確格式(去尾碼)的真實批號，也
一律回`STATUS=NG`，判斷這支API不是wafer逐顆bin資料的來源，**已停損不要
再花時間猜它的參數**——這支API名稱雖然聽起來很像，但實測結果不支持這個
假設。

## wafer bin地圖(綠色bin1/粉紅bin7)的真正資料來源還沒解開

WaferCoordinate.exe左邊那張wafer網格圖的顏色資料，最後追到是來自另一支
獨立程式(「目視檢查」/`P_map_image.exe`)，背後又指向同一台主機的另一個
SOAP服務路徑，但沒有進一步確認是哪一支API、格式為何。**目前的決定是不
再往下猜/測，這一步保留人工操作**（開現場工具查詢、把資料貼進
`WaferBinMap`），`wafer_map.py`的設計刻意跟資料來源脫鉤，不管這份資料
怎麼來的都能用。如果之後想再挑戰自動化這塊，`P_map_image.exe`裡找到的
`http://tneas.tn.chipmos.com.tw:10000/Mapping/Service.asmx`WSDL清單是
起點，但`GetAOIBinData`已知是死路，不要重複嘗試。

## DB vs ESEC(2100SD)：基板位置排列順序完全不同，不能共用一套邏輯

2026/08/14從PPT裡一封2019/11/27的內部信件截圖(第22頁)挖出來的：DB機台
跟ESEC 2100SD機台，即使是同一個產品、同一套SUBSTRATE_ROW/COLUMN，
DIE_INFO裡基板位置(第4欄)的排列順序完全不同：

- **DB**：從`0:0`開始，欄序由小到大，每欄內列由小到大遞增，單純掃描
- **ESEC**：從**最後一格**`COLUMN-1:ROW-1`開始，欄序由大到小，而且
  **每換一欄，列的方向就交替一次**(蛇形/boustrophedon)

信件原文直接寫：「以下畫面為DB&2100SD產生的BINGO MAP 啟始的位置相反,
所以如果COPY到不同機型的資料,所得的圖就會不同」——這不是理論推測，是
公司內部真實案例(BA708 MOVE OUT NG，補資料格式抄錯機型導致的異常)。

`blank_generator.py`的`machine_type`參數("DB"/"ESEC")就是照這個真實
比對寫的，兩組排列演算法各自用真實檔案的頭13筆資料驗證。**任何其他
機型(CM700等)在沒有真實範例驗證前，都不要假設沿用DB或ESEC其中一套
邏輯**——這兩套本身就已經證明「聽起來合理」不代表是對的(一開始设計時
完全没想到会有反向+蛇形这种排法)。

## wafer bin地圖的真正資料來源：反編譯.exe直接找到答案，不用猜

前面繞了很多路想找wafer bin地圖(WaferCoordinate.exe左邊那張綠/粉紅圖)的
資料來源——先猜過SOAP API(`GetAOIBinData`，已證實是死路)，後來使用者
一路找到`F:\SMAP\FRM\`這個資料夾，但一直卡在「不知道裡面檔案格式」。

2026/08/14換了個方法直接解決：**用`ilspycmd`反編譯`WaferCoordinate.exe`**
（`dotnet tool install -g ilspycmd --version 8.2.0.7535`，注意最新版
`ilspycmd`在這個環境裝不起來，要指定這個版本；另外執行時要
`export DOTNET_ROLL_FORWARD=LatestMajor`，因為這個版本的ilspycmd是針對
.NET 6打包的，這台機器只裝得了.NET 8 SDK，要讓它roll forward才跑得動）。
反編譯出來的`.cs`檔案裡，`DieAttachFmtRW.ReadMap()`跟`CMAP_I_HEADER`/
`CMAP_II_HEADER`/`CMAPBIN_I`/`CMAPBIN_II`這幾個class把FRM檔案的二進位
格式寫得一清二楚——欄位、byte數、大小端序都在裡面，不用再猜或等使用者
找範例檔案。詳細規格見`frm_reader.py`的docstring，這裡記重點教訓：

**遇到「不知道某個檔案格式」的問題，如果那個格式是由一支.exe寫出來/
讀進去的，且那支.exe是.NET程式（用`file`指令看到"Mono/.Net assembly"字樣），
第一步應該是嘗試反編譯，而不是先猜格式或一直伸手跟使用者要範例檔案。**
反編譯拿到的是100%正確的規格（除非程式本身有bug），比對照少量範例檔案
逆向猜測可靠得多，而且不需要使用者一直在現場翻檔案、來回傳截圖。

反編譯路上的坑：
- `ilspycmd`最新版(11.x)在這個環境`dotnet tool install`會失敗
  （"Settings file 'DotnetToolSettings.xml' was not found"），指定舊版
  `8.2.0.7535`才裝得起來
- 裝起來的`8.2.0.7535`是針對.NET 6打包的，這個環境只裝了.NET 8 SDK
  （apt套件庫沒有6.0/7.0 runtime），要設環境變數
  `DOTNET_ROLL_FORWARD=LatestMajor`讓.NET 8 runtime代跑.NET 6目標的程式，
  不然會報「You must install or update .NET to run this application」

## 移植使用者提供的參考工具：先分辨「活的邏輯」跟「死碼」，再談要不要搬

2026/08/14：使用者要求把另外兩套自己開發的ESEC 2100參考工具（STRATE座標偏移點除工具v78、
STRATE補檔工具v38）的功能也搬進bingomap網頁。這兩個檔案都是單檔HTML+內嵌JS，而且都是**改版多次
沒清乾淨**的狀態：

- v78裡有整個`run()`函式（連同只有它會呼叫的`renderCorrectWaferOverlay`/`diagnoseCoordModes`/
  `classifyRow`等一大串helper，約占全檔35%）完全沒被任何按鈕綁定——是作者放棄的舊版「比對兩張wafer
  MAP」設計，跟目前活的`v67*`/`v72*`/`v78*`是兩套不同的演算法，不是被依賴的helper
- v38裡有整段包在`<script type="text/plain" id="legacyV31">`裡的舊版`run()`實作——`type="text/plain"`
  的script瀏覽器根本不會執行，是100%死碼，而且檔案裡同一個函式名稱（如`mapHtml32`）還疊了3~4代
  舊定義，靠後面的`window.mapHtml32=function(){...}`覆蓋前面的，只有最後一次賦值是真的在跑

**移植前一定要先追蹤每個按鈕的`addEventListener`實際呼叫到哪個函式版本，把真正在跑的邏輯跟版本
演進留下的殘骸分開**，不要照著檔案從頭到尾的順序理解「這是什麼設計」，很容易把已經被放棄的舊設計
當成現行邏輯搬過來。

## 誤吸偏移／BIN點除：座標轉換公式是「現場驗證過的經驗公式」，不是幾何推導

v78的核心轉換（STRATE記錄的wafer座標`FX:FY`轉回原始wafer MAP座標）用固定X反轉：
`MAP_X = wafer_map裡實際資料的max_x - FX`，程式裡的中文註解直接寫「現場資料驗證後，回原始MAP採X
反轉」——這是作者拿ESEC 2100SD真實資料試出來的，不是從geometry第一性原理推出來的公式，而且**整個
工具鎖死只支援NOTCH=270**，其他角度直接不處理。

移植到`mispick_analysis.py`時比照辦理：只支援NOTCH=270，遇到其他NOTCH直接丟`UnsupportedNotchError`
拒絕分析，不要自己延伸公式去猜其他角度怎麼轉——這正是使用者當下提醒的：「他的是針對esec2100機台
開發所以會跟我的規則有點不一樣」，別把單一機型驗證過的經驗公式當成放諸四海皆準的通用邏輯。

同一個原因，這個分析流程本身**還沒拿bingomap這邊的真實已知誤吸案例核對過**（只有拿v78的公式手算
出的合成測資驗證過數學本身算對），操作前應該先用一個已知結果的真實案例試跑確認，不要一開始就直接
信任輸出拿去現場點除。

## 誤吸偏移分析讀的wafer MAP，跟FRM是同一種格式——但參考工具自己那段parser是用猜的，不要照抄

v78自己內建一個`parseWaferMapBinary`，是完全沒有固定header、用滑動視窗掃描位元組、每個候選區段用
「取樣80筆、要求≥85%像座標」這種機率門檻去猜出來的heuristic scanner，程式裡自己標註
`parser:'v56_viewer_4byte_col_rowhi_rowlo'`，註解也承認是「沿用使用者提供的wafer_viewer原圖parser」
——不是反編譯得出的，是猜的。這個位元組佈局（1 byte bin字元+2個0+2byte count+1個0接住座標，每筆座標
4 bytes：col、row高位、row低位、padding）跟`frm_reader.py`已經反編譯verified的FRM格式（bin_kind是
2-byte大端ASCII碼、格式I座標是1byte x+1byte y沒有padding byte）完全對不上。

問過使用者確認：誤吸點除工具讀的「原始wafer MAP」就是同一份F:\SMAP\FRM\的FRM檔案，所以
`mispick_analysis.py`直接吃`frm_to_wafer_bin_map()`轉出來的`WaferBinMap`，v78那段heuristic scanner
完全沒有搬——這是本專案「不要猜格式，能反編譯/能問清楚就不要用機率門檻硬猜」原則的又一次應用。

## 移植Crack模式時往回讀v78原始碼，才發現誤吸模式自己漏掉了wafer ID正規化

2026/08/14移植Crack位置回推時重新細讀`runV78Crack`，發現它比對wafer ID用的是
`String(r.strateWaferId||'').trim().toUpperCase()`——回頭看`runV68`（誤吸點除模式的進入點）
其實**也是**同一種寫法，只是我第一次移植`mispick_analysis.py`時只顧著搬座標轉換公式，
沒注意到這個正規化，寫成了`die.wafer_ring != wafer_ring`的exact match（比參考工具本身還嚴格，
會把大小寫或前後空白不同但其實是同一顆wafer的資料誤判成「其他wafer」而排除掉）。

已經修正：兩個模式現在共用`mispick_analysis.normalize_wafer_id()`（trim+大寫）做比對，
`crack_recovery.py`從一開始就用這個規則。**教訓：只移植看得到、在意的那一小段邏輯（例如這次
一開始只看了座標轉換公式那幾行）容易漏掉旁邊看起來不起眼但同樣重要的正規化/防呆邏輯——
移植同一個工具的第二個功能時，值得回頭把第一個功能也對照一次，不要假設第一次就搬乾淨了。**

## 誤吸偏移／Crack回推的座標公式：搬完ESEC工具之後才發現使用者實際用的是DB機型

2026/08/14：`mispick_analysis.py`跟`crack_recovery.py`都上線、也各自寫了測試跟通過Playwright
驗證之後，使用者才提醒：「記得我的基板上片strip規則跟wafer mapping座標規則是DB機型的」——這兩個
模組的座標轉換公式(NOTCH=270的X反轉、raw↔machine旋轉、輸出顯示的TX反轉、Crack局部分布的NOTCH
旋轉)全部是照ESEC 2100參考工具的程式碼字面搬過來的，而參考工具本身的註解也明講這些公式是「現場
驗證過的經驗公式」，只對ESEC 2100SD這個機型成立——**這兩個功能目前的座標數學，跟使用者實際在用的
DB機型規則很可能對不上**。

已經在網頁跟README/CLAUDE.md標上明顯警告，等使用者提供DB機台的真實案例(STRATE+wafer MAP+已知正確
結果)後重新推導公式。**教訓：移植別人給的參考工具時，工具本身是為哪個機型/情境開發的，不代表使用者
自己實際的生產規則也是同一個——即使工具程式碼裡寫死「這是驗證過的」，也只代表對工具原作者的情境
驗證過，換了使用情境（這裡是DB vs ESEC）還是要重新跟使用者核對，不能因為「反正是照抄現成驗證過的
公式」就跳過這一步。**跟blank_generator.py的DB/ESEC基板排列規則不是同一件事——那邊已經支援machine_type
參數且DB是預設值；這裡誤吸/Crack的座標轉換公式是全新的、只依照ESEC工具本身的假設寫的，兩者不要混為
一談。

## WaferCoordinate.exe對話框文字不對稱，不要自己腦補

數量不符時的提示文字，選多跟選少用的字不一樣：
- 選多了：「需要 Die 數量N，已選擇數量M，**需減少**X顆」
- 選少了：「需要 Die 數量N，已選擇數量M，**還需選擇**X顆」

第一版憑常理猜選少了應該是「需增加X顆」，猜錯了，後來用真實對話框
截圖才修正。凡是要重現既有系統的訊息文字，優先找真實截圖，不要用「聽
起來合理」的說法自己填。
