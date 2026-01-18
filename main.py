import os
import yfinance as yf
import requests
from datetime import datetime, timezone, timedelta

# === 從 GitHub Secrets 讀取機密資料 ===
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

# === 設定監控股票 (可自行修改) ===
targets = {
    "00878.TW": {"name": "國泰永續高股息", "single_dividend": 0.55, "frequency": 4, "target_yield": 0.07},
    "00919.TW": {"name": "群益台灣精選高息", "single_dividend": 0.70, "frequency": 4, "target_yield": 0.08},
    "00929.TW": {"name": "復華台灣科技優息", "single_dividend": 0.20, "frequency": 12, "target_yield": 0.075}
}

# === 發送 Telegram ===
def send_telegram_notify(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=payload)
        print("✅ 通知已發送")
    except Exception as e:
        print(f"❌ 發送失敗：{e}")

# === 檢查股價邏輯 ===
def check_stock():
    tw_timezone = timezone(timedelta(hours=8))
    current_time = datetime.now(tw_timezone).strftime('%Y-%m-%d %H:%M')
    print(f"執行時間：{current_time}")

    msg_buffer = f"📅 *{current_time} 收盤監控*\n"
    has_opportunity = False

    for ticker, data in targets.items():
        try:
            stock = yf.Ticker(ticker)
            # 抓取最後一筆收盤價
            hist = stock.history(period="1d")
            if hist.empty: continue
            
            price = hist['Close'].iloc[-1]
            annual_div = data['single_dividend'] * data['frequency']
            cheap_price = annual_div / data['target_yield']
            yield_rate = (annual_div / price) * 100
            
            # 簡化版報告
            report = f"\n*{data['name']}* (`{price:.2f}`)"
            
            if price <= cheap_price:
                gap = cheap_price - price
                report += f"\n🔴 *買進！* (殖利率 `{yield_rate:.2f}%`)"
                has_opportunity = True
            else:
                report += f"\n🟢 觀望 (殖利率 `{yield_rate:.2f}%`)"
            
            msg_buffer += report
            
        except Exception as e:
            print(f"錯誤 {ticker}: {e}")

    # 有買點才通知 (若想每天通知，把 if 拿掉即可)
    if has_opportunity:
        send_telegram_notify(msg_buffer)
    else:
        print("💤 無買點，不打擾。")

if __name__ == "__main__":
    check_stock()
