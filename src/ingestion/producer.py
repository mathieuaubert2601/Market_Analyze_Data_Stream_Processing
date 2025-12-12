import time
import json
import yfinance as yf
import feedparser
import urllib.parse
from kafka import KafkaProducer
import sys
import os
import pandas as pd # Nécessaire pour manipuler les timeframes

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
# On importe ALERT_THRESHOLDS et KAFKA_TOPIC_HOT_NEWS
from src.config import (
    KAFKA_BOOTSTRAP_SERVERS, 
    KAFKA_TOPIC_NEWS, 
    TICKERS, 
    SLEEP_TIME, 
    KAFKA_TOPIC_HISTORY, 
    KAFKA_TOPIC_HOT_NEWS, 
    ALERT_THRESHOLDS
)

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

def create_producer():
    try:
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda x: json.dumps(x).encode('utf-8')
        )
        print("✅ [Producer] Connexion Kafka OK")
        return producer
    except Exception as e:
        print(f"❌ [Producer] Erreur Kafka : {e}")
        return None

# --- PARTIE 1 : GOOGLE NEWS RSS (NOUVEAU) ---
def fetch_google_rss(producer, ticker, seen_ids):
    """
    Cherche sur Google News RSS et envoie à Kafka (Topic NEWS).
    """
    search_term = TICKER_MAPPING.get(ticker, ticker)
    print(f"🔍 Recherche Google pour : {search_term} (Ticker: {ticker})")
    
    # when:1d = dernières 24h pour éviter le bruit
    encoded_query = urllib.parse.quote(search_term)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}+when:1d&hl=fr&gl=FR&ceid=FR:fr"
    
    try:
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:3]: # Top 3 seulement pour ne pas spammer
            
            # ID unique pour éviter doublons
            news_id = str(hash(entry.link))
            if news_id in seen_ids:
                continue

            # Gestion de la date
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
            
            # Envoi vers le topic standard NEWS
            producer.send(KAFKA_TOPIC_NEWS, value=payload)
            print(f"🌍 [Google RSS] {ticker} : {entry.title[:30]}...")
            seen_ids.add(news_id)

    except Exception as e:
        print(f"⚠️ Erreur RSS {ticker}: {e}")

# --- PARTIE 2 : YAHOO FINANCE & ANALYSE TECHNIQUE (EXISTANT) ---

def send_history_data(producer, stock, ticker):
    """Envoie l'historique Daily (pour les graphiques)"""
    try:
        hist = stock.history(period="1y") 
        if hist.empty: return
        
        last_row = hist.iloc[-1]
        history_payload = {
            "ticker": ticker,
            "date": str(last_row.name),
            "Open": last_row['Open'],
            "High": last_row['High'],
            "Low": last_row['Low'],
            "Close": last_row['Close'],
            "Volume": last_row['Volume']
        }
        producer.send(KAFKA_TOPIC_HISTORY, value=history_payload)

    except Exception as e:
        print(f"❌ Erreur History {ticker}: {e}")

def generate_intraday_metrics(stock, ticker):
    """Calcule les variations 10min, 1h, 6h."""
    try:
        # On demande 2 jours pour avoir assez de recul
        df = stock.history(period="2d", interval="5m")
        if df.empty or len(df) < 10: return None

        current_price = df['Close'].iloc[-1]
        
        # Définition des index pour bougies de 5 minutes
        # 12 * 5min = 60min (1h)
        # 72 * 5min = 360min (6h)
        # 144 * 5min = 720min (12h - souvent indisponible en intraday simple si le marché vient d'ouvrir)
        
        # --- 1. Construction du Résumé Texte ---
        intervals = { "10min": 2, "30min": 6, "1h": 12, "3h": 36, "6h": 72 }
        metrics_text = f"Analyse Momentum {ticker} (Prix: {current_price:.2f}):\n"

        for label, idx in intervals.items():
            if len(df) > idx:
                past_price = df['Close'].iloc[-(idx+1)]
                var_pct = ((current_price - past_price) / past_price) * 100
                emoji = "🟩" if var_pct > 0 else "🟥" if var_pct < 0 else "⬜"
                metrics_text += f"- {label}: {emoji} {var_pct:+.2f}%\n"

        prev_close = stock.fast_info.previous_close
        if prev_close:
            var_1d = ((current_price - prev_close) / prev_close) * 100
            metrics_text += f"- 24h: {'🟩' if var_1d > 0 else '🟥'} {var_1d:+.2f}%\n"

        # --- 2. Construction du Payload JSON (Données Brutes) ---
        payload = {
            "ticker": ticker,
            "title": f"Momentum Intraday {ticker}", 
            "summary": metrics_text, 
            "content": metrics_text, 
            "link": f"https://finance.yahoo.com/quote/{ticker}",
            "publish_time": int(time.time()),
            "type": "intraday_metrics", 
            "source": "system_metrics",
            "current_price": current_price,
            "last_close": prev_close,
            "opening_price": df['Open'].iloc[-1],
            
            # CORRECTION DES INDEX ET DES NOMS
            # 72 intervalles = 6h
            "price_6h_ago": df['Close'].iloc[-(72+1)] if len(df) > 73 else 0,
            # 36 intervalles = 3h
            "price_3h_ago": df['Close'].iloc[-(36+1)] if len(df) > 37 else 0,
            # 12 intervalles = 1h
            "price_1h_ago": df['Close'].iloc[-(12+1)] if len(df) > 13 else 0,
            # 6 intervalles = 30min
            "price_30min_ago": df['Close'].iloc[-(6+1)] if len(df) > 7 else 0,
            # 2 intervalles = 10min
            "price_10min_ago": df['Close'].iloc[-(2+1)] if len(df) > 3 else 0,
            
            "id": f"LATEST_METRICS_{ticker}"
        }
        return payload
            
    except Exception as e:
        print(f"⚠️ Erreur Metrics {ticker}: {e}")
        return None
