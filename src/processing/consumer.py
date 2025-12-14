import json
import sys
import os
import time
import pandas as pd
import chromadb
from kafka import KafkaConsumer
from sentence_transformers import SentenceTransformer
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from src.config import (
    KAFKA_BOOTSTRAP_SERVERS,
    KAFKA_TOPIC_NEWS,
    KAFKA_TOPIC_HISTORY,
    KAFKA_TOPIC_HOT_NEWS,
    CHROMA_PATH,
    HISTORY_PATH,
    COLLECTION_NAME,
    EMBEDDING_MODEL_NAME,
    TTL_NEWS,
    TTL_INTRADAY,
)

# --- SETUP ---
print("[Consumer] Loading AI Models (Embeddings + Sentiment)...")
embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
analyzer = SentimentIntensityAnalyzer()

print(f"[Consumer] Connecting to ChromaDB at {CHROMA_PATH}...")
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name=COLLECTION_NAME)

os.makedirs(HISTORY_PATH, exist_ok=True)


def update_heartbeat() -> None:
    """Touch a file to indicate the consumer is alive."""
    try:
        with open(os.path.join(HISTORY_PATH, "consumer_heartbeat.txt"), "w") as f:
            f.write(str(time.time()))
    except Exception:
        pass


def clean_metadata(data: dict, sentiment_score: float) -> dict:
    """
    Strict cleaning of metadata for ChromaDB.
    Chroma crashes if metadata contains None or wrong types.
    """
    meta = {}
    
    # 1. Strings (Ensure no None)
    meta["ticker"] = str(data.get("ticker", "UNKNOWN"))
    meta["type"] = str(data.get("type", "news"))
    meta["source"] = str(data.get("source", "unknown"))
    meta["doc"] = str(data.get("title", ""))[:50]
    meta["link"] = str(data.get("link", "#"))
    
    # 2. Floats (Ensure no None or Strings)
    # List of all numeric fields expected by RAG Engine
    float_keys = [
        "publish_time", "current_price", "mean_200", "mean_50", "mean_10",
        "price_12h_ago", "price_6h_ago", "price_3h_ago", "price_1h_ago",
        "price_30min_ago", "price_10min_ago", "last_close", "opening_price"
    ]
    
    for key in float_keys:
        val = data.get(key)
        try:
            # Convert to float, default to 0.0 if None or error
            meta[key] = float(val) if val is not None else 0.0
        except:
            meta[key] = 0.0

    # Add calculated fields
    meta["timestamp"] = meta["publish_time"] # for RAG Time Decay
    meta["sentiment"] = float(sentiment_score)
    
    return meta


def process_history(data: dict) -> None:
    """Stores OHLCV history in CSV for charts."""
    ticker = data.get("ticker")
    date = data.get("date")
    
    if not ticker or not date:
        return

    csv_file = os.path.join(HISTORY_PATH, f"{ticker}.csv")
    
    try:
        new_row = pd.DataFrame([data]).set_index("date")
        
        if os.path.exists(csv_file):
            df = pd.read_csv(csv_file, index_col="date")
            df = pd.concat([df, new_row])
            # Remove duplicates keeping the last (fresher) one
            df = df[~df.index.duplicated(keep="last")]
            df.sort_index(inplace=True)
        else:
            # ✅ À la première ligne : charger 6 mois d'historique yfinance
            import yfinance as yf
            from datetime import datetime, timedelta
            
            try:
                end_date = datetime.now()
                start_date = end_date - timedelta(days=180)
                hist_data = yf.download(ticker, start=start_date, end=end_date, progress=False)
                
                if not hist_data.empty:
                    hist_data.index.name = 'date'
                    df = hist_data
                    print(f"✅ Loaded {len(df)} days of history for {ticker}")
                else:
                    df = new_row
            except:
                df = new_row
            
        df.to_csv(csv_file)
        
    except Exception as e:
        print(f"[Consumer] Error CSV {ticker}: {e}")

