# myrichstock

每個交易日用 GitHub Actions 抓台股 ETF 股價，透過 Telegram 發送日報：

- **報價**：0050、00631L（元大台灣50正2）的收盤價、漲跌、近一年配息與殖利率
- **高股息估價**：00878、00919、0056、00713，用近一年配息算殖利率，低於目標買價就提醒「快買進」

每一檔的近一年配息都會從 Yahoo 自動計算（自動判斷月配／季配／半年配／年配），配息金額變了也不用改程式。

## 設定

1. 在 repo 的 Settings → Secrets and variables → Actions 新增 `TELEGRAM_TOKEN`、`CHAT_ID`
2. 要監控的股票、目標殖利率都在 `main.py` 最上面
3. `NOTIFY_EVERY_DAY = False` 可以改成只在有買點或出錯時才發送

## 出錯時

抓不到股價或 Telegram 發送失敗時，Telegram 會收到「抓取失敗」的訊息，GitHub Actions 也會亮紅燈並寄信通知。
如果排程被 GitHub 停用（Actions 頁面出現 “This scheduled workflow is disabled”），按 **Enable workflow** 重新啟用即可。
