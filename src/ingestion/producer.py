import time
import json
import yfinance as yf
from kafka import KafkaProducer
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from src.config import KAFKA_BOOTSTRAP_SERVERS, KAFKA_TOPIC_NEWS, TICKERS, SLEEP_TIME,KAFKA_TOPIC_HISTORY

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
def send_history_data(producer, stock, ticker):
    """Récupère l'historique et l'envoie ligne par ligne à Kafka"""
    try:
        # On récupère 1 an d'historique (ou '6mo' pour être plus léger)
        hist = stock.history(period="1y") 
        
        # On envoie chaque ligne (chaque jour)
        # Note : Dans un vrai système prod, on n'enverrait que la dernière bougie 
        # une fois l'init faite, pour ne pas spammer Kafka à chaque boucle.
        # Ici, pour la démo, on envoie tout le paquet.
        
        count = 0
        for date, row in hist.iterrows():
            history_payload = {
                "ticker": ticker,
                "date": str(date), # Important pour le CSV
                "Open": row['Open'],
                "High": row['High'],
                "Low": row['Low'],
                "Close": row['Close'],
                "Volume": row['Volume']
            }
            # Envoi vers le topic dédié aux graphiques
            producer.send(KAFKA_TOPIC_HISTORY, value=history_payload)
            count += 1
            
        print(f"📊 [History] {ticker} : {count} bougies envoyées.")

    except Exception as e:
        print(f"❌ Erreur History {ticker}: {e}")

def analyze_technicals_and_alerts(stock, ticker):
    try:
        hist = stock.history(period="1y")
        if hist.empty: return None, None

        currency = stock.fast_info.get('currency', 'USD')
        current = hist['Close'].iloc[-1]
        open_p = hist['Open'].iloc[-1]
        var_pct = ((current - open_p) / open_p) * 100
        
        ma_200 = hist['Close'].rolling(window=200).mean().iloc[-1]
        ma_50 = hist['Close'].rolling(window=50).mean().iloc[-1]
        ma_10 = hist['Close'].rolling(window=10).mean().iloc[-1]
        trend_200 = "HAUSSIERE" if current > ma_200 else "BAISSIERE"
        trend_50 = "HAUSSIERE" if ma_50 > ma_200 else "BAISSIERE"
        trend_10 = "HAUSSIERE" if ma_10 > ma_50 else "BAISSIERE"
        
        tech_text = (
            f"Rapport Technique {ticker} . Prix : {current:.2f} {currency} . "
            f"Variation : {var_pct:.2f} % . Tendance Long Terme : {trend_200} ."
            f" Tendance Moyen Terme : {trend_50} . Tendance Court Terme : {trend_10} ."
        )

        tech_data = {
            "ticker": ticker,
            "title": f"Tech Report : {ticker}",
            "content": tech_text,
            "publisher": "Tech Bot",
            "link": f"https://finance.yahoo.com/quote/{ticker}",
            "publish_time": int(time.time()),
            "type": "technical",
            "id": f"TECH_{ticker}"
        }
        return tech_data
    except: return None

def fetch_and_send_data(producer, seen_news):
    print("🔄 [Producer] Scan Temps Réel...")
    
    for ticker in TICKERS:
        try:
            stock = yf.Ticker(ticker)
            
            # 1. Historique
            send_history_data(producer, stock, ticker)

            # 2. Tech & Alertes
            tech = analyze_technicals_and_alerts(stock, ticker)
            
            if tech:
                # Pas besoin de vérifier seen_news pour la tech, on veut toujours la dernière
                payload = tech.copy()
                payload["title"] = tech['content']
                producer.send(KAFKA_TOPIC_NEWS, value=payload)
                print(f"📈 [Tech] {ticker} envoyé")
    

            # 2. News Yahoo
            news = stock.news
            for item in news:
                # Gestion de la structure imbriquée de Yahoo
                content = item.get('content', item)
                news_id = item.get('uuid', item.get('id'))
                title = content.get('title')
                
                # Gestion du lien (parfois un objet, parfois une string)
                link_obj = content.get('clickThroughUrl')
                if isinstance(link_obj, dict):
                    link = link_obj.get('url')
                else:
                    link = link_obj

                if not title or not news_id:
                    continue

                if news_id not in seen_news:
                    news_payload = {
                        "ticker": ticker, # TRES IMPORTANT POUR EVITER LE UNKNOWN
                        "title": title,
                        "publisher": content.get('provider', {}).get('displayName', 'Yahoo'),
                        "link": link,
                        "publish_time": int(content.get('providerPublishTime', time.time())),
                        "type": "news"
                    }
                    
                    producer.send(KAFKA_TOPIC_NEWS, value=news_payload)
                    print(f"📰 [News] {ticker} : {title[:30]}...")
                    seen_news.add(news_id)

        except Exception as e:
            print(f"⚠️ Erreur {ticker}: {e}")

    producer.flush()

if __name__ == "__main__":
    producer = create_producer()
    seen = set()
    if producer:
        while True:
            fetch_and_send_data(producer, seen)
            time.sleep(SLEEP_TIME)