def process_news(data):
    try:
        title = data.get('title', "")
        if not title: return

        ticker = data.get('ticker', 'UNKNOWN')
        doc_type = data.get('type', 'news')
        
        # --- LOGIQUE ANTI-DOUBLON ---
        if doc_type == 'technical':
            unique_id = f"LATEST_TECH_{ticker}"
        elif doc_type == 'intraday_metrics':
            unique_id = f"LATEST_METRICS_{ticker}"
        else: 
            raw_id = data.get('id')
            if not raw_id:
                raw_id = str(hash(title))
            unique_id = f"NEWS_{ticker}_{raw_id}"

        # ✅ AMÉLIORATION: Utiliser title + summary + content pour le sentiment
        text_for_sentiment = data.get('summary', title)
        if data.get('content'):
            text_for_sentiment = f"{title}. {data.get('content')}"
            
        sentiment_scores = analyzer.polarity_scores(text_for_sentiment)
        sentiment = sentiment_scores['compound']
        
        # ✅ DEBUG: Afficher les scores VADER
        print(f"DEBUG [{ticker}] Sentiment: {sentiment:.3f} | Scores: {sentiment_scores}")
        
        # Embedding sur le titre + ticker
        text_embed = f"{ticker}: {title}"
        vector = embedding_model.encode(text_embed).tolist()
        
        # Upsert
        collection.upsert(
            ids=[unique_id],
            embeddings=[vector],
            documents=[data.get('content', title)],
            metadatas=[{
                "ticker": ticker,
                "timestamp": data.get('publish_time', 0),
                "current_price": float(data['current_price']) if data.get('current_price') else 0.0,
                "mean_200": float(data['mean_200']) if data.get('mean_200') else 0.0,
                "mean_50": float(data['mean_50']) if data.get('mean_50') else 0.0,
                "mean_10":  float(data['mean_10']) if data.get('mean_10') else 0.0,
                "price_12h_ago": float(data['price_12h_ago']) if data.get('price_12h_ago') else 0.0,
                "price_6h_ago": float(data['price_6h_ago']) if data.get('price_6h_ago') else 0.0,
                "price_3h_ago": float(data['price_3h_ago']) if data.get('price_3h_ago') else 0.0,
                "price_1h_ago": float(data['price_1h_ago']) if data.get('price_1h_ago') else 0.0,
                "price_30min_ago": float(data['price_30min_ago']) if data.get('price_30min_ago') else 0.0,
                "price_10min_ago": float(data['price_10min_ago']) if data.get('price_10min_ago') else 0.0,
                "last_close": float(data['last_close']) if data.get('last_close') else 0.0,
                "opening_price": float(data['opening_price']) if data.get('opening_price') else 0.0,
                "content": data.get('summary', title),
                "sentiment": sentiment,
                "doc":  title,
                "link": data.get('link', '#')
            }]
        )
        print(f"✅ [RAG] Traité : {ticker} ({doc_type}) - Sentiment: {sentiment:.2f}")

    except Exception as e:
        print(f"❌ Erreur RAG ({ticker}): {e}")

if __name__ == "__main__":
    
    # Initialize Consumer without strict deserializer to prevent crashes on bad bytes
    consumer = KafkaConsumer(
        KAFKA_TOPIC_NEWS,
        KAFKA_TOPIC_HISTORY,
        KAFKA_TOPIC_HOT_NEWS,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        auto_offset_reset="earliest",
        group_id="consumer-final-group-v3",
        enable_auto_commit=True
    )

    print("[Consumer] Connected to Kafka. Listening...")

    for message in consumer:
        update_heartbeat()
        
        try:
            if message.value is None: continue
            data = json.loads(message.value.decode("utf-8"))
            
            topic = message.topic
            
            if topic == KAFKA_TOPIC_HISTORY:
                process_history(data)
            elif topic == KAFKA_TOPIC_NEWS:
                process_news(data)
            elif topic == KAFKA_TOPIC_HOT_NEWS:
                process_news(data) # Hot news goes to RAG too
                
        except json.JSONDecodeError:
            print(f"⚠️ [Consumer] JSON Error on topic {message.topic}")
        except Exception as e:
            print(f"❌ [Consumer] Critical Loop Error: {e}")
