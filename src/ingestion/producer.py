# Library imports
import time
import json
import yfinance as yf
import feedparser
import urllib.parse
from kafka import KafkaProducer
import sys
from datetime import datetime
import os
import pandas as pd
import random
import socket
import requests
from typing import Dict, Optional

# --- SETUP ---
socket.setdefaulttimeout(20)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.config import (
    KAFKA_BOOTSTRAP_SERVERS,
    KAFKA_TOPIC_NEWS,
    TICKERS,
    SLEEP_TIME,
    KAFKA_TOPIC_HISTORY,
    KAFKA_TOPIC_HOT_NEWS,
    KAFKA_TOPIC_DAILY_SUMMARY
)

# Simulation of different user agents to avoid blocking
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36"
]

TICKER_MAPPING = {
    "MC.PA": "LVMH Moët Hennessy",
    "TTE.PA": "TotalEnergies",
    "OR.PA": "L'Oréal Finance",
    "RMS.PA": "Hermès International",
    "SAN.PA": "Sanofi",
    "SAF.PA": "Safran",
    "SU.PA": "Schneider Electric",
    "AI.PA": "Air Liquide",
    "BNP.PA": "BNP Paribas",
    "DG.PA": "Vinci Construction"
}


# --- HELPERS ---

def get_random_header() -> dict:
    """Return a random User-Agent header."""
    return {"User-Agent": random.choice(USER_AGENTS)}


def create_producer() -> Optional[KafkaProducer]:
    """Create and return a Kafka producer. Handle connection errors."""
    try:
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda x: json.dumps(x).encode('utf-8'),
            request_timeout_ms=10000,
            retries=3
        )
        print("[Producer] Connected to Kafka successfully.")
        return producer
    except Exception as e:
        print(f"[Producer] Critical Kafka Error: {e}")
        return None


# --- PART 1 : GOOGLE NEWS RSS FEED ---
def fetch_google_rss(producer: KafkaProducer, ticker: str,
                     seen_ids: set) -> None:
    """Search Google News RSS for the given ticker and send articles."""
    search_term = TICKER_MAPPING.get(ticker, ticker)
    print(f"🔍 Searching Google News for: {search_term} (Ticker: {ticker})")

    encoded_query = urllib.parse.quote(search_term)
    rss_url = (f"https://news.google.com/rss/search?q={encoded_query}"
               f"+when:1d&hl=fr&gl=FR&ceid=FR:fr")

    try:
        response = requests.get(rss_url, headers=get_random_header(),
                                timeout=10)
        if response.status_code != 200:
            print(f"⚠️ [RSS] {ticker} HTTP Error {response.status_code}")
            return

        feed = feedparser.parse(response.content)
        for entry in feed.entries[:3]:
            news_id = str(hash(entry.link))
            if news_id in seen_ids:
                continue

            pub_time = int(time.time())
            if hasattr(entry, 'published_parsed'):
                pub_time = int(time.mktime(entry.published_parsed))

            payload = {
                "ticker": ticker,
                "title": entry.title,
                "publisher": (entry.source.title if 'source' in entry
                              else "Google News"),
                "link": entry.link,
                "summary": f"Source: {entry.source.title}",
                "publish_time": pub_time,
                "type": "news",
                "source": "google_rss",
                "id": news_id
            }

            producer.send(KAFKA_TOPIC_NEWS, key=ticker.encode('utf-8'),
                          value=payload)
            print(f"[Google RSS] {ticker} : {entry.title[:30]}...")
            seen_ids.add(news_id)

    except Exception as e:
        print(f"Erreur RSS {ticker}: {e}")


# --- PART 2 : YAHOO FINANCE & TECHNICAL ANALYSIS ---

def send_history_data(producer: KafkaProducer, ticker: str,
                      hist: pd.DataFrame) -> None:
    """Send Daily history (for charts) using pre-fetched data."""
    try:
        if hist.empty:
            return

        last_row = hist.iloc[-1]
        history_payload = {
            "ticker": ticker,
            "date": str(last_row.name),
            "Open": float(last_row['Open']),
            "High": float(last_row['High']),
            "Low": float(last_row['Low']),
            "Close": float(last_row['Close']),
            "Volume": int(last_row['Volume'])
        }
        producer.send(KAFKA_TOPIC_HISTORY, key=ticker.encode('utf-8'),
                      value=history_payload)
    except Exception as e:
        print(f"[History] Error {ticker}: {e}")


