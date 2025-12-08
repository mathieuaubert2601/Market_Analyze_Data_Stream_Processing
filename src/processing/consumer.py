import json
import sys
import os
import chromadb
from kafka import KafkaConsumer
from sentence_transformers import SentenceTransformer
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from src.config import KAFKA_BOOTSTRAP_SERVERS, KAFKA_TOPIC_NEWS, CHROMA_PATH, COLLECTION_NAME, EMBEDDING_MODEL_NAME

print("⏳ [Consumer] Chargement des modèles IA...")
embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
analyzer = SentimentIntensityAnalyzer()

print("📂 [Consumer] Connexion ChromaDB...")
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name=COLLECTION_NAME)

def process_message(message):
    try:
        data = message.value
        
        # --- SÉCURITÉ : Vérification du Titre ---
        # Si le titre est None, on met une chaîne vide pour ne pas faire planter Vader
        raw_title = data.get('title', "")
        if raw_title is None:
            raw_title = ""
            
        # Si vraiment pas de titre, on ignore le message
        if not raw_title.strip():
            print(f"⚠️ Message ignoré (Titre vide): {data}")
            return

        # 1. Calcul du Sentiment
        sentiment_score = analyzer.polarity_scores(raw_title)['compound']
        
        # 2. Vectorisation
        # On ajoute le ticker pour donner du contexte au vecteur
        text_to_embed = f"{data.get('ticker', 'UNKNOWN')}: {raw_title}"
        vector = embedding_model.encode(text_to_embed).tolist()
        
        unique_id = f"{data.get('ticker', 'UNK')}_{data.get('publish_time', '0')}"
        
        # 3. Stockage
        collection.upsert(
            ids=[unique_id],
            embeddings=[vector],
            documents=[raw_title], 
            metadatas=[{
                "ticker": data.get('ticker', 'UNKNOWN'),
                "timestamp": data.get('publish_time', 0),
                "source": data.get('publisher', 'Unknown'),
                "link": data.get('link', '#'),
                "type": data.get('type', 'news'),
                "sentiment": sentiment_score
            }]
        )
        
        # Affichage console
        emoji = "😐"
        if sentiment_score > 0.05: emoji = "🟢"
        elif sentiment_score < -0.05: emoji = "🔴"
        
        print(f"✅ {emoji} [Sent: {sentiment_score:.2f}] {data.get('ticker')} - {data.get('type')}")

    except Exception as e:
        print(f"❌ Erreur lors du traitement d'un message : {e}")

if __name__ == "__main__":
    os.makedirs(CHROMA_PATH, exist_ok=True)
    
    consumer = KafkaConsumer(
        KAFKA_TOPIC_NEWS,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        auto_offset_reset='earliest',
        value_deserializer=lambda x: json.loads(x.decode('utf-8')),
        group_id='rag-indexer-sentiment-v2' # J'ai changé le group_id pour éviter de relire les erreurs
    )
    
    print("🎧 [Consumer] Prêt à analyser les sentiments...")
    
    for message in consumer:
        process_message(message)