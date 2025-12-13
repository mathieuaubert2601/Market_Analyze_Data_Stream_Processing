import os
import chromadb
import datetime
import sys
import json
import time
import math
import re
from groq import Groq
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv
from collections import Counter

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from src.config import (
    CHROMA_PATH,
    COLLECTION_NAME,
    EMBEDDING_MODEL_NAME,
    LLM_MODEL_NAME,
    TICKERS,
    HORIZON_RECENT,
    HORIZON_HISTORICAL,
)

# --- INITIALIZATION ---
load_dotenv()

api_key = os.getenv("GROQ_API_KEY")
if not api_key:
    raise ValueError("❌ Missing GROQ_API_KEY in .env file")

# Initialize Clients
client_groq = Groq(api_key=api_key)

print("[RAG] Loading Embedding Model...")
embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)

print(f"[RAG] Connecting to ChromaDB at {CHROMA_PATH}...")
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_collection(name=COLLECTION_NAME)

# --- HELPER FUNCTIONS ---

def get_dynamic_horizon(user_query: str, client_groq: Groq) -> float:
    """
    TIME AGENT: Calculates the ideal search window in HOURS.
    Example: 
    - "Why is it dropping now?" -> Returns 2 hours (in seconds).
    - "What happened last Friday?" (asked on Sunday) -> Returns 48 or 72 hours.
    """
    now_str = datetime.datetime.now().strftime("%A %d %B %Y at %H:%M")
    
    system_prompt = (
        f"Current System Date/Time: {now_str}."
        "\nYou are a Time Horizon Calculator. "
        "\nBased on the user query, determine how many HOURS back I need to search to find the answer."
        "\n\nRULES:"
        "\n- If query is about 'now', 'current', 'live', 'moment': Return '2' (2 hours)."
        "\n- If query is about 'yesterday': Return '24'."
        "\n- If query is about a specific day (e.g., 'Friday') and today is different: Calculate the hours difference."
        "\n- If query is 'history', 'trend', 'long term': Return '720' (30 days)."
        "\n- OUTPUT: Just the integer number. No text."
    )

    try:
        resp = client_groq.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt}, 
                {"role": "user", "content": user_query}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0,
            max_tokens=10,
        )
        text = resp.choices[0].message.content
        hours = int(re.search(r'\d+', text).group())
        
        # Security cap: Minimum 2h, Max 30 days
        hours = max(2, min(hours, 720))
        return float(hours * 3600)
    except Exception as e:
        print(f"[Time Agent] Error: {e}. Defaulting to 2h.")
        return HORIZON_RECENT


def _decay(now: float, timestamp: float, horizon: float) -> float:
    """
    Exponential Time Decay.
    Scores drop significantly as they approach the horizon limit.
    """
    if not timestamp:
        return 0.0
    # Scale factor based on the dynamic horizon
    scale = max(horizon / 3, 1) 
    age = max(now - timestamp, 0)
    return math.exp(-age / scale)


def format_price_context(meta: dict) -> str:
    """Formats intraday metrics for the LLM."""
    try:
        current = meta.get('current_price', 0)
        p_10m = meta.get('price_10min_ago', 0)
        p_1h = meta.get('price_1h_ago', 0)
        
        var_10m = ((current - p_10m) / p_10m * 100) if p_10m else 0
        var_1h = ((current - p_1h) / p_1h * 100) if p_1h else 0
        
        return (
            f"   - **Live Price**: {current:.2f} {meta.get('currency', 'EUR')}\n"
            f"   - **Momentum**: 10m: {var_10m:+.2f}% | 1h: {var_1h:+.2f}%\n"
            f"   - **Key Levels**: MA50: {meta.get('mean_50', 0):.2f} | MA200: {meta.get('mean_200', 0):.2f}"
        )
    except:
        return "   - Live price data unavailable."


