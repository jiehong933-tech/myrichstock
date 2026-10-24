import csv
import html
import io
import os
import re
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
    "00685L.TW": "群益臺灣加權正2",
}

# 高股息估價標的：只要設定目標殖利率
dividend_targets = {
    "00878.TW": {"name": "國泰永續高股息",   "target_yield": 0.09},
    "00919.TW": {"name": "群益台灣精選高息", "target_yield": 0.09},
    "0056.TW":  {"name": "元大高股息",       "target_yield": 0.09},
    "00713.TW": {"name": "元大台灣高息低波", "target_yield": 0.09},
}

# 今年以來漲幅：固定追蹤的標的，加上集保受益人數最多的前幾檔主動式 ETF（每次執行自動重新排名）
ytd_targets = {
    "00631L.TW": "元大台灣50正2",
    "00685L.TW": "群益臺灣加權正2",
}
TOP_ACTIVE_COUNT = 5

FREQUENCY_NAMES = {1: "年配", 2: "半年配", 4: "季配", 12: "月配"}

# 集保「股權分散表」（每週更新），用來算每檔 ETF 的受益人數
TDCC_URLS = [
    "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5",
    "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5",
]
# 證交所每日收盤資料，用來查中文名稱
TWSE_DAILY_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"

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

# === 7. 今年以來漲幅（正二 + 受益人數前五的主動式 ETF） ===
def fetch_active_etf_holders():
    """回傳 (集保資料日期, {主動式 ETF 代號: 受益人數})；主動式 ETF 的代號是 5 碼數字加 A"""
    error = None
    for url in TDCC_URLS:
        try:
            # 集保網站遇到程式預設的 User-Agent 會無限重新導向，所以用瀏覽器的
            resp = requests.get(url, headers={"User-Agent": BROWSER_UA}, timeout=60)
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            error = e
            print(f"⚠️ {url} 抓取失敗：{e}")
    else:
        raise RuntimeError(f"集保受益人數抓取失敗（{error}）")

    try:
        text = resp.content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = resp.content.decode("cp950")

    holders, data_date = {}, None
    # 欄位：資料日期, 證券代號, 持股分級, 人數, 股數, 占集保庫存數比例%
    # 持股分級 1～15 是各級距的人數，加起來就是總受益人數
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 4 or not row[2].strip().isdigit():
            continue  # 標題列
        code, level = row[1].strip(), int(row[2])
        if re.fullmatch(r"\d{5}A", code) and 1 <= level <= 15:
            holders[code] = holders.get(code, 0) + int(row[3].replace(",", ""))
            data_date = row[0].strip()
    if not holders:
        raise RuntimeError("集保資料裡找不到主動式 ETF")
    return data_date, holders

def fetch_twse_names():
    """回傳 {代號: 中文名稱}；抓不到就回傳空 dict，報告裡只顯示代號"""
    try:
        resp = requests.get(TWSE_DAILY_URL, timeout=30)
        resp.raise_for_status()
        return {item["Code"]: item["Name"] for item in resp.json()}
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        print(f"⚠️ 證交所名稱抓取失敗，只顯示代號：{e}")
        return {}

def performance(ticker, year):
    """回傳 (今年以來報酬, 成立以來報酬, 成立日)；用還原權值價計算，所以有含配息

    Yahoo 的台股 ETF 資料從基金成立日（募集期的淨值，通常是 10 元）開始，
    所以第一筆就是成立以來的起點。
    今年以來的起點是去年最後一個交易日的收盤，所以每年 1 月會自動從 0 重新算；
    今年才成立的就從成立日算起。
    """
    hist = fetch_history(ticker, "max")
    prices = (hist["Adj Close"] if "Adj Close" in hist else hist["Close"]).dropna()
    price = prices.iloc[-1]
    before = prices[prices.index.year < year]
    year_start = before.iloc[-1] if not before.empty else prices.iloc[0]
    return price / year_start - 1, price / prices.iloc[0] - 1, prices.index[0].date()

def build_ytd_section(year):
    """回傳 (區塊文字, 錯誤清單)"""
    lines, errors = [f"🏁 <b>{year} 今年以來漲幅</b>（含息）"], []

    for ticker, name in ytd_targets.items():
        print(f"正在計算 {ticker} 今年以來漲幅...")
        try:
            ytd, _, _ = performance(ticker, year)
            print(f"  今年 {ytd:+.2%}")
        except Exception as e:
            errors.append(f"{ticker} {e}"[:200])
            continue
        lines.append(f"• {html.escape(name)} ({ticker.removesuffix('.TW')})：<code>{ytd:+.2%}</code>")

    names = fetch_twse_names()
    print(f"證交所名稱：{len(names)} 筆")
    print("正在抓集保受益人數...")
    try:
        data_date, holders = fetch_active_etf_holders()
    except Exception as e:
        errors.append(str(e)[:200])
        return "\n".join(lines), errors
    top = sorted(holders.items(), key=lambda item: item[1], reverse=True)[:TOP_ACTIVE_COUNT]

    lines.append(f"\n<b>主動式 ETF 受益人數前 {len(top)} 名</b>（集保 {data_date}）")
    for rank, (code, count) in enumerate(top, 1):
        # 上市的 Yahoo 代號是 .TW，上櫃是 .TWO；證交所清單抓不到時兩個都試
        if names:
            tickers = [f"{code}.TW"] if code in names else [f"{code}.TWO"]
        else:
            tickers = [f"{code}.TW", f"{code}.TWO"]
        print(f"正在計算 {code}（受益人 {count} 人）...")
        for ticker in tickers:
            try:
                ytd, since_inception, founded = performance(ticker, year)
                print(f"  {ticker} 今年 {ytd:+.2%}，成立以來 {since_inception:+.2%}（{founded} 成立）")
                break
            except Exception as e:
                error = e
        else:
            errors.append(f"{code} {error}"[:200])
            continue
        lines.append(f"{rank}. {html.escape(names.get(code, ''))} ({code})｜{count / 10000:.1f} 萬人")
        lines.append(
            f"   今年 <code>{ytd:+.2%}</code>｜成立以來 <code>{since_inception:+.2%}</code>（{founded} 成立）"
        )
    return "\n".join(lines), errors

# === 8. 主程式 ===
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

    ytd_section, ytd_errors = build_ytd_section(now.year)
    for e in ytd_errors:
        print(f"❌ {e}")
    errors += ytd_errors

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
    parts.append(ytd_section)
    if valuation_blocks:
        parts.append("💰 <b>高股息估價</b>")
        parts += valuation_blocks
    if errors:
        parts.append("⚠️ <b>抓取失敗</b>\n" + "\n".join(html.escape(e) for e in errors))

    sent = send_telegram_notify(token, chat_id, "\n\n".join(parts))

    # 有任何失敗就回傳 1，讓 GitHub Actions 顯示紅燈並寄信通知
    return 0 if sent and not errors else 1

# === 9. 程式進入點 ===
if __name__ == "__main__":
    sys.exit(main())
