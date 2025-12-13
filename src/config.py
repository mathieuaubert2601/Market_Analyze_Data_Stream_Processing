import os

# --- KAFKA INFRASTRUCTURE ---
KAFKA_HOST = os.getenv("KAFKA_BROKER", "localhost:9092")
KAFKA_BOOTSTRAP_SERVERS = [KAFKA_HOST]

# Topics
KAFKA_TOPIC_NEWS = "financial-news"       # News + tech analysis
KAFKA_TOPIC_HISTORY = "stock-history"     # OHLCV for charts
KAFKA_TOPIC_HOT_NEWS = "hot-news-events"  # Important events / intraday

# --- ACTIONS (Euronext + US) ---
TICKERS = [
    "STLAP.PA", "STMPA.PA", "ORA.PA", "ENGI.PA",
    "ALHPI.PA", "CS.PA", "DCAM.PA", "ETZ.PA",
]

# --- PARAMETERS ---
SLEEP_TIME = 60
CHROMA_PATH = "./data/chromadb"
HISTORY_PATH = "./data/history"  # Folder for CSV files
COLLECTION_NAME = "financial_news"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
LLM_MODEL_NAME = "llama-3.3-70b-versatile"

# Horizons/TTL centralises
HORIZON_RECENT = 2 * 60 * 60          # 2 hours for RECENT questions
HORIZON_HISTORICAL = 30 * 24 * 3600   # 30 days for historical questions
TTL_NEWS = 3 * 24 * 3600              # Ignore news > 3 days
TTL_INTRADAY = 24 * 3600              # Ignore intraday metrics > 24h

ALERT_THRESHOLDS = {
    "10min": 0.5,
    "30min": 1.0,
    "1h": 1.5,
    "3h": 2.0,
    "6h": 3.0,
    "1d": 4.0,
}
