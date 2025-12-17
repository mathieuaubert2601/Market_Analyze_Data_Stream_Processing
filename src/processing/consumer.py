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
    KAFKA_TOPIC_DAILY_SUMMARY,
    CHROMA_PATH,
    HISTORY_PATH,
    COLLECTION_NAME,
    EMBEDDING_MODEL_NAME,
)

RETENTION_DAYS = 30
RETENTION_SECONDS = RETENTION_DAYS * 24 * 3600

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
        heartbeat_file = os.path.join(HISTORY_PATH, "consumer_heartbeat.txt")
        with open(heartbeat_file, "w") as f:
            f.write(str(time.time()))
    except Exception:
        pass


def clean_metadata(data: dict, sentiment_score: float) -> dict:
    """Clean and validate metadata for ChromaDB storage."""
    meta = {}

    meta["ticker"] = str(data.get("ticker", "UNKNOWN"))
    meta["type"] = str(data.get("type", "news"))
    meta["source"] = str(data.get("source", "unknown"))
    meta["doc"] = str(data.get("title", ""))[:150]
    meta["link"] = str(data.get("link", "#"))
    meta["market_state"] = str(data.get("market_state", "REGULAR"))
    meta["currency"] = str(data.get("currency", "UKN"))

    float_keys = [
        "publish_time", "current_price", "mean_200", "mean_50", "mean_10",
        "price_12h_ago", "price_6h_ago", "price_3h_ago", "price_1h_ago",
        "price_30min_ago", "price_10min_ago", "last_close", "opening_price",
        "regularMarketTime", "timestamp"
    ]

    for key in float_keys:
        val = data.get(key)
        try:
            if val is None or val == "":
                meta[key] = 0.0
            else:
                meta[key] = float(val)
        except (ValueError, TypeError):
            meta[key] = 0.0

    if meta["timestamp"] == 0.0 and meta["publish_time"] > 0:
        meta["timestamp"] = meta["publish_time"]

    meta["sentiment"] = float(sentiment_score)

    return meta


def process_history(data: dict) -> None:
    """Store OHLCV history in CSV files for charts."""
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
            df = df[~df.index.duplicated(keep="last")]
            df.sort_index(inplace=True)
        else:
            df = new_row
            print(f"📄 Created new history file for {ticker}")

        df.to_csv(csv_file)

    except Exception as e:
        print(f"[Consumer] Error CSV {ticker}: {e}")


def enforce_retention_policy(ticker: str) -> None:
    """Delete daily_summary older than 30 days from ChromaDB."""
    try:
        cutoff_time = time.time() - RETENTION_SECONDS

        collection.delete(
            where={
                "$and": [
                    {"type": {"$eq": "daily_summary"}},
                    {"ticker": {"$eq": ticker}},
                    {"timestamp": {"$lt": cutoff_time}}
                ]
            }
        )
    except Exception as e:
        print(f"⚠️ [Retention] Cleanup error for {ticker}: {e}")


def process_news(data: dict) -> None:
    """Process news, metrics, technicals and daily summaries for RAG."""
    try:
        title = data.get('title', "")
        if not title:
            return

        ticker = data.get('ticker', 'UNKNOWN')
        doc_type = data.get('type', 'news')

        if doc_type == 'technical':
            unique_id = f"LATEST_TECH_{ticker}"
        elif doc_type == 'intraday_metrics':
            unique_id = f"LATEST_METRICS_{ticker}"
        elif doc_type == 'daily_summary':
            ts = int(data.get('publish_time', time.time()))
            unique_id = f"DAILY_SUMMARY_{ticker}_{ts}"
        else:
            raw_id = data.get('id')
            if not raw_id:
                raw_id = str(hash(title))
            unique_id = f"NEWS_{ticker}_{raw_id}"

        text_for_sentiment = data.get('summary', title)
        if data.get('content'):
            text_for_sentiment = f"{title}. {data.get('content')}"

        sentiment_scores = analyzer.polarity_scores(text_for_sentiment)
        sentiment = sentiment_scores['compound']

        text_embed = f"{ticker}: {title}"
        vector = embedding_model.encode(text_embed).tolist()

        metadata_clean = clean_metadata(data, sentiment)

        collection.upsert(
            ids=[unique_id],
            embeddings=[vector],
            documents=[data.get('content', title)],
            metadatas=[metadata_clean]
        )

        log_msg = f"✅ [RAG] Processed: {ticker} ({doc_type})"

        if doc_type == 'daily_summary':
            enforce_retention_policy(ticker)
            log_msg += " + Cleanup > 30 days done"

        print(log_msg)

    except Exception as e:
        print(f"❌ RAG Error ({ticker}): {e}")


if __name__ == "__main__":

    consumer = KafkaConsumer(
        KAFKA_TOPIC_NEWS,
        KAFKA_TOPIC_HISTORY,
        KAFKA_TOPIC_HOT_NEWS,
        KAFKA_TOPIC_DAILY_SUMMARY,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        auto_offset_reset="earliest",
        group_id="consumer-rag-group-v5",
        enable_auto_commit=True,
        value_deserializer=lambda x: (json.loads(x.decode('utf-8'))
                                      if x else None)
    )

    print(f"[Consumer] Connected to Kafka. Listening "
          f"(Retention: {RETENTION_DAYS} days)...")

    for message in consumer:
        update_heartbeat()

        try:
            data = message.value
            if data is None:
                continue

            topic = message.topic

            if topic == KAFKA_TOPIC_HISTORY:
                process_history(data)
            elif topic in [KAFKA_TOPIC_NEWS, KAFKA_TOPIC_HOT_NEWS,
                           KAFKA_TOPIC_DAILY_SUMMARY]:
                process_news(data)

        except json.JSONDecodeError:
            print(f"⚠️ [Consumer] JSON Error on topic {message.topic}")
        except Exception as e:
            print(f"❌ [Consumer] Critical Loop Error: {e}")