# --- MAIN RAG LOGIC ---
def get_answer(user_query: str):
    # 1. Embed Query
    query_vector = embedding_model.encode(user_query).tolist()
    query_upper = user_query.upper()

    # 2. Identify Ticker (Heuristic)
    target_ticker = None
    SYNONYMS = {
        "STLAP.PA": ["STELLANTIS", "STLA", "PEUGEOT"],
        "STMPA.PA": ["STMICRO", "STM", "CHIP"],
        "ORA.PA": ["ORANGE", "TELECOM"],
        "ENGI.PA": ["ENGIE", "GAS", "ENERGY"],
        "CS.PA": ["AXA", "INSURANCE"],
        "ETZ.PA": ["BNP", "BANK"],
    }
    for ticker, keywords in SYNONYMS.items():
        if any(k in query_upper for k in keywords):
            target_ticker = ticker
            break
    if not target_ticker:
        for t in TICKERS:
            if t in query_upper:
                target_ticker = t
                break

    # 3. CALL TIME AGENT (Dynamic Horizon)
    now = time.time()
    horizon_seconds = get_dynamic_horizon(user_query, client_groq)
    
    # Adjust Strategy based on Agent's decision
    if horizon_seconds <= HORIZON_RECENT: # Less than 2 hours = REAL TIME MODE
        intent_label = "LIVE_TRADING"
        weight_cosine = 0.3
        weight_decay = 0.7 # Heavy Time Decay
    elif horizon_seconds > HORIZON_RECENT and horizon_seconds <= HORIZON_HISTORICAL: # Looking back days/weeks = CONTEXT MODE
        intent_label = "HISTORICAL_ANALYSIS"
        weight_cosine = 0.8
        weight_decay = 0.2 # Relevance matters more than "seconds ago"

    print(f"[RAG] Query: '{user_query}' | Ticker: {target_ticker} | Horizon: {horizon_seconds} seconds ({intent_label})")

    # 4. ChromaDB Query
    search_filters = {"timestamp": {"$gt": now - horizon_seconds}}
    if target_ticker:
        search_filters = {"$and": [search_filters, {"ticker": {"$eq": target_ticker}}]}

    results = collection.query(
        query_embeddings=[query_vector],
        n_results=20, 
        where=search_filters if search_filters else None,
        include=["documents", "metadatas", "distances"],
    )

    # 5. Re-Ranking & Sorting
    combined_docs = []
    seen_hashes = set()
    
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    if documents:
        for i, doc in enumerate(documents):
            meta = metadatas[i]
            dist = distances[i]
            
            unique_hash = f"{meta.get('ticker')}_{meta.get('doc', '')[:20]}"
            if unique_hash in seen_hashes: continue
            seen_hashes.add(unique_hash)

            timestamp = float(meta.get("timestamp", 0))
            
            # Dynamic Score Calculation
            score = (weight_cosine * (1 - dist)) + (weight_decay * _decay(now, timestamp, horizon_seconds))

            combined_docs.append({
                "doc": doc,
                "meta": meta,
                "timestamp": timestamp,
                "score": score,
                "type": meta.get("type")
            })

    combined_docs.sort(key=lambda x: x["score"], reverse=True)
    top_docs = combined_docs[:8] 

    # 6. Build Context for LLM
    horizon_hours = round(horizon_seconds / 3600, 2)
    context_text = f"CURRENT SYSTEM TIME: {datetime.datetime.now().strftime('%A %Y-%m-%d %H:%M:%S')}\n"
    context_text += f"SEARCH WINDOW: Last {horizon_hours} hours (Intent: {intent_label}).\n\n"
    
    sources = []
    dominant_ticker = target_ticker

    if not top_docs:
        context_text += "SYSTEM ALERT: No data found within this time window. Markets might be closed or pipeline empty.\n"
    
    for item in top_docs:
        meta = item["meta"]
        # Show full date if looking back days, else just time
        fmt = "%H:%M:%S" if horizon_hours < 24 else "%Y-%m-%d %H:%M"
        ts_str = datetime.datetime.fromtimestamp(item["timestamp"]).strftime(fmt)
        
        sources.append({
            "ticker": meta.get("ticker"),
            "title": item["doc"],
            "link": meta.get("link", "#"),
            "date": ts_str,
            "type": meta.get("type"),
            "sentiment": meta.get("sentiment"),
            "current_price": meta.get("current_price"),
            "mean_50": meta.get("mean_50"),
            "mean_200": meta.get("mean_200"),
            "timestamp": item["timestamp"]
        })

        if meta.get("type") == "intraday_metrics":
            context_text += f"📊 [REAL-TIME METRICS] {meta.get('ticker')} @ {ts_str}:\n"
            context_text += format_price_context(meta) + "\n\n"
        elif meta.get("type") == "technical":
            context_text += f"📈 [TECHNICAL ANALYSIS] {meta.get('ticker')} @ {ts_str}:\n{item['doc']}\n\n"
        else:
            context_text += f"📰 [NEWS] {meta.get('ticker')} @ {ts_str} (Sentiment: {meta.get('sentiment', 0):.2f}):\n{item['doc']}\n\n"

    # 7. Final System Prompt
    system_instruction = (
        "You are a Senior Quantitative Analyst at a top-tier investment bank."
        f"\n\n### CONTEXT SETTING:"
        f"\n- The user asked for data covering the last **{horizon_hours} hours**."
        "\n- If the data is from Friday and today is Sunday, THIS IS EXPECTED. Analyze the Friday close."
        "\n- If the user asks for 'Live' data but the latest timestamp is old, warn them: 'Markets are closed/Data is delayed'."
        "\n\n### ANALYSIS RULES:"
        "\n1. **Metrics First**: Use [REAL-TIME METRICS] to quote specific % variations (10m, 1h)."
        "\n2. **Trend**: Compare Price vs MA200. Price < MA200 = Bearish."
        "\n3. **Causality**: If news explains the drop, link the News Title to the Price Action."
        "\n\n### RESPONSE FORMAT (Markdown):"
        "\n**🔴 Market Update** (or 🟢)"
        "\n* **Price Action**: [Price] ([Variation]%)"
        "\n* **Technical**: [Trend Status vs MA200]"
        "\n* **Catalyst**: [Why is it moving?]"
        f"\n\n### DATA CONTEXT:\n{context_text}"
    )

    try:
        chat = client_groq.chat.completions.create(
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_query},
            ],
            model=LLM_MODEL_NAME,
            temperature=0.2, 
        )
        return chat.choices[0].message.content, sources, dominant_ticker, horizon_seconds
    except Exception as e:
        return f"🚨 AI Engine Error: {e}", sources, None, horizon_seconds
