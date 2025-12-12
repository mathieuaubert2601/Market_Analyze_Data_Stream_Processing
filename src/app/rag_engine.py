import os
import chromadb
import datetime
import sys
import json
import time
from groq import Groq
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv
from collections import Counter

# Ajout du chemin racine pour les imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from src.config import CHROMA_PATH, COLLECTION_NAME, EMBEDDING_MODEL_NAME, LLM_MODEL_NAME, TICKERS

# --- INITIALISATION ---
load_dotenv()

api_key = os.getenv("GROQ_API_KEY")
if not api_key:
    raise ValueError("❌ Clé API GROQ manquante dans le fichier .env")

client_groq = Groq(api_key=api_key)

print("⏳ [RAG] Chargement du modèle d'embedding...")
embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)

print("📂 [RAG] Connexion à ChromaDB...")
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_collection(name=COLLECTION_NAME)

# --- FONCTIONS D'AIDE ---

def determine_intent(user_query, client_groq):
    """
    Détermine si l'utilisateur veut du récent (RSS/Live) ou de l'historique.
    """
    system_prompt = (
        "Tu es un routeur temporel. Ta réponse doit être UN SEUL mot."
        "\n- Réponds 'RECENT' si la question contient : aujourd'hui, ce matin, maintenant, news, actualité récente, dernier moment, chute, hausse."
        "\n- Réponds 'HISTORICAL' si la question est générale, porte sur l'analyse technique moyen terme, le passé, ou une synthèse."
    )
    try:
        resp = client_groq.chat.completions.create(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_query}],
            model="llama-3.3-70b-versatile",
            temperature=0,
            max_tokens=10
        )
        intent = resp.choices[0].message.content.strip().upper()
        if "RECENT" in intent: return "RECENT"
        return "HISTORICAL"
    except:
        return "HISTORICAL"

# --- FONCTION PRINCIPALE ---

