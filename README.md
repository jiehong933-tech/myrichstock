# myrichstock

每個交易日用 GitHub Actions 抓台股 ETF 股價，透過 Telegram 發送日報：

- **報價**：0050、00631L（元大台灣50正2）、00685L（群益臺灣加權正2）的收盤價、漲跌、近一年配息與殖利率
- **今年以來漲幅**：00631L、00685L 和集保受益人數前五名的主動式 ETF（每週依集保資料自動重新排名），主動式另外列出成立以來的績效；都是含息報酬，每年 1 月自動從 0 重新算
- **高股息估價**：00878、00919、0056、00713，用近一年配息算殖利率，低於目標買價就提醒「快買進」

每一檔的近一年配息都會從 Yahoo 自動計算（自動判斷月配／季配／半年配／年配），配息金額變了也不用改程式。

## 設定

1. 在 repo 的 Settings → Secrets and variables → Actions 新增 `TELEGRAM_TOKEN`、`CHAT_ID`
2. 要監控的股票、目標殖利率都在 `main.py` 最上面
3. `NOTIFY_EVERY_DAY = False` 可以改成只在有買點或出錯時才發送

## 排程

GitHub 的排程常常延遲好幾個小時（甚至到台灣半夜才執行），Yahoo 有時也很晚才更新收盤價，
所以每個交易日排三次（台灣 14:05、17:05、20:05）。程式會記住上次發送的資料日期，
同一天的資料只發一次；沒有新資料（休市或 Yahoo 還沒更新）就等下一次排程。手動執行一定會發送。

## 出錯時

抓不到股價、Telegram 發送失敗，或 Yahoo 資料超過 14 天沒更新時，Telegram 會收到「抓取失敗」的訊息，GitHub Actions 也會亮紅燈並寄信通知。
如果排程被 GitHub 停用（Actions 頁面出現 “This scheduled workflow is disabled”），按 **Enable workflow** 重新啟用即可。
