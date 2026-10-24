import html
import os
import sys
import time
from datetime import datetime, timezone, timedelta

import requests
import yfinance as yf

TW_TZ = timezone(timedelta(hours=8))

# === 1. 通知設定 ===
# True：每個交易日都發送報告；False：只在有買點或出錯時才發送
NOTIFY_EVERY_DAY = True

# === 2. 設定監控股票 ===
# 每一檔的近一年配息都會自動從 Yahoo 計算，不用手動填配息

# 只看報價的標的（股價、漲跌、近一年配息、殖利率）
quote_targets = {
    "0050.TW":   "元大台灣50",
    "00631L.TW": "元大台灣50正2",
}

# 高股息估價標的：只要設定目標殖利率
dividend_targets = {
    "00878.TW": {"name": "國泰永續高股息",   "target_yield": 0.09},
    "00919.TW": {"name": "群益台灣精選高息", "target_yield": 0.09},
    "0056.TW":  {"name": "元大高股息",       "target_yield": 0.09},
    "00713.TW": {"name": "元大台灣高息低波", "target_yield": 0.09},
}

FREQUENCY_NAMES = {1: "年配", 2: "半年配", 4: "季配", 12: "月配"}

# === 3. 發送 Telegram 通知函式 ===
def send_telegram_notify(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    try:
        resp = requests.post(url, data=payload, timeout=15)
    except requests.RequestException as e:
        print(f"❌ 發送失敗：{e}")
        return False

    # Token 錯誤（401）、Chat ID 錯誤（400 chat not found）都不會丟例外，要自己檢查
    if not resp.ok:
        print(f"❌ Telegram 回傳錯誤 {resp.status_code}：{resp.text}")
        return False

    print("✅ Telegram 通知已發送")
    return True

# === 4. 抓股價資料（失敗會重試） ===
def fetch_history(ticker, period):
    error = "沒有資料"
    for attempt in range(3):
        if attempt:
            time.sleep(10 * attempt)
        try:
            # auto_adjust=False：拿交易所實際收盤價，不是還原權值後的價格
            hist = yf.Ticker(ticker).history(period=period, auto_adjust=False)
            if "Close" in hist and hist["Close"].notna().any():
                return hist
        except Exception as e:
            error = e
    raise RuntimeError(f"抓取失敗（{error}）")

def price_change(closes):
    """回傳 (最新收盤價, 漲跌, 漲跌幅%)"""
    price = float(closes.iloc[-1])
    if len(closes) < 2:
        return price, 0.0, 0.0
    prev = float(closes.iloc[-2])
    return price, price - prev, (price - prev) / prev * 100

def format_change(change, pct):
    if change > 0:
        return f"▲{change:.2f} (+{pct:.2f}%)"
    if change < 0:
        return f"▼{-change:.2f} ({pct:.2f}%)"
    return "平盤"

def recent_year_dividend(hist):
    """回傳 (近一年配息, 一年配幾次)；近一年沒有配息就回傳 (0.0, 0)

    一年配幾次是從過去兩年的配息間隔自動判斷，再加總最近那幾次。
    不直接加總「365 天內」的配息，是因為除息日每年差個幾天，
    就會多算或少算一次（例如季配變成算到 5 次）。
    """
    if "Dividends" not in hist:
        return 0.0, 0
    divs = hist["Dividends"][hist["Dividends"] > 0]
    last_day = hist.index[-1]
    divs = divs[divs.index > last_day - timedelta(days=730)]
    # 最近一次配息在 13 個多月前，就當作近一年沒有配息
    if divs.empty or last_day - divs.index[-1] > timedelta(days=400):
        return 0.0, 0

    if len(divs) == 1:
        times = 1
    else:
        gap_days = divs.index.to_series().diff().dt.days.median()
        times = min(12, max(1, round(365 / gap_days)))
    return float(divs.tail(times).sum()), times

def format_frequency(times):
    return FREQUENCY_NAMES.get(times, f"一年 {times} 次")

# === 5. 報價（0050、正二） ===
def build_quote(ticker, name):
    hist = fetch_history(ticker, "2y")
    closes = hist["Close"].dropna()
    price, change, pct = price_change(closes)
    dividend, times = recent_year_dividend(hist)
    print(f"  收盤 {price:.2f}，近一年配息 {dividend:.3f}（{times} 次）")

    code = ticker.removesuffix(".TW")
    lines = [f"• {html.escape(name)} ({code})：<code>{price:.2f}</code> {format_change(change, pct)}"]
    if times:
        lines.append(
            f"   近一年配息 <code>{dividend:.3f}</code> 元（{format_frequency(times)}）"
            f"｜殖利率 <code>{dividend / price * 100:.2f}%</code>"
        )
    else:
        lines.append("   近一年沒有配息")
    return "\n".join(lines), closes.index[-1].date()

# === 6. 高股息估價 ===
def build_valuation(ticker, info):
    hist = fetch_history(ticker, "2y")
    closes = hist["Close"].dropna()
    price, change, pct = price_change(closes)
    dividend, times = recent_year_dividend(hist)
    print(f"  收盤 {price:.2f}，近一年配息 {dividend:.3f}（{times} 次）")
    if not times:
        raise RuntimeError("抓不到近一年的配息資料")

    cheap_price = dividend / info["target_yield"]
    current_yield = dividend / price * 100
    is_buy = price <= cheap_price

    code = ticker.removesuffix(".TW")
    lines = [
        f"📊 <b>{html.escape(info['name'])} ({code})</b>",
        f"💰 目前股價：<code>{price:.2f}</code> {format_change(change, pct)}",
        f"💵 近一年配息：<code>{dividend:.3f}</code> 元（{format_frequency(times)}）",
        f"📈 目前殖利率：<code>{current_yield:.2f}%</code>",
        f"📉 目標買價：<code>{cheap_price:.2f}</code>（殖利率 {info['target_yield'] * 100:.1f}%）",
    ]
    if is_buy:
        lines.append(f"🔴 <b>【快買進！價格甜了】</b>比目標便宜 {cheap_price - price:.2f} 元")
    else:
        lines.append(f"🟢 <b>【觀望】</b>還差 {price - cheap_price:.2f} 元")
    return "\n".join(lines), is_buy, closes.index[-1].date()

# === 7. 主程式 ===
def main():
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("CHAT_ID")
    if not token or not chat_id:
        print("❌ 錯誤：沒有設定 TELEGRAM_TOKEN 或 CHAT_ID（請檢查 GitHub Secrets）")
        return 1

    now = datetime.now(TW_TZ)
    print(f"執行時間：{now:%Y-%m-%d %H:%M}")

    quote_lines, valuation_blocks, errors, data_dates = [], [], [], []
    has_opportunity = False

    for ticker, name in quote_targets.items():
        print(f"正在檢查 {ticker}...")
        try:
            line, data_date = build_quote(ticker, name)
        except Exception as e:
            print(f"❌ {ticker} {e}")
            errors.append(f"{ticker} {e}"[:200])
            continue
        quote_lines.append(line)
        data_dates.append(data_date)

    for ticker, info in dividend_targets.items():
        print(f"正在檢查 {ticker}...")
        try:
            block, is_buy, data_date = build_valuation(ticker, info)
        except Exception as e:
            print(f"❌ {ticker} {e}")
            errors.append(f"{ticker} {e}"[:200])
            continue
        valuation_blocks.append(block)
        data_dates.append(data_date)
        has_opportunity = has_opportunity or is_buy

    # 排程執行時，最新資料不是今天就代表今天休市（例如國定假日），不重複發送
    latest_date = max(data_dates) if data_dates else None
    is_scheduled = os.environ.get("GITHUB_EVENT_NAME") == "schedule"
    if is_scheduled and not errors and latest_date < now.date():
        print(f"💤 最新資料是 {latest_date}，今天休市，不發送。")
        return 0

    if not (NOTIFY_EVERY_DAY or has_opportunity or errors):
        print("💤 無買點，不打擾。")
        return 0

    title = f"📅 <b>{now:%Y-%m-%d %H:%M} 股市日報</b>"
    if latest_date and latest_date != now.date():
        title += f"（資料日 {latest_date}）"
    parts = [title]
    if has_opportunity:
        parts.append("🔥 <b>老闆，發現便宜好貨！</b>")
    if quote_lines:
        parts.append("📈 <b>報價</b>\n" + "\n".join(quote_lines))
    if valuation_blocks:
        parts.append("💰 <b>高股息估價</b>")
        parts += valuation_blocks
    if errors:
        parts.append("⚠️ <b>抓取失敗</b>\n" + "\n".join(html.escape(e) for e in errors))

    sent = send_telegram_notify(token, chat_id, "\n\n".join(parts))

    # 有任何失敗就回傳 1，讓 GitHub Actions 顯示紅燈並寄信通知
    return 0 if sent and not errors else 1

# === 8. 程式進入點 ===
if __name__ == "__main__":
    sys.exit(main())
