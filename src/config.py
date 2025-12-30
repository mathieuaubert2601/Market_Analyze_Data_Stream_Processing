import os

# --- KAFKA INFRASTRUCTURE ---
KAFKA_HOST = os.getenv("KAFKA_BROKER", "localhost:9092")
KAFKA_BOOTSTRAP_SERVERS = [KAFKA_HOST]

# Topics
KAFKA_TOPIC_NEWS = "financial-news"       
KAFKA_TOPIC_HISTORY = "stock-history"     
KAFKA_TOPIC_HOT_NEWS = "hot-news-events"  
KAFKA_TOPIC_DAILY_SUMMARY = "daily-summary"  

# --- ACTIONS ---
TICKERS = [
    "MC.PA","TTE.PA","OR.PA","RMS.PA","SAN.PA","SAF.PA","SU.PA","AI.PA","BNP.PA","DG.PA"
]

# --- PARAMETERS ---
SLEEP_TIME = 60
CHROMA_PATH = "./data/chromadb"
HISTORY_PATH = "./data/history" 
COLLECTION_NAME = "financial_news"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
LLM_MODEL_NAME = "llama-3.3-70b-versatile"
          