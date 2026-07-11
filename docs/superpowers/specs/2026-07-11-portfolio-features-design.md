# 零股／大盤燈號／持股監控／虛擬操盤 設計

日期：2026-07-11
狀態：使用者已確認四項功能與預設值

## 使用者需求

功能對齊 stock-breakout-signals：持股監控、大盤燈號、虛擬操盤；
加上零股買賣支援（使用者總資金約 5 萬，整張買不起多數入選股）。
Email 通知不做。

## 共用預設（config.json 可調）

- total_capital: 50000（總資金）
- position_pct: 10（單檔上限 %＝5,000 元）
- paper_max_new_per_day: 2（虛擬操盤每日最多新買檔數）

## 1. 零股支援

- `core/position.py`：
  - `suggest_shares(price, capital, pct)`＝floor(capital×pct/100 ÷ price)
  - `buy_cost(price, shares)`／`sell_net(price, shares)`：
    重用 calculate_tw_cost（股數÷1000 傳入，數學上精確），
    手續費 0.1425%×0.6 低消 20 元、賣出加證交稅 0.3%
- 回測引擎 `entry_price` 改由 cfg 讀（預設 0＝空手開始，行為不變）；
  `initial_size` 傳小數張（4 股＝0.004 張）即零股持倉
- 網頁：每日選股表加「建議股數／約需金額」欄
- 已告知限制：零股實際成交價比收盤價差一點，模擬略偏樂觀；低消用 20 元
  保守計（多數券商零股低消 1 元）

## 2. 大盤燈號（core/market.py）

- `new_high_ratio_series(conn, end, days)`：每日「創近一年（245日）收盤新高
  家數 ÷ 有交易家數」的時間序列（單次全市場掃描產生整段序列）
- `market_light(series)`：綠＝比率位於近一年前 30% 且 ≥ 一個月前；
  紅＝位於後 30% 且 < 一個月前；其餘黃。與 breakout 系統邏輯一致
- 每日排程存 outputs/market.parquet；網頁頁首下方顯示燈號＋比率＋走勢小圖
  ＋操作建議（綠＝照計畫買、黃＝減量、紅＝空手等待）

## 3. 持股監控（core/holdings.py）

- repo 根目錄 `holdings.csv`（stock_id,buy_date,cost,shares），GitHub 網頁編輯
- 每日排程對每檔：run_backtest(start=buy_date, entry_price=cost,
  initial_size=shares/1000) 取最後一列 → 訊號狀態、停損/停利線、未實現損益、
  建議文字；存 outputs/holdings_report.parquet
- 網頁新分頁「持股監控」：警示表（跌破停損=紅、轉弱=黃、加碼提示=綠）＋
  編輯說明連結

## 4. 虛擬操盤（core/paper.py）

- 狀態存 outputs/paper/state.json（cash、持股{代號: 股數/成本/進場日}）、
  trades.csv（累加）、equity.csv（每日總值）
- 每日規則（收盤後排程執行）：
  1. 持股檢查：run_backtest(start=進場日, entry_price=成本) 今日列
     狀態為「出場」→ 以收盤價全數賣出（sell_net），記錄交易與原因
  2. 新買：今日掃描名單逐檔 run_backtest（起算=6個月前、空手），
     今日列狀態=「重返進場」→ 買 suggest_shares 股（現金足夠、
     未持有、當日新買 ≤ paper_max_new_per_day）
  3. 記 equity＝現金＋Σ持股×收盤
- 網頁新分頁「虛擬操盤」：目前持股、資金曲線圖、交易紀錄表
- 誠實限制：收盤價成交、無滑價；與真實零股盤成交價有差

## 排程整合

jobs/daily.py 增加 market / holdings / paper 三步（各有 --skip-* 旗標），
outputs 由既有 workflow commit。網頁分頁：每日選股｜個股分析｜時光機｜
持股監控｜虛擬操盤。

## 測試

各模組合成資料 pytest：股數建議與成本、燈號三色判定、持股警示（跌破停損）、
虛擬操盤買進/出場/資金守恆。真實 DB 抽驗後上雲。
