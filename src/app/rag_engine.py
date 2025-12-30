import os
import sys
import json
import time
import math
import re
import datetime
import chromadb
from groq import Groq
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from src.config import (
    CHROMA_PATH,
    COLLECTION_NAME,
    EMBEDDING_MODEL_NAME,
    LLM_MODEL_NAME,
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

def parse_date_flexible(date_str: str) -> int:
    """
    Convert a date string to UNIX timestamp with multiple formats.
    """
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d"
    ]
    
    for fmt in formats:
        try:
            dt = datetime.datetime.strptime(date_str, fmt)
            return int(dt.timestamp())
        except ValueError:
            continue
    raise ValueError(f"Aucun format de date ne correspond pour : {date_str}")

def parse_query_intent(user_query: str, client_groq: Groq) -> dict:
    """
    ROUTER AGENT: Analyzes the user query to extract specific search parameters.
    Outputs a JSON with target ticker, precise time window strings, and intent.
    """
    now = datetime.datetime.now()
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    day_name = now.strftime('%A')
    
    system_prompt = (
        f"CRITICAL SYSTEM INSTRUCTION: Today is STRICTLY {now_str} ({day_name}).\n"
        "Ignore your internal training data cutoff. You must use the provided Current System Time for all date calculations.\n\n"
        
        "You are a Query Router for a Financial RAG System. "
        "Analyze the user's question and output a STRICT JSON object.\n\n"
        
        "### 1. TICKER MAPPING (Contextual):"
        "\n- LVMH, Louis Vuitton, Luxury, Arnault -> 'MC.PA'"
        "\n- Total, TotalEnergies, Oil, Energy -> 'TTE.PA'"
        "\n- L'Oreal, Cosmetics, Beauty -> 'OR.PA'"
        "\n- Hermes, Birkin, Luxury -> 'RMS.PA'"
        "\n- Sanofi, Pharma, Health -> 'SAN.PA'"
        "\n- Safran, Engines, Aerospace, Defense -> 'SAF.PA'"  
        "\n- Schneider, Electric, Energy Mgmt -> 'SU.PA'"
        "\n- Air Liquide, Hydrogen, Gas -> 'AI.PA'"
        "\n- BNP, Bank, Finance -> 'BNP.PA'"
        "\n- Vinci, Construction, Highways -> 'DG.PA'"
        "\n- If no specific company is named, return null.\n\n"
        
        "### 2. TIME WINDOW RULES:"
        f"\n- Reference 'NOW' is {now_str}."
        "\n- 'Last week': If today is Monday/Tuesday, it usually means the full previous Monday-Friday week."
        "\n- 'La semaine dernière': Calculate the Start Date (Previous Monday) and End Date (Previous Friday)."
        "\n- 'Now', 'Current', 'Live': start = NOW minus 24 hours, end = NOW."
        "\n\n"
        
        "### 3. INTENT RULES:"
        "\n- If looking for immediate price action/news -> 'REAL_TIME'"
        "\n- If looking for past events, trends, or specific past dates -> 'HISTORICAL'\n\n"
        
        "OUTPUT FORMAT (JSON ONLY - USE ISO FORMAT FOR DATES):"
        "\n{"
        '\n  "ticker": "SYMBOL" or null,'
        '\n  "start_date_str": "YYYY-MM-DD HH:MM:SS",'
        '\n  "end_date_str": "YYYY-MM-DD HH:MM:SS",'
        '\n  "intent": "REAL_TIME" or "HISTORICAL"'
        "\n}"
    )

    try:
        completion = client_groq.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0,
            response_format={"type": "json_object"}
        )
        content = completion.choices[0].message.content
        data = json.loads(content)
        
        # --- ROBUST PARSING ---
        try:
            start_ts = parse_date_flexible(data.get("start_date_str"))
            end_ts = parse_date_flexible(data.get("end_date_str"))
        except Exception as parse_error:
            print(f"⚠️ [Router] Date Parsing Error: {parse_error}")
            print(f"🔍 DEBUG: LLM returned Start='{data.get('start_date_str')}' End='{data.get('end_date_str')}'")
            raise parse_error

        return {
            "ticker": data.get("ticker"),
            "start_timestamp": start_ts,
            "end_timestamp": end_ts,
            "intent": data.get("intent")
        }

    except Exception as e:
        print(f"⚠️ [Router] General Error or Fallback triggered: {e}")
        # Fallback safe defaults (24h)
        return {
            "ticker": None,
            "start_timestamp": int(time.time() - 86400),
            "end_timestamp": int(time.time()),
            "intent": "REAL_TIME"
        }

