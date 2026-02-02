import os
import yfinance as yf
import requests
from datetime import datetime, timezone, timedelta

# === 1. 從 GitHub Secrets 讀取機密資料 ===
# 必須使用 os.environ，不然 GitHub 會報錯
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# === 2. 設定監控股票 ===
targets = {
    "00878.TW": {"name": "國泰永續高股息", "single_dividend": 0.40, "frequency": 4, "target_yield": 0.09},
    "00919.TW": {"name": "群益台灣精選高息", "single_dividend": 0.54, "frequency": 4, "target_yield": 0.09},
    "0056.TW":  {"name": "元大高股息",     "single_dividend": 0.866, "frequency": 4, "target_yield": 0.09},
    "00713.TW":  {"name": "元大台灣高息低波",     "single_dividend": 0.78, "frequency": 4, "target_yield": 0.09}
}

# === 3. 發送 Telegram 通知函式 ===
def send_telegram_notify(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ 錯誤：Token 或 Chat ID 為空")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=payload)
        print("✅ Telegram 通知已發送")
    except Exception as e:
        print(f"❌ 發送失敗：{e}")

# === 4. 單檔股票計算函式 (這是您剛剛寫對的部分) ===
def check_stock_valuation(ticker, data):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1d")
        
        if hist.empty: 
            return None, False

        current_price = hist['Close'].iloc[-1]
        
        # 計算相關數值
        annual_dividend = data['single_dividend'] * data['frequency']
        cheap_price = annual_dividend / data['target_yield']
        current_yield = (annual_dividend / current_price) * 100
        
        # 定義單檔股票的報告
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
        
        return msg_body + signal_msg, is_buy

    except Exception as e:
        print(f"無法抓取 {ticker} 的數據：{e}")
        return None, False

# === 5. 主程式：指揮官 (您剛剛缺這一段) ===
def check_stock():
    # 設定台灣時間
    tw_timezone = timezone(timedelta(hours=8))
    current_time = datetime.now(tw_timezone).strftime('%Y-%m-%d %H:%M')
    print(f"執行時間：{current_time}")

    # 準備總訊息
    total_message = f"📅 *{current_time} 股息監控報告*\n"
    has_opportunity = False

    # 迴圈：一檔一檔檢查
    for ticker, info in targets.items():
        print(f"正在檢查 {ticker}...", end=" ")
        report, is_buy = check_stock_valuation(ticker, info)
        
        if report:
            print("完成")
            total_message += "\n" + report
            if is_buy:
                has_opportunity = True
        else:
            print("失敗")

    # 決定是否發送
    if has_opportunity:
        print("🚀 發現買點，發送通知！")
        final_msg = "🔥 *老闆，發現便宜好貨！請查看：*\n" + total_message
        send_telegram_notify(final_msg)
    else:
        print("💤 無買點，不打擾。")
        # 如果想測試有沒有成功，可以把下面這行註解拿掉：
        # send_telegram_notify("測試：機器人運作正常，但目前沒股票達標。")

# === 6. 程式進入點 ===
if __name__ == "__main__":
    check_stock()
