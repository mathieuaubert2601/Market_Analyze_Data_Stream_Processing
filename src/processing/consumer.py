import json
import sys
import os
import pandas as pd
import chromadb
from kafka import KafkaConsumer
from sentence_transformers import SentenceTransformer
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from src.config import KAFKA_BOOTSTRAP_SERVERS, KAFKA_TOPIC_NEWS, KAFKA_TOPIC_HISTORY, CHROMA_PATH, HISTORY_PATH, COLLECTION_NAME, EMBEDDING_MODEL_NAME

print("⏳ [Consumer] Chargement Modèles...")
embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
analyzer = SentimentIntensityAnalyzer()

print("📂 [Consumer] Init Stockage...")
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name=COLLECTION_NAME)
os.makedirs(HISTORY_PATH, exist_ok=True)

# --- TRAITEMENT HISTORIQUE ---
def process_history(data):
    ticker = data.get('ticker')
    date = data.get('date')
    if not ticker or not date: return

    csv_file = os.path.join(HISTORY_PATH, f"{ticker}.csv")
    new_row = pd.DataFrame([data]).set_index('date')
    
    try:
        if os.path.exists(csv_file):
            df = pd.read_csv(csv_file, index_col='date')
            df = pd.concat([df, new_row])
            df = df[~df.index.duplicated(keep='last')]
            df.sort_index(inplace=True)
        else:
            df = new_row
        df.to_csv(csv_file)
    except Exception as e:
        print(f"❌ Erreur CSV {ticker}: {e}")

# --- TRAITEMENT NEWS/TECH (RAG) ---
def process_news(data):
    try:
        title = data.get('title', "")
        if not title: return

        ticker = data.get('ticker', 'UNKNOWN')
        doc_type = data.get('type', 'news')
        
        # --- LOGIQUE ANTI-DOUBLON (ID UNIQUE) ---
        if doc_type == 'technical':
            # Pour la tech, on écrase toujours avec la dernière version
            unique_id = f"LATEST_TECH_{ticker}"
        else:
            # Pour les news, on utilise l'ID Yahoo s'il existe, sinon un hash du titre
            # Cela empêche d'avoir 2 fois la même news
            raw_id = data.get('id')
            if not raw_id:
                raw_id = str(hash(title))
            unique_id = f"NEWS_{ticker}_{raw_id}"
        # ----------------------------------------

        sentiment = analyzer.polarity_scores(title)['compound']
        text_embed = f"{ticker}: {title}"
        vector = embedding_model.encode(text_embed).tolist()
        
        # Upsert (Insérer ou Mettre à Jour)
        collection.upsert(
            ids=[unique_id],
            embeddings=[vector],
            documents=[title],
            metadatas=[{
                "ticker": ticker,
                "timestamp": data.get('publish_time', 0),
                "type": doc_type,
                "sentiment": sentiment,
                "doc": title,
                "link": data.get('link', '#') # On stocke bien le lien ici
            }]
        )
        print(f"✅ [RAG] Traité : {ticker} ({doc_type}) -> ID: {unique_id}")

    except Exception as e:
        print(f"❌ Erreur RAG : {e}")

if __name__ == "__main__":
    consumer = KafkaConsumer(
        KAFKA_TOPIC_NEWS, KAFKA_TOPIC_HISTORY,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_deserializer=lambda x: json.loads(x.decode('utf-8')),
        auto_offset_reset='earliest',
        group_id='consumer-final-fix-v1' # Changement de groupe pour relecture propre
    )
    
    print("🎧 [Consumer] En attente...")
    
    for message in consumer:
        if message.topic == KAFKA_TOPIC_HISTORY:
            process_history(message.value)
        elif message.topic == KAFKA_TOPIC_NEWS:
            process_news(message.value)