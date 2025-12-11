import os

# --- INFRASTRUCTURE KAFKA ---
KAFKA_HOST = os.getenv('KAFKA_BROKER', 'localhost:9092')
KAFKA_BOOTSTRAP_SERVERS = [KAFKA_HOST]

# Topics
KAFKA_TOPIC_NEWS = 'financial-news'       # Pour le texte (News + Analyse Tech)
KAFKA_TOPIC_HISTORY = 'stock-history'     # NOUVEAU : Pour les graphiques (OHLCV)

# --- ACTIONS (Euronext + US) ---
TICKERS = [
    "STLAP.PA","STMPA.PA","ORA.PA","ENGI.PA","ALHPI.PA","CS.PA","DCAM.PA","ETZ.PA"
]

# --- PARAMÈTRES ---
SLEEP_TIME = 60
CHROMA_PATH = "./data/chromadb"
HISTORY_PATH = "./data/history" # Dossier pour les CSV
COLLECTION_NAME = "financial_news"
EMBEDDING_MODEL_NAME = 'all-MiniLM-L6-v2'
LLM_MODEL_NAME = "llama-3.3-70b-versatile"