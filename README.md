# 箱型選股回測系統

台股「選股 → 回測」全自動雲端系統。每個交易日 15:30（台北時間）自動：

1. 從 Yahoo 增量更新股價到 SQLite 資料庫
2. 掃描「接近 3 年收盤高點 95% 以上 + KD(9,3,3) 剛金叉／將金叉」的股票
3. 對入選名單跑達瓦斯箱型策略回測（移動停利 10%、固定停損 3%）
4. 結果發佈到網頁，手機、電腦開同一個網址就能看

## 架構

```
GitHub Actions（每日排程）─→ 更新 DB（存 GitHub Release）
                          └→ 掃描+回測結果（存 outputs/，commit 回 repo）
Streamlit Community Cloud ─→ 讀取上述結果呈現網頁，可互動改參數重算
```

## 專案結構

| 路徑 | 職責 |
|------|------|
| `core/config.py` | 所有可調參數（停利%、停損%、門檻%…）集中在這 |
| `core/data.py` | 資料庫存取、yfinance 增量更新 |
| `core/indicators.py` | KD 指標計算 |
| `core/scanner.py` | 選股條件（要改選股規則看這裡） |
| `core/backtest.py` | 箱型策略狀態機（要改進出場規則看這裡） |
| `core/report.py` | Excel 報告產生 |
| `jobs/daily.py` | 每日排程入口 |
| `app/main.py` | Streamlit 網頁 |
| `outputs/日期/` | 每日掃描名單與回測結果（自動產生） |

## 本機開發

```bash
pip install -r requirements.txt
python -m pytest                     # 跑測試（29 個）
streamlit run app/main.py -- --local-db "C:\path\to\tw_stock_v2.db"
```

手動跑一次每日流程：

```bash
python -m jobs.daily --db tw_stock_v2.db --output-dir outputs --skip-update
```

## 部署步驟（一次性）

1. `gh auth login` 登入 GitHub
2. `gh repo create stock-box-system --public --source . --push`
3. 上傳初始資料庫：`gh release create data tw_stock_v2.db --title "資料庫" --notes "每日由 Actions 自動更新"`
4. 手動觸發一次確認可跑：`gh workflow run daily-scan-backtest`
5. 到 [share.streamlit.io](https://share.streamlit.io) 用 GitHub 登入 → New app → 選這個 repo、主檔填 `app/main.py` → Advanced settings 的 Secrets 填：
   ```toml
   REPO = "你的帳號/stock-box-system"
   ```
   （選填 `GITHUB_TOKEN`：填了之後網頁上的「存為預設」會把參數寫回 repo）
6. Deploy 完成後的網址即可分享給任何人

## 改參數／改規則

- **日常調參**：網頁側欄直接調，按「重新回測」立即生效；按「存為預設」讓每日排程也改用新參數
- **改選股條件**：編輯 `core/scanner.py` 的 `scan()`
- **改進出場規則**：編輯 `core/backtest.py` 的 `run_backtest()`
- 改完跑 `python -m pytest` 確認測試通過再 push，push 後雲端自動生效

## 常見問題

- **網頁打開要等 30～60 秒**：免費版閒置會休眠，喚醒中，不是壞掉
- **今天沒有新資料**：Yahoo 偶爾抓不到，隔天排程會自動補；網頁上方顯示目前的資料日期
- **排程沒跑**：GitHub → repo → Actions 分頁看 log；公開 repo 60 天無 commit 會自動停用排程，重新啟用即可
