import os
import chromadb
import datetime
import sys
from groq import Groq
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv
from collections import Counter

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from src.config import CHROMA_PATH, COLLECTION_NAME, EMBEDDING_MODEL_NAME, LLM_MODEL_NAME, TICKERS

load_dotenv()
api_key = os.getenv("GROQ_API_KEY")
client_groq = Groq(api_key=api_key)
embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_collection(name=COLLECTION_NAME)

def get_answer(user_query):
    query_vector = embedding_model.encode(user_query).tolist()
    
    # --- 1. LOGIQUE DE DÉTECTION DU SUJET ---
    target_ticker = None
    query_upper = user_query.upper()
    
    # Dictionnaire de synonymes (Nom Humain -> Ticker Technique)
    synonyms = {
        "STM": "STMPA.PA", "STMICRO": "STMPA.PA", 
        "STELLANTIS": "STLAP.PA", "STLA": "STLAP.PA",
        "ORANGE": "ORA.PA", "ENGIE": "ENGI.PA",
        "TESLA": "TSLA", "NVIDIA": "NVDA", "GOOGLE": "GOOGL"
    }
    
    # Recherche dans les synonymes
    for name, symb in synonyms.items():
        if name in query_upper:
            target_ticker = symb
            break
            
    # Recherche dans la liste brute des tickers
    if not target_ticker:
        for t in TICKERS:
            if t in query_upper:
                target_ticker = t
                break
    
    # --- 2. FILTRE STRICT (La solution anti-mélange) ---
    search_filters = {}
    if target_ticker:
        print(f"🎯 Sujet identifié : {target_ticker} -> Filtre activé.")
        # ON FORCE LA BASE A NE DONNER QUE CE TICKER
        search_filters = {"ticker": target_ticker}
    else:
        print("⚠️ Pas de sujet précis identifié, recherche large.")

    # --- 3. REQUÊTE BASE DE DONNÉES ---
    results = collection.query(
        query_embeddings=[query_vector],
        n_results=10,
        where=search_filters if target_ticker else None # <--- FILTRE APPLIQUÉ ICI
    )
    
    # --- 4. TRAITEMENT DES RÉSULTATS ---
    processed_docs = []
    seen_hashes = set()
    
    if results['documents']:
        for i, doc in enumerate(results['documents'][0]):
            meta = results['metadatas'][0][i]
            
            # On vérifie que les métadonnées essentielles sont là
            if 'ticker' not in meta or meta['ticker'] == 'UNKNOWN':
                continue # On saute les données corrompues

            # Anti-doublon
            unique_hash = f"{meta.get('ticker')}_{meta.get('timestamp')}"
            if unique_hash in seen_hashes: continue
            seen_hashes.add(unique_hash)

            try: ts = float(meta.get('timestamp', 0))
            except: ts = 0.0
            
            processed_docs.append({
                "doc": doc, "meta": meta, "timestamp": ts, 
                "sentiment": meta.get('sentiment', 0.0)
            })

    processed_docs.sort(key=lambda x: x['timestamp'], reverse=True)
    
    # Détermination du ticker dominant pour afficher le graphique
    dominant_ticker = target_ticker
    if not dominant_ticker and processed_docs:
        tickers_found = [d['meta'].get('ticker') for d in processed_docs]
        if tickers_found:
            dominant_ticker = Counter(tickers_found).most_common(1)[0][0]

    # --- 5. CONSTRUCTION DU CONTEXTE ---
    context_text = ""
    sources = []
    
    for item in processed_docs[:6]:
        meta = item['meta']
        try: date_str = datetime.datetime.fromtimestamp(item['timestamp']).strftime('%d/%m %H:%M')
        except: date_str = "?"
        
        # Le contexte est clair pour l'IA
        context_text += f"- [{date_str}] [{meta.get('type')}] Info sur {meta.get('ticker')} : {item['doc']}\n"
        
        sources.append({
            "ticker": meta.get('ticker'),
            "title": item['doc'],
            "link": meta.get('link'),
            "date": date_str,
            "type": meta.get('type'),
            "sentiment": item['sentiment']
        })
    
    if not context_text:
        return "Je n'ai pas trouvé d'informations récentes sur cette entreprise.", [], None

    # Prompt sécurisé
    system_prompt = (
        "Tu es un expert boursier. Utilise le contexte fourni pour répondre. "
        "Si l'utilisateur demande une action précise, ne parle QUE de celle-là. "
        "Fais attention aux devises (EUR pour Paris, USD pour US). "
        "Ne mélange pas les chiffres."
    )
    
    try:
        chat = client_groq.chat.completions.create(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_query}],
            model=LLM_MODEL_NAME, temperature=0.3
        )
        return chat.choices[0].message.content, sources, dominant_ticker
    except Exception as e:
        return f"Erreur IA: {e}", sources, None