# --- PART 3 : DAILY SUMMARY ---
def send_daily_summary(producer: KafkaProducer, ticker: str,
                       hist: pd.DataFrame) -> None:
    """Send a daily summary message to Kafka using pre-fetched data."""
    try:
        if hist.empty or len(hist) < 2:
            return

        today = hist.iloc[-1]
        yesterday = hist.iloc[-2]

        open_price = float(today['Open'])
        close_price = float(today['Close'])
        volume = int(today['Volume'])
        day_low = float(today['Low'])
        day_high = float(today['High'])
        variation_pct = (((close_price - yesterday['Close']) /
                          yesterday['Close']) * 100
                         if yesterday['Close'] != 0 else 0.0)

        summary_text = (
            f"Daily Summary for {ticker}:\n"
            f"- Open: {open_price:.2f}\n"
            f"- Close: {close_price:.2f}\n"
            f"- Variation: {variation_pct:.2f}%\n"
            f"- Volume: {volume}\n"
            f"- Low: {day_low:.2f}\n"
            f"- High: {day_high:.2f}\n"
        )

        payload = {
            "ticker": ticker,
            "title": f"Daily Summary {ticker}",
            "summary": summary_text,
            "content": summary_text,
            "link": f"https://finance.yahoo.com/quote/{ticker}",
            "publish_time": int(time.time()),
            "type": "daily_summary",
            "source": "system_summary",
            "id": f"DAILY_SUMMARY_{ticker}_{int(time.time())}"
        }

        producer.send(KAFKA_TOPIC_DAILY_SUMMARY,
                      key=ticker.encode('utf-8'), value=payload)

    except Exception as e:
        print(f"[Daily Summary] Error {ticker}: {e}")


# --- PART 4 : INTRADAY METRICS & TECHNICAL ANALYSIS ---
def generate_intraday_metrics(stock: yf.Ticker,
                              ticker: str) -> Optional[Dict]:
    """Calculate 10min, 1h, 6h variations."""
    try:
        df = stock.history(period="2d", interval="5m")
        if df.empty or len(df) < 10:
            return None

        info = stock.info
        if info is None:
            print(f"⚠️ [Metrics] No info for {ticker}")
            return None

        current_price = info.get('currentPrice',
                                 info.get('regularMarketPrice'))
        if current_price is None:
            current_price = df['Close'].iloc[-1]

        current_price = float(current_price)
        last_price_timestamp = info.get('regularMarketTime',
                                        int(time.time()))

        intervals = {"10min": 2, "30min": 6, "1h": 12, "3h": 36, "6h": 72}
        metrics_text = (f"Momentum Analysis {ticker} "
                        f"(Price: {current_price:.2f}):\n")

        for label, idx in intervals.items():
            if len(df) > idx:
                past_price = df['Close'].iloc[-(idx + 1)]
                var_pct = (((current_price - past_price) / past_price) * 100
                           if past_price != 0 else 0)
                emoji = ("🟩" if var_pct > 0 else "🟥"
                         if var_pct < 0 else "⬜")
                metrics_text += f"- {label}:  {emoji} {var_pct:.2f}%\n"

        prev_close = info.get('previousClose',
                              info.get('regularMarketPreviousClose', 0.0))
        open_price = info.get('open', info.get('regularMarketOpen', 0.0))
        currency = info.get('currency', 'EUR')

        payload = {
            "ticker": ticker,
            "title": f"Momentum Intraday {ticker}",
            "summary": metrics_text,
            "content": metrics_text,
            "link": f"https://finance.yahoo.com/quote/{ticker}",
            "publish_time": int(time.time()),
            "type": "intraday_metrics",
            "source": "system_metrics",
            "current_price": float(current_price),
            "last_close": float(prev_close) if prev_close else 0.0,
            "opening_price": float(open_price) if open_price else 0.0,
            "price_6h_ago": (float(df['Close'].iloc[-(72 + 1)])
                             if len(df) > 73 else 0.0),
            "price_3h_ago": (float(df['Close'].iloc[-(36 + 1)])
                             if len(df) > 37 else 0.0),
            "price_1h_ago": (float(df['Close'].iloc[-(12 + 1)])
                             if len(df) > 13 else 0.0),
            "price_30min_ago": (float(df['Close'].iloc[-(6 + 1)])
                                if len(df) > 7 else 0.0),
            "price_10min_ago": (float(df['Close'].iloc[-(2 + 1)])
                                if len(df) > 3 else 0.0),
            "regularMarketTime": last_price_timestamp,
            "currency": currency,
            "market_state": info.get('marketState', 'N/C'),
            "id": f"LATEST_METRICS_{ticker}"
        }
        return payload
    except Exception as e:
        print(f"⚠️ [Metrics] Erreur {ticker}: {e}")
        return None