def analyze_technicals_daily(stock, ticker):
    """Calcule les moyennes mobiles et le RSI basique"""
    try:
        hist = stock.history(period="1y") 
        if hist.empty: return None

        current = hist['Close'].iloc[-1]
        ma_10 = hist['Close'].rolling(window=10).mean().iloc[-1]
        ma_50 = hist['Close'].rolling(window=50).mean().iloc[-1]
        ma_200 = hist['Close'].rolling(window=200).mean().iloc[-1]
        
        trend = "NEUTRE"
        if current > ma_50: trend = "HAUSSIER"
        if current < ma_50: trend = "BAISSIER"

        tech_text = (
            f"Analyse Technique {ticker}. Prix: {current:.2f}. "
            f"Tendance Moyen Terme (MA50): {trend}. "
            f"Moyenne 50j: {ma_50:.2f}. "
            f"Moyenne 200j: {ma_200:.2f}."
            f" Moyenne 10j: {ma_10:.2f}."
        )

        tech_payload = {
            "ticker": ticker,
            "title": f"Rapport Technique {ticker} ({trend})",
            "summary": tech_text,
            "content": tech_text,
            "link": f"https://finance.yahoo.com/quote/{ticker}",
            "publish_time": int(time.time()),
            "type": "technical",
            "current_price": current,
            "mean_10": 0 if pd.isna(ma_10) else ma_10,
            "mean_50": ma_50,
            "mean_200": 0 if pd.isna(ma_200) else ma_200,
            "id": f"LATEST_TECH_{ticker}"
        }
        return tech_payload
    except Exception as e:
        print(f"Erreur Tech Daily {ticker}: {e}")
        return None

def fetch_and_send_data(producer, seen_news):
    print("🔄 [Producer] Scan Temps Réel (Prix + News Yahoo + Google RSS)...")
    
    for ticker in TICKERS:
        
        # 1. Récupération Google RSS (Streaming News)
        fetch_google_rss(producer, ticker, seen_news)
        
        # 2. Récupération Yahoo (Market Data & Official News)
        try:
            stock = yf.Ticker(ticker)
            
            # Historique Graphique
            send_history_data(producer, stock, ticker)

            # Bulletin Intraday
            metrics = generate_intraday_metrics(stock, ticker)
            if metrics:
                producer.send(KAFKA_TOPIC_HOT_NEWS, value=metrics)

            # Analyse Technique
            tech_data = analyze_technicals_daily(stock, ticker)
            if tech_data:
                producer.send(KAFKA_TOPIC_NEWS, value=tech_data)

            # News Yahoo (Classique)
            news = stock.news
            for item in news:
                content = item.get('content', item)
                news_id = item.get('uuid', item.get('id'))
                title = content.get('title')
                link_obj = content.get('clickThroughUrl')
                link = link_obj.get('url') if isinstance(link_obj, dict) else link_obj

                if not title or not news_id: continue

                if news_id not in seen_news:
                    news_payload = {
                        "ticker": ticker,
                        "title": title,
                        "publisher": content.get('provider', {}).get('displayName', 'Yahoo'),
                        "link": link,
                        "summary": content.get('summary'),
                        "publish_time": int(time.mktime(time.strptime(content.get('pubDate'), "%Y-%m-%dT%H:%M:%SZ"))),
                        "type": "news",
                        "source": "yahoo_api", # Tag source
                        "id": news_id
                    }
                    producer.send(KAFKA_TOPIC_NEWS, value=news_payload)
                    print(f"📰 [Yahoo] {ticker} : {title[:20]}...")
                    seen_news.add(news_id)

        except Exception as e:
            print(f"⚠️ Erreur Globale {ticker}: {e}")

    producer.flush()

if __name__ == "__main__":
    producer = create_producer()
    seen = set() # Set partagé entre Yahoo et Google pour les IDs
    if producer:
        while True:
            fetch_and_send_data(producer, seen)
            print(f"💤 Pause {SLEEP_TIME}s...")
            time.sleep(SLEEP_TIME)