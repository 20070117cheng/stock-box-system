# 疊加過濾器（volume / regime / rs）設計

日期：2026-07-10
狀態：已與使用者確認（三個一起測）

## 目的

三模式對比後報酬率無明顯差異，檢視大師方法找出系統缺口：
量能確認（達瓦斯/歐尼爾）、大盤濾網（歐尼爾 M/林則行多空判別）、
相對強度（歐尼爾 RS/橫斷面動能）。三者用現有價量資料即可回測。

## 設計

`cfg["scan_filters"]`（list，可疊加、可與任何 scan_mode 組合）：

- **volume**：訊號日成交量 ≥ volume_avg_days(20) 日均量 × volume_surge_ratio(1.5)
- **regime**：regime_symbol(0050) 收盤 ≥ 其 regime_ma_days(200) 日均值，
  否則當日整批不出訊號
- **rs**：近 rs_lookback_days(60) 交易日報酬 ≥ 全市場（有足夠資料者）
  100−rs_top_pct(20) 百分位

實作於 scan() 主迴圈：regime 開頭一次判定；volume 逐檔後置檢查；
rs 迴圈中蒐集全市場報酬分布、迴圈後取百分位過濾。
scan_params() 納入啟用的過濾參數（快取隔離）。

## 驗證方式

backfill-mode workflow 新增 filters 輸入，各回填一年到
outputs/history_near_high_<filter>/，與基準 near_high 對比。
基準假設（事前寫下）：volume 對報酬改善最明顯、regime 降交易數但提品質、
rs 在多頭年效果普通。

commit 步驟加 push 重試（三個回填平行跑會撞車）。

## 事前預測（回頭對答案用）

- volume：每筆平均報酬提升最多
- regime：交易數下降、每筆報酬升，總獲利未必升
- rs：這一年效果普通（多頭年強弱股都在漲）