def get_answer(user_query):
    """
    Fonction principale du RAG (Uniquement via ChromaDB).
    """
    
    # 1. VECTORISATION
    query_vector = embedding_model.encode(user_query).tolist()
    
    # 2. DÉTECTION DU TICKER
    target_ticker = None
    query_upper = user_query.upper()
    
    SYNONYMS = {
        "STLAP.PA": ["STELLANTIS", "STLA", "PEUGEOT", "PSA"],
        "STMPA.PA": ["STMICROELECTRONICS", "STM", "STMICRO"],
        "ORA.PA":   ["ORANGE", "FRANCE TELECOM"],
        "ENGI.PA":  ["ENGIE", "GDF"],
        "CS.PA":    ["AXA", "ASSURANCE"],
        "ETZ.PA":   ["BNP", "PARIBAS"]
    }

    for ticker, mots_cles in SYNONYMS.items():
        if any(mot in query_upper for mot in mots_cles):
            target_ticker = ticker
            break
            
    if not target_ticker:
        for t in TICKERS:
            if t in query_upper:
                target_ticker = t
                break
    
    # 3. ROUTAGE INTELLIGENT
    intent = determine_intent(user_query, client_groq)
    print(f"🧠 Intention : {intent} | Ticker : {target_ticker}")

    context_text = ""
    sources = []
    dominant_ticker = target_ticker

    # --- CONFIGURATION DES FILTRES CHROMA ---
    # Par défaut, on cherche tout type de contenu pertinent
    search_filters = {}
    
    if target_ticker:
        search_filters["ticker"] = {"$eq": target_ticker}

    # Si RECENT : on force la récupération des données 'intraday' et 'news'
    # ChromaDB ne gère pas facilement le tri temporel pur, donc on récupère
    # les vecteurs proches et on triera en Python par date.
    
    # Récupération Vectorielle
    results = collection.query(
        query_embeddings=[query_vector],
        n_results=15, # On prend large pour filtrer ensuite
        where=search_filters if target_ticker else None
    )

    combined_docs = []
    seen_hashes = set()

    if results['documents']:
        for i, doc in enumerate(results['documents'][0]):
            meta = results['metadatas'][0][i]
            
            # Déduplication
            unique_hash = f"{meta.get('ticker')}_{meta.get('doc', '')[:20]}"
            if unique_hash in seen_hashes: continue
            seen_hashes.add(unique_hash)
            
            timestamp = float(meta.get('timestamp', 0))
            doc_type = meta.get('type', 'unknown')

            # Pondération temporelle (Recency Weighting)
            # Si l'intention est RECENT, on pénalise les vieux documents
            if intent == "RECENT":
                # Si le doc a plus de 24h (86400s), on l'ignore sauf si c'est de l'historique pur
                if (time.time() - timestamp) > 86400 and doc_type == 'news':
                    continue
            
            combined_docs.append({
                "doc": doc,
                "meta": meta,
                "timestamp": timestamp
            })

    # Tri final par date décroissante (Le plus récent en haut)
    combined_docs.sort(key=lambda x: x['timestamp'], reverse=True)

    # Sélection des Top résultats
    final_docs = combined_docs[:8]

    # Construction du contexte pour le LLM
    if not dominant_ticker and final_docs:
        tickers_found = [d['meta'].get('ticker') for d in final_docs]
        if tickers_found: dominant_ticker = Counter(tickers_found).most_common(1)[0][0]

    for item in final_docs:
        meta = item['meta']
        try: date_str = datetime.datetime.fromtimestamp(item['timestamp']).strftime('%d/%m %H:%M')
        except: date_str = "?"
        
        doc_type = meta.get('type', 'info').upper()
        source_origin = meta.get('source', 'unknown') # google_rss ou yahoo
        
        # Badge visuel pour le contexte
        badge = f"[{doc_type} | {source_origin}]"
        
        context_text += f"SOURCE {badge} [{date_str}] SUJET:{meta.get('ticker')} : {item['doc']}\n"
        
        sources.append({
            "ticker": meta.get('ticker'), 
            "title": item['doc'], 
            "link": meta.get('link', '#'),
            "date": date_str, 
            "type": meta.get('type'), 
            "sentiment": meta.get('sentiment', 0),
            "current_price": meta.get('current_price'), 
            "mean_50": meta.get('mean_50'),
            "mean_10": meta.get('mean_10'),
            "mean_200": meta.get('mean_200'),
            # Ajout des champs intraday si dispos
            "price_10min_ago": meta.get('price_10min_ago'),
            "price_1h_ago": meta.get('price_1h_ago'),
            "price_3h_ago": meta.get('price_3h_ago'),
            "price_6h_ago": meta.get('price_6h_ago'),
            "price_12h_ago": meta.get('price_12h_ago'),
            "last_close": meta.get('last_close'),
            "opening_price": meta.get('opening_price')
        })

    # --- CAS DE VIDE (FALLBACK) ---
    if not context_text:
        context_text = "Aucune information récente trouvée dans la base de connaissances (Kafka)."

    # 4. GÉNÉRATION LLM
    system_prompt = (
        "You are a Senior Quantitative Analyst at a top-tier investment bank."
        "\n\nOBJECTIVE:"
        "\nProduce a highly detailed, data-driven market commentary using ALL available technical and fundamental data points."
        "\n\nCRITICAL DATA RULES (MANDATORY):"
        "\n1. **Use Specific Numbers**: Never say 'the stock dropped'. Say 'the stock dropped -0.45% over the last hour'."
        "\n2. **Compare vs Moving Averages**: You MUST compare the 'Current Price' against the 'Mean_50' and 'Mean_200' if available. State if the price is ABOVE or BELOW these levels to define the trend."
        "\n3. **Cite Sources**: When mentioning a number, specify its origin (e.g., '[Technical Report]', '[Intraday Metrics]')."
        "\n4. **English Only**: Output must be in professional English."
        "\n\nDATA DICTIONARY:"
        "\n- [INTRADAY_METRICS]: Variations (10m, 1h, 6h). Use this for immediate momentum."
        "\n- [TECHNICAL]: Contains MA50 (Medium Term) and MA200 (Long Term Trend). Use MA200 to define the 'secular trend'."
        "\n- [NEWS] / [RSS]: Context for WHY the numbers are moving."
        "\n\nRESPONSE STRUCTURE:"
        "\n## Executive Summary"
        "\n(Synthesize the trend in one sentence using the price vs MA200)."
        "\n\n## Technical Health Check"
        "\n* **Trend Analysis**: Compare Current Price vs MA50 and MA200. (e.g., 'Price (14.50) is trading below MA200 (15.20), indicating a long-term bearish trend.')"
        "\n* **Intraday Volatility**: Cite the 1h and 6h variations explicitly."
        "\n\n## Fundamental Catalysts"
        "\n(Connect the news to the numbers. Did the news cause the 1h drop?)"
        "\n\n## Analyst Outlook"
        "\n(Final verdict: Bullish, Bearish, or Neutral based on the confluence of Technicals and News.)"
        "\n\nCONTEXT DATA:"
        f"\n{context_text}"
    )
    
    try:
        chat = client_groq.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ],
            model=LLM_MODEL_NAME,
            temperature=0.2
        )
        return chat.choices[0].message.content, sources, dominant_ticker
    except Exception as e:
        return f"❌ Erreur IA : {e}", sources, None