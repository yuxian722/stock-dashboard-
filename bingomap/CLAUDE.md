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

## WaferCoordinate.exe對話框文字不對稱，不要自己腦補

數量不符時的提示文字，選多跟選少用的字不一樣：
- 選多了：「需要 Die 數量N，已選擇數量M，**需減少**X顆」
- 選少了：「需要 Die 數量N，已選擇數量M，**還需選擇**X顆」

第一版憑常理猜選少了應該是「需增加X顆」，猜錯了，後來用真實對話框
截圖才修正。凡是要重現既有系統的訊息文字，優先找真實截圖，不要用「聽
起來合理」的說法自己填。