# --- PART 5 : TECHNICAL ANALYSIS DAILY ---
def analyze_technicals_daily(ticker: str, hist: pd.DataFrame,
                             stock: yf.Ticker) -> Optional[Dict]:
    """Calculate daily technical indicators using pre-fetched data."""
    try:
        if hist.empty:
            return None

        info = stock.info
        if info is None:
            return None

        current = info.get('currentPrice',
                           info.get('regularMarketPrice'))
        if current is None:
            current = hist['Close'].iloc[-1]
        current = float(current)

        last_price_timestamp = info.get('regularMarketTime',
                                        int(time.time()))

        ma_10 = hist['Close'].rolling(window=10).mean().iloc[-1]
        ma_50 = hist['Close'].rolling(window=50).mean().iloc[-1]
        ma_200 = hist['Close'].rolling(window=200).mean().iloc[-1]

        trend = "NEUTRAL"
        if current > ma_50:
            trend = "BULLISH"
        if current < ma_50:
            trend = "BEARISH"

        tech_text = (
            f"Technical Analysis {ticker}.  Price: {current:.2f}. "
            f"Medium Term Trend (MA50): {trend}. "
            f"MA 50d: {ma_50:.2f}. "
            f"MA 200d: {ma_200:.2f}."
        )

        currency = info.get('currency', 'EUR')

        tech_payload = {
            "ticker": ticker,
            "title": f"Technical Analysis {ticker} ({trend})",
            "summary": tech_text,
            "content": tech_text,
            "link": f"https://finance.yahoo.com/quote/{ticker}",
            "publish_time": int(time.time()),
            "type": "technical",
            "current_price": float(current),
            "mean_10": float(ma_10) if not pd.isna(ma_10) else 0.0,
            "mean_50": float(ma_50),
            "mean_200": float(ma_200) if not pd.isna(ma_200) else 0.0,
            "regularMarketTime": last_price_timestamp,
            "market_state": info.get('marketState', 'N/C'),
            "currency": currency,
            "id": f"LATEST_TECH_{ticker}"
        }
        return tech_payload
    except Exception as e:
        print(f"⚠️ [Technical] Error {ticker}:  {e}")
        return None


