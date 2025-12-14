import time
import json
import yfinance as yf
import feedparser
import urllib.parse
from kafka import KafkaProducer
import sys
import os
import pandas as pd
import random
import socket
import requests
from typing import List, Dict, Optional

socket.setdefaulttimeout(20)  # Global timeout for network operations
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.config import (
    KAFKA_BOOTSTRAP_SERVERS, 
    KAFKA_TOPIC_NEWS, 
    TICKERS, 
    SLEEP_TIME, 
    KAFKA_TOPIC_HISTORY, 
    KAFKA_TOPIC_HOT_NEWS, 
    ALERT_THRESHOLDS
)

# Simulation of different user agents to avoid blocking
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36"
]

TICKER_MAPPING = {
    "STLAP.PA": "Stellantis",
    "STMPA.PA": "STMicroelectronics",
    "ORA.PA":   "Orange S.A.",
    "ENGI.PA":  "Engie",
    "ALHPI.PA": "Hopium",
    "CS.PA":    "AXA Assurance",
    "DCAM.PA":  "AMUNDI PEA MONDE MSCI WORLD",     
    "ETZ.PA":   "BNP Paribas Easy Stoxx Europe600",       
}

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
        print("[Producer] Connexion Kafka OK")
        return producer
    except Exception as e:
        print(f"[Producer] Erreur Kafka CRITIQUE : {e}")
        return None

# --- PART 1 : GOOGLE NEWS RSS ---
def fetch_google_rss(producer: KafkaProducer, ticker: str, seen_ids: set) -> None:
    """
    Search Google News RSS for the given ticker and send new articles to Kafka.
    """
    search_term = TICKER_MAPPING.get(ticker, ticker)
    print(f"🔍 Recherche Google pour : {search_term} (Ticker: {ticker})")
    
    # when:1d = dernières 24h pour éviter le bruit
    encoded_query = urllib.parse.quote(search_term)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}+when:1d&hl=fr&gl=FR&ceid=FR:fr"
    
    try:
        # Use of requests to avoid 443 errors
        response = requests.get(rss_url, headers=get_random_header(), timeout=10)
        if response.status_code != 200:
            print(f"⚠️ [RSS] {ticker} HTTP Error {response.status_code}")
            return

        feed = feedparser.parse(response.content)
        for entry in feed.entries[:3]:
            
            # unique ID to avoid duplicates
            news_id = str(hash(entry.link))
            if news_id in seen_ids:
                continue

            # Date handling
            pub_time = int(time.time())
            if hasattr(entry, 'published_parsed'):
                pub_time = int(time.mktime(entry.published_parsed))

            payload = {
                "ticker": ticker,
                "title": entry.title,
                "publisher": entry.source.title if 'source' in entry else "Google News",
                "link": entry.link,
                "summary": f"Source: {entry.source.title}", 
                "publish_time": pub_time,
                "type": "news",
                "source": "google_rss", # Tag pour différencier de Yahoo
                "id": news_id
            }
            
            producer.send(KAFKA_TOPIC_NEWS, value=payload)
            print(f"[Google RSS] {ticker} : {entry.title[:30]}...")
            seen_ids.add(news_id)

    except Exception as e:
        print(f"Erreur RSS {ticker}: {e}")

# --- PART 2 : YAHOO FINANCE & TECHNICAL ANALYSIS ---
def send_history_data(producer: KafkaProducer, stock: yf.Ticker, ticker: str) -> None:
    """Send Daily history (for charts)"""
    try:
        hist = stock.history(period="1y") 
        if hist.empty: return
        
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
        producer.send(KAFKA_TOPIC_HISTORY, value=history_payload)
    except Exception as e:
        print(f"[History] Error {ticker}: {e}")

def generate_intraday_metrics(stock: yf.Ticker, ticker: str) -> Optional[Dict]:
    """Calculate 10min, 1h, 6h variations."""
    try:
        # We fetch 2 days of 5min data to ensure enough points
        df = stock.history(period="2d", interval="5m")
        if df.empty or len(df) < 10: return None

        current_price = df['Close'].iloc[-1]

        last_price_time = df. index[-1]
        last_price_timestamp = int(last_price_time.timestamp())
        last_price_datetime = last_price_time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Definitions of indexes:
        # 12 * 5min = 60min (1h)
        # 72 * 5min = 360min (6h)
        # 144 * 5min = 720min (12h - often unavailable in simple intraday if the market just opened)
        
        intervals = { "10min": 2, "30min": 6, "1h": 12, "3h": 36, "6h": 72 }
        metrics_text = f"Momentum Analysis {ticker} (Price: {current_price:.2f}):\n"

        for label, idx in intervals.items():
            if len(df) > idx:
                past_price = df['Close'].iloc[-(idx+1)]
                var_pct = ((current_price - past_price) / past_price) * 100 if past_price != 0 else 0
                emoji = "🟩" if var_pct > 0 else "🟥" if var_pct < 0 else "⬜"
                metrics_text += f"- {label}: {emoji} {var_pct:+.2f}%\n"

        prev_close = stock.fast_info.previous_close
        
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
            "opening_price": float(df['Open'].iloc[-1]),
            "price_6h_ago": float(df['Close'].iloc[-(72+1)]) if len(df) > 73 else 0.0,
            "price_3h_ago": float(df['Close'].iloc[-(36+1)]) if len(df) > 37 else 0.0,
            "price_1h_ago": float(df['Close'].iloc[-(12+1)]) if len(df) > 13 else 0.0,
            "price_30min_ago": float(df['Close'].iloc[-(6+1)]) if len(df) > 7 else 0.0,
            "price_10min_ago": float(df['Close'].iloc[-(2+1)]) if len(df) > 3 else 0.0,
            "regularMarketTime": last_price_timestamp,
            "currency": stock.info.get('currency', 'UKN'),
            "market_state": stock.info.get('marketState', 'UKN'),
            "id": f"LATEST_METRICS_{ticker}"
        }
        return payload
    except Exception as e:
        print(f"⚠️ [Metrics] Erreur {ticker}: {e}")
        return None
    

