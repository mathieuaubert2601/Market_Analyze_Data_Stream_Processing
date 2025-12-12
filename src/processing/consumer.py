import json
import sys
import os
import pandas as pd
import chromadb
from kafka import KafkaConsumer
from sentence_transformers import SentenceTransformer
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from src.config import KAFKA_BOOTSTRAP_SERVERS, KAFKA_TOPIC_NEWS, KAFKA_TOPIC_HISTORY, CHROMA_PATH, HISTORY_PATH, COLLECTION_NAME, EMBEDDING_MODEL_NAME, KAFKA_TOPIC_HOT_NEWS

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
# --- TRAITEMENT NEWS/TECH (RAG) ---
def process_news(data):
    try:
        title = data.get('title', "")
        if not title: return

        ticker = data.get('ticker', 'UNKNOWN')
        doc_type = data.get('type', 'news')
        
        # --- LOGIQUE ANTI-DOUBLON (ID UNIQUE) ---
        if doc_type == 'technical':
            # Pour la tech (MM50, Trend), on écrase toujours
            unique_id = f"LATEST_TECH_{ticker}"
            
        elif doc_type == 'intraday_metrics':
            # <--- AJOUT CRUCIAL : Pour le momentum (10m, 1h), on écrase toujours
            # Cela doit correspondre exactement à ce que cherche rag_engine.py
            unique_id = f"LATEST_METRICS_{ticker}"
            
        else:
            # Pour les news, on garde l'historique
            raw_id = data.get('id')
            if not raw_id:
                raw_id = str(hash(title))
            # On préfixe pour éviter les collisions
            unique_id = f"NEWS_{ticker}_{raw_id}"
        # ----------------------------------------

        # Calcul du sentiment (si pas déjà fourni)
        if 'summary' in data:
            text_for_sentiment = data['summary']
        else:
            text_for_sentiment = title
            
        sentiment = analyzer.polarity_scores(text_for_sentiment)['compound']
        
        # Embedding sur le titre + ticker
        text_embed = f"{ticker}: {title}"
        vector = embedding_model.encode(text_embed).tolist()
        
        # Upsert
        collection.upsert(
            ids=[unique_id],
            embeddings=[vector],
            documents=[data.get('content', title)], # On essaie de sauver le contenu complet si dispo
            metadatas=[{
                "ticker": ticker,
                "timestamp": data.get('publish_time', 0),
                "current_price": float(data['current_price']) if data.get('current_price') else 0.0,
                "mean_200": float(data['mean_200']) if data.get('mean_200') else 0.0,
                "mean_50": float(data['mean_50']) if data.get('mean_50') else 0.0,
                "mean_10": float(data['mean_10']) if data.get('mean_10') else 0.0,
                "type": doc_type,
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
                "doc": title,
                "link": data.get('link', '#')
            }]
        )
        print(f"✅ [RAG] Traité : {ticker} ({doc_type}) -> ID: {unique_id}")

    except Exception as e:
        print(f"❌ Erreur RAG ({ticker}): {e}")

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

        sentiment = analyzer.polarity_scores(data.get('summary', title))['compound']
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
                "current_price": data.get('current_price', None),
                "mean_200": data.get('mean_200', None),
                "mean_50": data.get('mean_50', None),
                "mean_10": data.get('mean_10', None),
                "last_close": data.get('last_close', None),
                "opening_price": data.get('opening_price', None),
                "price_12h_ago": data.get('price_12h_ago', None),
                "price_6h_ago": data.get('price_6h_ago', None),
                "price_3h_ago": data.get('price_3h_ago', None),
                "price_1h_ago": data.get('price_1h_ago', None),
                "price_30min_ago": data.get('price_30min_ago', None),
                "price_10min_ago": data.get('price_10min_ago', None),
                "content": data.get('summary', title),
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
        KAFKA_TOPIC_NEWS, 
        KAFKA_TOPIC_HISTORY, 
        KAFKA_TOPIC_HOT_NEWS, # <--- AJOUT ICI
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_deserializer=lambda x: json.loads(x.decode('utf-8')),
        auto_offset_reset='earliest',
        group_id='consumer-final-v2' # Change v1 -> v2 pour reset les offsets
    )
    
    print("🎧 [Consumer] En attente (News, History, Hot-News)...")
    
    for message in consumer:
        if message.topic == KAFKA_TOPIC_HISTORY:
            process_history(message.value)
            
        elif message.topic == KAFKA_TOPIC_NEWS:
            process_news(message.value)
            
        elif message.topic == KAFKA_TOPIC_HOT_NEWS: # <--- AJOUT ICI
            print("🔥 Hot News reçue (Archivage...)")
            # On réutilise process_news car on a formaté le payload RSS pour être compatible !
            process_news(message.value)