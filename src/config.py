import os

# --- KAFKA CONFIGURATION ---
# Si on est dans Docker, on prend la variable d'env, sinon localhost
KAFKA_HOST = os.getenv('KAFKA_BROKER', 'localhost:9092')
KAFKA_BOOTSTRAP_SERVERS = [KAFKA_HOST]
KAFKA_TOPIC_NEWS = 'financial-news'

# --- DATA SOURCE (YAHOO) ---
# Les entreprises que le Producer va surveiller
TICKERS = [
    "STLAP.PA","STMPA.PA","ORA.PA","ENGI.PA","ALHPI.PA","CS.PA","DCAM.PA","ETZ.PA"
]

# Temps d'attente entre deux scans (en secondes)
# 60s est recommandé pour ne pas se faire bloquer par Yahoo
SLEEP_TIME = 60

# --- DATABASE VECTORIELLE (CHROMADB) ---
# Chemin où les données sont stockées sur le disque dur
CHROMA_PATH = "./data/chromadb"
COLLECTION_NAME = "financial_news"

# --- INTELLIGENCE ARTIFICIELLE ---

# 1. Modèle d'Embedding (LOCAL - Petit)
# Sert à transformer le texte en vecteurs pour la recherche dans ChromaDB
EMBEDDING_MODEL_NAME = 'all-MiniLM-L6-v2'

# 2. Modèle de Génération (CLOUD - Gros - via Groq)
# Sert à rédiger la réponse finale
# Utilisation de Llama 3.3 (Dernier modèle stable gratuit sur Groq)
LLM_MODEL_NAME = "llama-3.3-70b-versatile"