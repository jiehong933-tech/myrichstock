import os
import yfinance as yf
import requests
from datetime import datetime, timezone, timedelta

# === 從 GitHub Secrets 讀取機密資料 ===
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

# === 設定監控股票 (可自行修改) ===
targets = {
    "00878.TW": {"name": "國泰永續高股息", "single_dividend": 0.55, "frequency": 4, "target_yield": 0.09},
    "00919.TW": {"name": "群益台灣精選高息", "single_dividend": 0.70, "frequency": 4, "target_yield": 0.09},
    "0056.TW": {"name": "元大高股息", "single_dividend": 0.866, "frequency": 4, "target_yield": 0.09}
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
def check_stock_valuation(ticker, data):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1d")
        
        # 如果抓不到股價，直接回報失敗
        if hist.empty: 
            return None, False

        current_price = hist['Close'].iloc[-1]
        
        # 計算相關數值
        annual_dividend = data['single_dividend'] * data['frequency']
        cheap_price = annual_dividend / data['target_yield']
        current_yield = (annual_dividend / current_price) * 100
        
        # === 關鍵修正：定義 msg_body ===
        # 這裡會建立要傳送的訊息內容
        msg_body = (
            f"\n📊 *{data['name']} ({ticker})*"
            f"\n-----------------------"
            f"\n💰 目前股價：`{current_price:.2f}`"
            f"\n📉 目標買價：`{cheap_price:.2f}` (殖利率 {data['target_yield']*100:.1f}%)"
            f"\n📈 目前殖利率：`{current_yield:.2f}%`"
        )
        
        signal_msg = ""
        is_buy = False
        
        # 判斷是否便宜
        if current_price <= cheap_price:
            gap = cheap_price - current_price
            signal_msg = f"\n🔴 *【快買進！價格甜了】*\n   (比目標便宜 {gap:.2f} 元)"
            is_buy = True
        else:
            gap = current_price - cheap_price
            signal_msg = f"\n🟢 *【觀望】* 還差 {gap:.2f} 元"
        
        # 回傳結果
        return msg_body + signal_msg, is_buy

    except Exception as e:
        print(f"無法抓取 {ticker} 的數據：{e}")
        return None, False
    # 有買點才通知 (若想每天通知，把 if 拿掉即可)
    if has_opportunity:
        send_telegram_notify(msg_buffer)
    else:
        print("💤 無買點，不打擾。")

if __name__ == "__main__":
    check_stock()
