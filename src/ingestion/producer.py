import time
import json
import yfinance as yf
from kafka import KafkaProducer
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from src.config import KAFKA_BOOTSTRAP_SERVERS, KAFKA_TOPIC_NEWS, TICKERS, SLEEP_TIME

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

def analyze_technicals_and_alerts(stock, ticker):
    """Calcule les indicateurs techniques et génère des alertes de prix"""
    try:
        # On demande l'historique
        hist = stock.history(period="1y")
        
        if hist.empty: return None, None

        # 1. Gestion de la Devise
        currency = stock.fast_info.get('currency', 'USD')

        # 2. Calculs
        current_price = hist['Close'].iloc[-1]
        open_price = hist['Open'].iloc[-1]
        variation_pct = ((current_price - open_price) / open_price) * 100
        
        ma_200 = hist['Close'].rolling(window=200).mean().iloc[-1]
        trend_long = "HAUSSIERE" if current_price > ma_200 else "BAISSIERE"
        
        # 3. Texte Propre
        tech_text = (
            f"Rapport Technique pour {ticker} . "
            f"Prix actuel : {current_price:.2f} {currency} . "
            f"Variation du jour : {variation_pct:.2f} pourcent . "
            f"Tendance Long Terme (Moyenne 200j) : {trend_long} . "
            f"Moyenne Mobile 200j : {ma_200:.2f} {currency} ."
        )

        # 4. Payload Technique
        tech_data = {
            "ticker": ticker,
            "title": f"Tech Report : {ticker}",
            "content": tech_text,
            "publisher": "Tech Bot",
            "link": f"https://finance.yahoo.com/quote/{ticker}",
            "publish_time": int(time.time()),
            "type": "technical"
        }

        # 5. Payload Alerte (Si variation > 2%)
        alert_data = None
        if abs(variation_pct) >= 2.0:
            direction = "HAUSSE" if variation_pct > 0 else "BAISSE"
            alert_msg = f"ALERTE {ticker} : {direction} de {variation_pct:.2f} pourcent (Prix : {current_price:.2f} {currency})"
            alert_data = {
                "ticker": ticker,
                "title": f"🚨 {alert_msg}",
                "content": alert_msg,
                "publisher": "Market Guard",
                "link": f"https://finance.yahoo.com/quote/{ticker}",
                "publish_time": int(time.time()),
                "type": "alert"
            }

        return tech_data, alert_data

    except Exception as e:
        # print(f"⚠️ Info : Pas de tech pour {ticker} (Marché peut-être fermé ou données manquantes)")
        return None, None

def fetch_and_send_data(producer, seen_news):
    print("🔄 [Producer] Cycle de récupération...")
    
    for ticker in TICKERS:
        try:
            # On crée l'objet Ticker une seule fois par tour
            stock = yf.Ticker(ticker)
            
            # --- PARTIE 1 : TECHNIQUE & ALERTES ---
            tech_data, alert_data = analyze_technicals_and_alerts(stock, ticker)
            
            if tech_data:
                # ID unique basé sur l'heure (change toutes les minutes)
                tech_id = f"tech_{ticker}_{int(time.time() / 60)}" 
                if tech_id not in seen_news:
                    payload = tech_data.copy()
                    payload["title"] = tech_data['content'] 
                    producer.send(KAFKA_TOPIC_NEWS, value=payload)
                    seen_news.add(tech_id)
                    print(f"📈 [Tech] {ticker} envoyé")

            if alert_data:
                alert_id = f"alert_{ticker}_{int(time.time() / 3600)}"
                if alert_id not in seen_news:
                    payload = alert_data.copy()
                    payload["title"] = alert_data['content']
                    producer.send(KAFKA_TOPIC_NEWS, value=payload)
                    seen_news.add(alert_id)
                    print(f"🚨 [ALERTE] {ticker} envoyé")

            # --- PARTIE 2 : ACTUALITÉS (NEWS) ---
            # C'est ici que ça manquait !
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
            print(f"⚠️ Erreur globale sur {ticker}: {e}")

    producer.flush()

if __name__ == "__main__":
    producer = create_producer()
    seen = set()
    
    if producer:
        while True:
            fetch_and_send_data(producer, seen)
            print(f"💤 Pause de {SLEEP_TIME} secondes...")
            time.sleep(SLEEP_TIME)