def analyze_technicals_daily(stock: yf.Ticker, ticker: str) -> Optional[Dict]:
    """Calculate daily technical indicators and generate a report."""
    try:
        hist = stock.history(period="1y") 
        if hist.empty: return None

        current = hist['Close'].iloc[-1]

        last_price_date = hist.index[-1]
        last_price_timestamp = int(last_price_date.timestamp())
        last_price_datetime = last_price_date.strftime("%Y-%m-%d %H:%M:%S")
        

        ma_10 = hist['Close'].rolling(window=10).mean().iloc[-1]
        ma_50 = hist['Close'].rolling(window=50).mean().iloc[-1]
        ma_200 = hist['Close'].rolling(window=200).mean().iloc[-1]
        
        trend = "NEUTRAL"
        if current > ma_50: trend = "BULLISH"
        if current < ma_50: trend = "BEARISH"

        tech_text = (
            f"Technical Analysis {ticker}. Price: {current:.2f}. "
            f"Medium Term Trend (MA50): {trend}. "
            f"MA 50d: {ma_50:.2f}. "
            f"MA 200d: {ma_200:.2f}."
        )

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
            "market_state": stock.info.get('marketState', 'UKN'),
            "currency": stock.info.get('currency', 'UKN'),
            "id": f"LATEST_TECH_{ticker}"
        }
        return tech_payload
    except Exception as e:
        print(f"⚠️ [Technical] Erreur {ticker}: {e}")
        return None


def fetch_and_send_data(producer: KafkaProducer, seen_news: set) -> None:
    """Fetch data from Yahoo Finance and Google RSS, send to Kafka."""
    print("🔄 [Producer] Scan Real Time (Price + News Yahoo + Google RSS)...")

    # Shuffle the list of tickers to avoid always querying in the same order
    tickers_shuffled = TICKERS.copy()
    random.shuffle(tickers_shuffled)
    
    for ticker in tickers_shuffled:
        
        try:
            # 1. Fetch Google RSS (Streaming News)
            fetch_google_rss(producer, ticker, seen_news)
        
            # 2. Fetch Yahoo (Market Data & Official News)
            stock = yf.Ticker(ticker)

            # (Optional) Quick check if the API responds
            # If fast_info fails, skip the entire ticker to save time
            _ = stock.fast_info.last_price 
            
            # Historical Chart
            send_history_data(producer, stock, ticker)

            # Intraday Bulletin
            metrics = generate_intraday_metrics(stock, ticker)
            if metrics:
                producer.send(KAFKA_TOPIC_HOT_NEWS, value=metrics)

            # Technical Analysis Daily
            tech_data = analyze_technicals_daily(stock, ticker)
            if tech_data:
                producer.send(KAFKA_TOPIC_NEWS, value=tech_data)

            # News Yahoo
            news = stock.news
            if news:
                for item in news:
                    content = item.get('content', item)
                    news_id = item.get('uuid', item.get('id'))
                    title = content.get('title')
                    
                    if not title or not news_id: continue

                    if news_id not in seen_news:
                        link_obj = content.get('clickThroughUrl')
                        link = link_obj.get('url') if isinstance(link_obj, dict) else link_obj
                        
                        # Parsing date safe
                        try:
                            pub_date = content.get('pubDate')
                            pub_ts = int(time.mktime(time.strptime(pub_date, "%Y-%m-%dT%H:%M:%SZ")))
                        except:
                            pub_ts = int(time.time())

                        news_payload = {
                            "ticker": ticker,
                            "title": title,
                            "publisher": content.get('provider', {}).get('displayName', 'Yahoo'),
                            "link": link,
                            "summary": content.get('summary'),
                            "publish_time": pub_ts,
                            "type": "news",
                            "source": "yahoo_api",
                            "market_state": stock.info.get('marketState', 'UKN'),
                            "currency": stock.info.get('currency', 'UKN'),
                            "id": news_id
                        }
                        producer.send(KAFKA_TOPIC_NEWS, value=news_payload)
                        print(f"📰 [Yahoo] {ticker} :{title[:20]}...")
                        seen_news.add(news_id)

        except Exception as e:
            print(f"⚠️ [General] Error on {ticker}: {e}")

        # Random sleep between tickers to avoid rate limiting
        sleep_duration = random.uniform(2.0, 5.0)
        time.sleep(sleep_duration)

    producer.flush()

if __name__ == "__main__":
    producer = create_producer()
    seen = set() # Set partagé entre Yahoo et Google pour les IDs
    if producer:
        while True:
            fetch_and_send_data(producer, seen)

            print(f"💤 Pause {SLEEP_TIME}s...")
            time.sleep(SLEEP_TIME)