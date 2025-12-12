import os
import chromadb
import datetime
import sys
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

def get_answer(user_query):
    """
    Fonction principale du RAG :
    Structure la réponse en 3 parties : Présentation, News/Impact, Technique.
    """
    
    # 1. Vectorisation de la question
    query_vector = embedding_model.encode(user_query).tolist()
    
    # 2. DÉTECTION INTELLIGENTE DU TICKER
    target_ticker = None
    query_upper = user_query.upper()
    
    # Dictionnaire de synonymes (Version compacte)
    SYNONYMS = {
        "STLAP.PA": ["STELLANTIS", "STLA", "PEUGEOT", "PSA", "CITROEN", "FIAT", "CHRYSLER", "FCA", "JEEP"],
        "STMPA.PA": ["STMICROELECTRONICS", "STM", "STMICRO", "SGS-THOMSON", "SEMI-CONDUCTEURS"],
        "ORA.PA":   ["ORANGE", "FRANCE TELECOM", "OPERATEUR"],
        "ENGI.PA":  ["ENGIE", "GDF", "GDF SUEZ", "GAZ DE FRANCE"],
        "ALHPI.PA": ["HOPIUM", "MACHINA", "HYDROGENE"],
        "CS.PA":    ["AXA", "GROUPE AXA", "ASSURANCE"],
        "DCAM.PA":  ["AMUNDI", "ETF MONDE", "MSCI WORLD", "CW8", "AMUNDI WORLD"],
        "ETZ.PA":   ["BNP", "STOXX 600", "ETF EUROPE", "BNP EASY"],
    }

    # Recherche inversée dans les synonymes
    for ticker, mots_cles in SYNONYMS.items():
        if any(mot in query_upper for mot in mots_cles):
            target_ticker = ticker
            break
            
    if not target_ticker:
        for t in TICKERS:
            if t in query_upper:
                target_ticker = t
                break
    
    # 3. STRATÉGIE DE RÉCUPÉRATION (HYBRID FETCHING)
    combined_docs = []
    seen_hashes = set()

    def process_results(results_obj):
        if results_obj['documents']:
            for i, doc in enumerate(results_obj['documents'][0]):
                meta = results_obj['metadatas'][0][i]
                unique_hash = f"{meta.get('ticker')}_{meta.get('doc', '')[:20]}"
                if unique_hash in seen_hashes: continue
                seen_hashes.add(unique_hash)

                try: ts = float(meta.get('timestamp', 0))
                except: ts = 0.0
                
                combined_docs.append({
                    "doc": doc, "meta": meta, "timestamp": ts, 
                    "sentiment": meta.get('sentiment', 0.0)
                })

    # Construction des filtres avec la syntaxe $and
    if target_ticker:
        print(f"🎯 Cible verrouillée : {target_ticker}")
        search_filters_news = {"$and": [{"type": {"$eq": "news"}}, {"ticker": {"$eq": target_ticker}}]}
        search_filters_tech = {"$and": [{"type": {"$eq": "technical"}}, {"ticker": {"$eq": target_ticker}}]}
    else:
        search_filters_news = {"type": "news"}
        search_filters_tech = {"type": "technical"}

    # A. Récupérer les News
    try:
        results_news = collection.query(
            query_embeddings=[query_vector],
            n_results=6,
            where=search_filters_news
        )
        process_results(results_news)
    except: pass

    # B. Récupérer la Tech
    try:
        results_tech = collection.query(
            query_embeddings=[query_vector],
            n_results=2,
            where=search_filters_tech
        )
        process_results(results_tech)
    except: pass

    # 4. TRI ET SÉLECTION FINALE
    combined_docs.sort(key=lambda x: x['timestamp'], reverse=True)
    
    dominant_ticker = target_ticker
    if not dominant_ticker and combined_docs:
        tickers_found = [d['meta'].get('ticker') for d in combined_docs]
        if tickers_found:
            dominant_ticker = Counter(tickers_found).most_common(1)[0][0]

    # 5. CONSTRUCTION DU CONTEXTE
    context_text = ""
    sources = []
    
    # Si vide
    if not combined_docs:
        return "⚠️ Je n'ai trouvé aucune information récente (News ou Analyse) pour cette demande dans le flux Kafka.", [], None

    for item in combined_docs[:8]:
        meta = item['meta']
        try: date_str = datetime.datetime.fromtimestamp(item['timestamp']).strftime('%d/%m %H:%M')
        except: date_str = "?"
        
        badge = "ACTUALITÉ" if meta.get('type') == 'news' else "TECHNIQUE"
        ticker_name = meta.get('ticker', 'Inconnu')
        
        context_text += f"SOURCE [{date_str}] ({badge}) SUJET:{ticker_name} CONTENU: {item['doc']}\n"
        
        sources.append({
            "ticker": ticker_name,
            "title": item['doc'],
            "link": meta.get('link', '#'),
            "date": date_str,
            "type": meta.get('type'),
            "sentiment": item['sentiment'],
            "current_price": meta.get('current_price', None),
            "mean_200": meta.get('mean_200', None),
            "mean_50": meta.get('mean_50', None),
            "mean_10": meta.get('mean_10', None),
        })

    # 6. PROMPT STRUCTURÉ (C'EST ICI QUE TOUT CHANGE)
    system_prompt = (
        "Tu es un analyste financier senior de haut niveau."
        "\n\nOBJECTIF :"
        "\nProduire une note d'analyse structurée, claire et professionnelle pour un investisseur."
        "\n\nSTRUCTURE DE LA RÉPONSE OBLIGATOIRE :"
        "\n\n1. 🏢 PRÉSENTATION & SECTEUR"
        "\n   - Présente brièvement l'entreprise et son secteur d'activité."
        "\n   - *Exception :* Pour cette partie uniquement, tu peux utiliser tes connaissances générales."
        "\n\n2. 📰 DERNIÈRES ACTUALITÉS & IMPACT"
        "\n   - Résume les actualités fournies dans le CONTEXTE ci-dessous."
        "\n   - Pour chaque news, donne le nom de l'article et analyse brièvement son impact potentiel (Positif/Négatif/Neutre)."
        "\n   - Si le contexte ne contient aucune news, écris : 'Aucune actualité récente détectée dans le flux'."
        "\n   - *Règle :* Utilise STRICTEMENT le contexte. N'invente pas de news."
        "\n\n3. 📈 ANALYSE TECHNIQUE DU COURS"
        "\n   - Donne le Prix Actuel et la Variation."
        "\n   - Analyse la Tendance (Haussière/Baissière) en te basant sur les Moyennes Mobiles du contexte."
        "\n   - *Règle :* Utilise STRICTEMENT le contexte pour les chiffres."
        "\n\n4. 📝 CONCLUSION"
        "\n   - Synthèse rapide en une phrase sur le sentiment général (Bullish/Bearish)."
        "\n\nCONTEXTE TEMPS RÉEL (KAFKA) :"
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