# --- MAIN LOOP ---
def fetch_and_send_data(producer: KafkaProducer, seen_news: set) -> None:
    """Fetch data from Yahoo Finance and Google RSS, send to Kafka."""
    print("🔄 [Producer] Scan Real Time"
          " (Price + News Yahoo + Google RSS)...")

    tickers_shuffled = TICKERS.copy()
    random.shuffle(tickers_shuffled)

    for ticker in tickers_shuffled:

        try:
            fetch_google_rss(producer, ticker, seen_news)
            stock = yf.Ticker(ticker)

            try:
                info = stock.info
                if info is None or 'symbol' not in info:
                    if not info:
                        print(f"⚠️ [Yahoo] No info for {ticker}")
                        continue
            except Exception as e:
                print(f"⚠️ [Yahoo] Error connecting to info"
                      f" for {ticker} : {e}")
                continue

            try:
                hist_daily = stock.history(period="1y")
            except Exception as e:
                print(f"⚠️ [Yahoo] Error fetching Daily history"
                      f" for {ticker}: {e}")
                hist_daily = pd.DataFrame()

            if not hist_daily.empty:
                send_history_data(producer, ticker, hist_daily)
            if not hist_daily.empty:
                send_daily_summary(producer, ticker, hist_daily)

            metrics = generate_intraday_metrics(stock, ticker)
            if metrics:
                producer.send(KAFKA_TOPIC_HOT_NEWS,
                              key=ticker.encode('utf-8'), value=metrics)

            if not hist_daily.empty:
                tech_data = analyze_technicals_daily(ticker, hist_daily,
                                                     stock)
                if tech_data:
                    producer.send(KAFKA_TOPIC_NEWS,
                                  key=ticker.encode('utf-8'),
                                  value=tech_data)

            news = stock.news
            if news:
                for item in news:
                    content = item.get('content', item)
                    news_id = item.get('uuid', item.get('id'))
                    title = content.get('title')

                    if not title or not news_id:
                        continue

                    if news_id not in seen_news:
                        link_obj = content.get('clickThroughUrl')
                        link = (link_obj.get('url')
                                if isinstance(link_obj, dict) else link_obj)

                        try:
                            pub_date = content.get('pubDate')
                            pub_ts = int(time.mktime(
                                time.strptime(pub_date,
                                              "%Y-%m-%dT%H:%M:%SZ")))
                        except Exception:
                            pub_ts = int(time.time())

                        curr = (stock.info.get('currency', 'UKN')
                                if stock.info else 'UKN')

                        news_payload = {
                            "ticker": ticker,
                            "title": title,
                            "publisher": (content.get('provider', {})
                                          .get('displayName', 'Yahoo')),
                            "link": link,
                            "summary": content.get('summary'),
                            "publish_time": pub_ts,
                            "type": "news",
                            "source": "yahoo_api",
                            "market_state": stock.info.get('marketState', 'N/C'),
                            "currency": curr,
                            "id": news_id
                        }

                        producer.send(KAFKA_TOPIC_NEWS,
                                      key=ticker.encode('utf-8'),
                                      value=news_payload)
                        print(f"📰 [Yahoo] {ticker} :{title[:20]}...")
                        seen_news.add(news_id)

        except Exception as e:
            print(f"⚠️ [General] Error on {ticker}: {e}")

        sleep_duration = random.uniform(2.0, 5.0)
        time.sleep(sleep_duration)

    producer.flush()


def send_initial_history(producer: KafkaProducer, ticker: str,
                         days: int = 180) -> None:
    """Send historical data for charts and daily summaries."""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=f"{days}d")

        if hist.empty:
            return

        for date, row in hist.iterrows():
            history_payload = {
                "ticker": ticker,
                "date": str(date),
                "Open": float(row['Open']),
                "High": float(row['High']),
                "Low": float(row['Low']),
                "Close": float(row['Close']),
                "Volume": int(row['Volume'])
            }
            producer.send(KAFKA_TOPIC_HISTORY,
                          key=ticker.encode('utf-8'),
                          value=history_payload)

            idx = hist.index.get_loc(date)
            if idx > 0:
                prev_row = hist.iloc[idx - 1]
                close = float(row['Close'])
                prev_close = float(prev_row['Close'])
                var_pct = ((close - prev_close) / prev_close) * 100

                ts = int(date.timestamp())

                summary_text = (
                    f"Daily Summary for {ticker}"
                    f" on {date.strftime('%Y-%m-%d')}:\n"
                    f"- Open: {float(row['Open']):.2f}\n"
                    f"- High: {float(row['High']):.2f}\n"
                    f"- Low: {float(row['Low']):.2f}\n"
                    f"- Close: {close:.2f}\n"
                    f"- Variation: {var_pct:.2f}%\n"
                    f"- Volume: {int(row['Volume'])}\n"
                )

                payload = {
                    "ticker": ticker,
                    "title": f"Daily Summary {ticker}",
                    "summary": summary_text,
                    "content": summary_text,
                    "link": f"https://finance.yahoo.com/quote/{ticker}",
                    "publish_time": ts,
                    "type": "daily_summary",
                    "source": "backfill",
                    "id": f"DAILY_SUMMARY_{ticker}_{ts}"
                }
                producer.send(KAFKA_TOPIC_DAILY_SUMMARY,
                              key=ticker.encode('utf-8'),
                              value=payload)

        print(f"✅ [Init] Complete backfill for {ticker}")

    except Exception as e:
        print(f"❌ [Init] Error for {ticker}: {e}")


if __name__ == "__main__":
    producer = create_producer()
    seen = set()

    if producer:
        print("📊 [Producer] Sending initial history data...")
        for ticker in TICKERS:
            send_initial_history(producer, ticker, days=180)
        producer.flush()
        print("✅ [Producer] Initial history sent!")

        while True:
            fetch_and_send_data(producer, seen)
            print(f"💤 Pause {SLEEP_TIME}s...")
            time.sleep(SLEEP_TIME)