def calculate_score(distance: float, timestamp: float, intent: str) -> float:
    """
    Calculates document relevance score.
    - If REAL_TIME: Apply time decay (recent = better).
    - If HISTORICAL: Ignore time decay (relevance is purely semantic).
    """
    # Base similarity score (Cosine Similarity approx)
    similarity = 1 - distance
    
    if intent == "HISTORICAL":
        return similarity
    else:
        now = time.time()
        age = max(now - timestamp, 0)
        decay = math.exp(-age / 14400)
        
        return (similarity * 0.6) + (decay * 0.4)

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
    except Exception:
        return "   - Live price data unavailable."

# --- MAIN RAG LOGIC ---
def get_answer(user_query: str):
    query_vector = embedding_model.encode(user_query).tolist()
    
    # 2. CALL ROUTER
    route_data = parse_query_intent(user_query, client_groq)
    
    target_ticker = route_data.get("ticker")
    start_ts = route_data.get("start_timestamp")
    end_ts = route_data.get("end_timestamp")
    intent = route_data.get("intent")
    
    horizon_seconds = float(end_ts - start_ts)

    print(f"[RAG] Router: {target_ticker} | Intent: {intent}")
    print(f"[RAG] Window: {datetime.datetime.fromtimestamp(start_ts)} -> {datetime.datetime.fromtimestamp(end_ts)}")

    # 3. ChromaDB Query
    time_filter = {
        "$and": [
            {"timestamp": {"$gte": start_ts}},
            {"timestamp": {"$lte": end_ts}}
        ]
    }
    
    final_filter = time_filter
    if target_ticker:
        final_filter = {"$and": [time_filter, {"ticker": {"$eq": target_ticker}}]}

    results = collection.query(
        query_embeddings=[query_vector],
        n_results=20,
        where=final_filter,
        include=["documents", "metadatas", "distances"],
    )

    # 4. Re-Ranking
    combined_docs = []
    seen_hashes = set()
    
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    if documents:
        for i, doc in enumerate(documents):
            meta = metadatas[i]
            dist = distances[i]
            
            unique_hash = (
                f"{meta.get('ticker')}_"
                f"{int(meta.get('timestamp', 0))}_"
                f"{meta.get('type', 'unknown')}"
            )
            if unique_hash in seen_hashes:
                continue
            seen_hashes.add(unique_hash)

            timestamp = float(meta.get("timestamp", 0))
            score = calculate_score(dist, timestamp, intent)

            combined_docs.append({
                "doc": doc,
                "meta": meta,
                "timestamp": timestamp,
                "score": score,
                "type": meta.get("type")
            })

    combined_docs.sort(key=lambda x: x["score"], reverse=True)
    top_docs = combined_docs[:8]

    # 5. Build Context
    horizon_hours = round(horizon_seconds / 3600, 2)
    now_str = datetime.datetime.now().strftime('%A %Y-%m-%d %H:%M:%S')
    context_text = f"CURRENT SYSTEM TIME: {now_str}\n"
    context_text += f"USER INTENT: {intent} (Window: {horizon_hours} hours).\n\n"

    sources = []
    dominant_ticker = target_ticker

    if not top_docs:
        context_text += (
            "SYSTEM ALERT: No data found within this specific time window.\n"
        )

    for item in top_docs:
        meta = item["meta"]
        if not dominant_ticker:
            dominant_ticker = meta.get("ticker")
        ts_str = datetime.datetime.fromtimestamp(
            item["timestamp"]
        ).strftime("%Y-%m-%d %H:%M")

        source_entry = {
            "ticker": meta.get("ticker"),
            "title": item["doc"][:100] + "...",
            "link": meta.get("link", "#"),
            "date": ts_str,
            "type": meta.get("type"),
            "sentiment": meta.get("sentiment"),
            "current_price": meta.get("current_price"),
            "timestamp": item["timestamp"],
            "mean_50": meta.get("mean_50"),
            "mean_200": meta.get("mean_200"),
            "currency": meta.get("currency", "EUR"),
            "market_state": meta.get("market_state", "N/C"),
        }

        if meta.get("type") == "daily_summary":
            content = item["doc"]

            open_match = re.search(r"Open:\s*([\d\.]+)", content)
            if open_match:
                source_entry["opening_price"] = float(open_match.group(1))

            high_match = re.search(r"High:\s*([\d\.]+)", content)
            if high_match:
                source_entry["high_price"] = float(high_match.group(1))

            low_match = re.search(r"Low:\s*([\d\.]+)", content)
            if low_match:
                source_entry["low_price"] = float(low_match.group(1))

            close_match = re.search(r"Close:\s*([\d\.]+)", content)
            if close_match:
                source_entry["closing_price"] = float(close_match.group(1))

            var_match = re.search(r"Variation:\s*([-\d\.]+)", content)
            if var_match:
                source_entry["variation_pct"] = float(var_match.group(1))

            vol_match = re.search(r"Volume:\s*(\d+)", content)
            if vol_match:
                source_entry["volume"] = int(vol_match.group(1))

        sources.append(source_entry)

        doc_type = meta.get("type")
        if doc_type == "intraday_metrics":
            context_text += (
                f"📊 [REAL-TIME METRICS] {meta.get('ticker')} @ {ts_str}:\n"
            )
            context_text += format_price_context(meta) + "\n\n"
        elif doc_type == "technical":
            context_text += (
                f"📈 [TECHNICAL ANALYSIS] {meta.get('ticker')} @ {ts_str}:\n"
                f"{item['doc']}\n\n"
            )
        elif doc_type == "daily_summary":
            context_text += (
                f"🗓️ [MARKET HISTORY] {meta.get('ticker')} @ {ts_str}:\n"
                f"{item['doc']}\n\n"
            )
        else:
            sentiment = meta.get('sentiment', 0)
            context_text += (
                f"📰 [NEWS] {meta.get('ticker')} @ {ts_str} "
                f"(Sentiment: {sentiment:.2f}):\n{item['doc']}\n\n"
            )

    current_datetime = datetime.datetime.now().strftime(
        "%A %Y-%m-%d %H:%M"
    )
    
    system_instruction = (
        "You are a Senior Equity Strategist at a major investment bank "
        "(e.g., Goldman Sachs, Morgan Stanley). "
        "Your job is to produce high-frequency 'Flash Notes' for portfolio managers. "
        "You have access to a proprietary data stream containing real-time news, "
        "sentiment scores, and technical market data.\n\n"

        "### 🚨 CRITICAL DIRECTIVE: ENGLISH ONLY 🚨\n"
        "Regardless of the language used in the user's prompt "
        "(even if it is French, Spanish, etc.), "
        "**YOU MUST ANSWER STRICTLY IN PROFESSIONAL ENGLISH.** "
        "Do not translate the user's question, just answer it in English.\n\n"

        "### DATA INTERPRETATION RULES:\n"
        "1. **Synthesize, Don't List:** Do not say 'Source A says this... "
        "Source B says that'. Instead, weave a narrative: 'Despite strong "
        "earnings, regulatory headwinds are pressuring the stock...'.\n"
        "2. **Utilize the Data:** You have access to Open, High, Low, Close, "
        "and Volume data.\n"
        "   - If 'Open' is significantly different from 'Close', "
        "discuss intraday volatility.\n"
        "   - If 'Volume' is high, mention conviction.\n"
        "   - Compare the 'Current Price' to the moving averages (MA50, MA200) "
        "to determine the trend (Bullish/Bearish).\n"
        "3. **Sentiment Analysis:** Use the provided sentiment scores "
        "(from -1 to 1) to gauge market psychology. (e.g., 'Investor sentiment "
        "is deteriorating despite price stability').\n\n"

        "### REQUIRED OUTPUT STRUCTURE (Markdown):\n\n"
        "#Market Flash: {TICKER} Institutional Note\n\n"
        "**Executive Verdict**: [One concise sentence. Example: 'Tactical BUY "
        "on dip' or 'Neutral pending earnings'.]\n\n"
        "## 1. Macro & Fundamental Drivers\n"
        "* **The Catalyst**: Synthesize the key news driving the move.\n"
        "* **Context**: Why does this matter? (Earnings impact, sector "
        "rotation, macro event).\n\n"
        "## 2. Technical & Price Action Deep Dive\n"
        "* **Trend Analysis**: Analyze the price relative to MA50/MA200. "
        "Is it in an uptrend or downtrend?\n"
        "* **Volatility Insight**: Look at the High/Low spread provided in "
        "the context. Is the range tightening or expanding?\n"
        "* **Volume Profile**: Is the move supported by volume?\n\n"
        "## 3. Forward Outlook (Next 24h - 1 Week)\n"
        "* **Scenario**: What to watch for next? (e.g., 'A break above 14.50 "
        "confirms the reversal').\n"
        "* **Risk Factors**: What could go wrong?\n\n"
        "--- \n"
        "*Generated via Real-Time RAG Engine | Data: Kafka Stream & "
        "VADER Sentiment*"
        f"\n\n### CONTEXTUAL DATA STREAM (System Time: {current_datetime}):"
        f"\n{context_text}"
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
        return (
            chat.choices[0].message.content,
            sources,
            dominant_ticker,
            horizon_seconds
        )
    except Exception as e:
        return f"🚨 AI Engine Error: {e}", sources, None, horizon_seconds