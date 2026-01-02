import time
import os
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import datetime
from rag_engine import get_answer
from src.config import TICKERS, HISTORY_PATH, CHROMA_PATH, COLLECTION_NAME
import chromadb

st.set_page_config(
    page_title="Real-Time Market AI",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("⚡ Real-Time Financial Market Analyst")


def human_format(num):
    """Formats large numbers (e.g. 1000000 -> 1.0M)"""
    if num is None:
        return "N/A"
    try:
        num = float(num)
        magnitude = 0
        while abs(num) >= 1000:
            magnitude += 1
            num /= 1000.0
        return '%.1f%s' % (num, ['', 'K', 'M', 'B', 'T'][magnitude])
    except Exception:
        return str(num)


def fmt_relative(ts: float) -> str:
    """Formats timestamp into 'X min ago'."""
    if not ts:
        return "n/a"
    try:
        delta = max(int(time.time() - float(ts)), 0)
        if delta < 60:
            return f"{delta}s ago"
        if delta < 3600:
            return f"{delta // 60}m ago"
        if delta < 86400:
            return f"{delta // 3600}h ago"
        return f"{delta // 86400}d ago"
    except Exception:
        return "n/a"


def fmt(val):
    """Format numeric values with 2 decimal places."""
    if val is None or val == 'N/A' or val != val:
        return "N/A"
    try:
        return f"{float(val):.2f}"
    except Exception:
        return str(val)


def check_system_health() -> tuple[str, str]:
    """Checks if the Consumer is actively writing to the heartbeat file."""
    heartbeat_file = os.path.join(HISTORY_PATH, "consumer_heartbeat.txt")
    status = "🔴 OFFLINE"
    color = "red"

    if os.path.exists(heartbeat_file):
        try:
            with open(heartbeat_file, "r") as f:
                last_beat = float(f.read().strip())

            delta = time.time() - last_beat
            if delta < 120:
                status = "🟢 ONLINE"
                color = "green"
            else:
                status = f"🟠 LAGGING ({int(delta)}s)"
                color = "orange"
        except Exception:
            pass

    return status, color


def display_stock_chart(ticker: str) -> None:
    """Reads local CSV history and plots with MA50 and MA200."""
    csv_file = os.path.join(HISTORY_PATH, f"{ticker}.csv")

    if not os.path.exists(csv_file):
        st.info(f"⏳ Waiting for Kafka stream to populate data for {ticker}...")
        return

    try:
        data = pd.read_csv(csv_file)

        if data.columns[0] != "date":
            data = data.rename(columns={data.columns[0]: "date"})

        data = data.set_index("date")
        data.index = pd.to_datetime(data.index, errors='coerce')

        data.columns = [col.strip().capitalize() for col in data.columns]

        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in data.columns:
                data[col] = pd.to_numeric(data[col], errors='coerce')

        data = data.dropna(subset=["Open", "High", "Low", "Close"])

        if data.empty:
            st.warning("📊 Empty CSV or invalid data")
            return

        fig = go.Figure(data=[go.Candlestick(
            x=data.index,
            open=data["Open"],
            high=data["High"],
            low=data["Low"],
            close=data["Close"],
            name=ticker
        )])

        if len(data) > 50:
            ma50 = data["Close"].rolling(window=50).mean()
            fig.add_trace(go.Scatter(
                x=data.index,
                y=ma50,
                mode="lines",
                name="MA 50",
                line=dict(color="orange", width=2)
            ))

        if len(data) > 200:
            ma200 = data["Close"].rolling(window=200).mean()
            fig.add_trace(go.Scatter(
                x=data.index,
                y=ma200,
                mode="lines",
                name="MA 200",
                line=dict(color="blue", width=2)
            ))

        fig.update_layout(
            title=f"{ticker} (Source: Kafka/Local)",
            height=450,
            template="plotly_dark"
        )
        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Chart Error: {e}")


@st.cache_data(ttl=30)
def get_sidebar_data() -> list[dict]:
    """Fetches latest intraday metrics from ChromaDB."""
    results = []

    try:
        chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
        collection = chroma_client.get_collection(name=COLLECTION_NAME)
    except Exception:
        st.sidebar.warning(
            "⚠️ ChromaDB unavailable: waiting for Kafka data..."
        )
        return []

    for ticker in TICKERS:
        try:
            results_chroma = collection.query(
                query_texts=[f"Momentum Intraday {ticker}"],
                where={
                    "$and": [
                        {"ticker": {"$eq": ticker}},
                        {"type": {"$eq": "intraday_metrics"}}
                    ]
                },
                n_results=1,
                include=["metadatas"]
            )

            if results_chroma["metadatas"] and results_chroma["metadatas"][0]:
                meta = results_chroma["metadatas"][0][0]

                current_price = meta.get("current_price", 0)
                prev_close = meta.get("last_close", current_price)

                results.append({
                    "ticker": ticker,
                    "price": current_price,
                    "prev": prev_close if prev_close else current_price,
                    "currency": meta.get("currency", "EUR"),
                    "market_state": meta.get("market_state", "CLOSED"),
                    "mean_50": meta.get("mean_50", 0),
                    "mean_200": meta.get("mean_200", 0),
                    "sentiment": meta.get("sentiment", 0),
                    "regularMarketTime": meta.get("regularMarketTime", 0)
                })
            else:
                results.append({
                    "ticker": ticker,
                    "price": 0,
                    "prev": 0,
                    "currency": "---",
                    "market_state": "WAITING",
                    "mean_50": 0,
                    "mean_200": 0,
                    "sentiment": 0,
                    "regularMarketTime": 0
                })

        except Exception as e:
            print(f"[Sidebar] Error fetching {ticker}: {e}")

    return results


def display_sidebar() -> None:
    """Displays the sidebar with system status and market watch."""
    status, color = check_system_health()
    st.sidebar.markdown(f"### Pipeline Status: :{color}[{status}]")

    if st.sidebar.button("🔄 Refresh Data"):
        get_sidebar_data.clear()
        st.rerun()

    st.sidebar.divider()
    st.sidebar.subheader("📈 Market Watch")

    market_data = get_sidebar_data()

    for item in market_data:
        if item['market_state'] == "WAITING":
            st.sidebar.markdown(f"**{item['ticker']}** ⏳")
            st.sidebar.caption("Waiting for Kafka data...")
            st.sidebar.divider()
            continue

        delta = (
            ((item['price'] - item['prev']) / item['prev']) * 100
            if item['prev'] else 0
        )
        color_delta = "green" if delta >= 0 else "red"
        icon = "▲" if delta >= 0 else "▼"

        market_indicator = (
            "🟢" if item['market_state'] == "REGULAR" else "🔴"
        )

        st.sidebar.markdown(f"**{item['ticker']}** {market_indicator}")
        st.sidebar.markdown(
            f"{item['price']:.4f} {item['currency']} "
            f":{color_delta}[{icon} {delta:.2f}%]"
        )

        try:
            last_price_time = item.get('regularMarketTime')
            if last_price_time and last_price_time > 0:
                dt = datetime.datetime.fromtimestamp(last_price_time)
                time_str = dt.strftime("%d/%m/%Y %H:%M")
            else:
                time_str = "N/A"
        except Exception:
            time_str = "N/A"

        st.sidebar.caption(f"📅 {time_str}")
        st.sidebar.divider()


display_sidebar()

col1, col2 = st.columns([2, 1])

if 'sources' not in st.session_state:
    st.session_state.sources = None
if 'answer' not in st.session_state:
    st.session_state.answer = None
if 'ticker' not in st.session_state:
    st.session_state.ticker = None

with col1:
    with st.container():
        st.markdown("### 🤖 AI Market Analyst")
        with st.form(key="query_form"):
            query = st.text_input(
                "Ask about market trends, news, or technicals:",
                placeholder="Why is Stellantis dropping right now?"
            )
            submit = st.form_submit_button("Analyze", type="primary")

    if submit and query:
        with st.spinner("🧠 Agent is analyzing Kafka streams..."):
            answer, sources, ticker, horizon = get_answer(query)

            st.session_state.sources = sources
            st.session_state.answer = answer
            st.session_state.ticker = ticker

            horizon_hours = round(horizon / 3600, 1)
            mode_label = (
                "🔴 LIVE MODE" if horizon_hours <= 24 else "📚 HISTORY MODE"
            )
            st.caption(
                f"{mode_label} | Search Window: Last {horizon_hours} hours"
            )

            st.success("✅ Analysis Complete")
            st.markdown(answer)

            if ticker:
                st.divider()
                display_stock_chart(ticker)

with col2:
    st.subheader("📡 Context Sources")

    if st.session_state.sources:
        for s in st.session_state.sources:
            if s['type'] == 'technical':
                icon = "📈"
                relative_time = fmt_relative(s.get('timestamp'))

                try:
                    market_state = s.get('market_state', 'UNKNOWN')
                    if market_state != "CLOSED":
                        market_display = "🟢 OPEN"
                        market_color = "green"
                    else:
                        market_display = "🔴 CLOSED"
                        market_color = "red"
                except Exception:
                    market_display = "❓ UNKNOWN"
                    market_color = "gray"

                with st.expander(
                    f"{icon} {s['ticker']} - Technical Analysis "
                    f"({relative_time})"
                ):
                    st.caption(
                        f"📅 {s['date']} | "
                        f":{market_color}[{market_display}]"
                    )

                    if s.get('regularMarketTime') and s['regularMarketTime'] != 0:
                        try:
                            dt = datetime.datetime.fromtimestamp(
                                s['regularMarketTime']
                            )
                            last_price_date = dt.strftime(
                                "%A %d/%m/%Y %H:%M"
                            )
                            st.caption(
                                f"Last Price Update: {last_price_date}"
                            )
                        except Exception:
                            pass

                    price_parts = []
                    if s.get('current_price'):
                        price_parts.append(
                            f"Current Price: {fmt(s['current_price'])} "
                            f"{s.get('currency', '')}"
                        )
                    if s.get('last_close'):
                        price_parts.append(f"Close: {fmt(s['last_close'])}")
                    if s.get('opening_price'):
                        price_parts.append(f"Open: {fmt(s['opening_price'])}")
                    if price_parts:
                        st.write(" | ".join(price_parts))

                    ma_parts = []
                    if s.get('mean_10'):
                        ma_parts.append(f"MA10: {fmt(s['mean_10'])}")
                    if s.get('mean_50'):
                        ma_parts.append(f"MA50: {fmt(s['mean_50'])}")
                    if s.get('mean_200'):
                        ma_parts.append(f"MA200: {fmt(s['mean_200'])}")
                    if ma_parts:
                        st.write(" | ".join(ma_parts))

                    price_history = []
                    if s.get('price_12h_ago'):
                        price_history.append(f"12h: {fmt(s['price_12h_ago'])}")
                    if s.get('price_6h_ago'):
                        price_history.append(f"6h: {fmt(s['price_6h_ago'])}")
                    if s.get('price_3h_ago'):
                        price_history.append(f"3h: {fmt(s['price_3h_ago'])}")
                    if s.get('price_1h_ago'):
                        price_history.append(f"1h: {fmt(s['price_1h_ago'])}")
                    if s.get('price_30min_ago'):
                        price_history.append(
                            f"30m: {fmt(s['price_30min_ago'])}"
                        )
                    if s.get('price_10min_ago'):
                        price_history.append(
                            f"10m: {fmt(s['price_10min_ago'])}"
                        )
                    if price_history:
                        st.write(" | ".join(price_history))

                    if s.get('link') and s['link'] != "#":
                        st.markdown(f"[📖 Read more]({s['link']})")

            elif s['type'] == 'news':
                icon = "📰"
                relative_time = fmt_relative(s.get('timestamp'))

                with st.expander(
                    f"{icon} {s['ticker']} - News ({relative_time})"
                ):
                    st.caption(f"📅 {s['date']}")
                    st.write(f"{s['title']}")

                    sentiment_score = s.get('sentiment')
                    if sentiment_score is not None and sentiment_score != "N/A":
                        try:
                            sentiment_float = float(sentiment_score)
                            if sentiment_float > 0.5:
                                sentiment_label = "🟢 Positive"
                                sentiment_color = "green"
                            elif sentiment_float < -0.5:
                                sentiment_label = "🔴 Negative"
                                sentiment_color = "red"
                            else:
                                sentiment_label = "⚪ Neutral"
                                sentiment_color = "gray"

                            st.write(
                                f"**Sentiment:** :{sentiment_color}"
                                f"[{sentiment_label} ({sentiment_float:.2f})]"
                            )
                        except Exception:
                            pass

                    st.divider()
                    if s.get('link') and s['link'] != "#":
                        st.markdown(
                            f"[📖 Read full article]({s['link']})"
                        )

            elif s['type'] == 'daily_summary':
                icon = "🗓️"
                ts_val = s.get('timestamp')
                date_str = (
                    datetime.datetime.fromtimestamp(ts_val).strftime(
                        "%d/%m"
                    )
                    if ts_val else ""
                )

                with st.expander(f"{icon} {s['ticker']} ({date_str})"):

                    if s.get('opening_price') is not None:
                        # 1. Préparation de l'affichage de la variation (Couleur + Flèche)
                        var = s.get('variation_pct')
                        if var is not None:
                            color = "green" if var >= 0 else "red"
                            icon = "▲" if var >= 0 else "▼"
                            # Syntaxe Markdown Streamlit pour la couleur
                            var_str = f":{color}[{icon} {var:.2f}%]"
                        else:
                            var_str = "N/A"

                        currency = s.get('currency', '')
                        vol = human_format(s.get('volume'))

                        # 2. Affichage compact en 3 colonnes x 2 lignes
                        # On utilise st.markdown pour avoir un texte petit et formatté
                        c1, c2, c3 = st.columns(3)

                        with c1:
                            st.markdown(f"**Open:** {fmt(s['opening_price'])}")
                            st.markdown(f"**Close:** {fmt(s['closing_price'])}")
                        
                        with c2:
                            st.markdown(f"**High:** {fmt(s['high_price'])}")
                            st.markdown(f"**Low:** {fmt(s['low_price'])}")

                        with c3:
                            st.markdown(f"**Vol:** {vol}")
                            st.markdown(f"**Var:** {var_str}")

                    else:
                        st.warning("⚠️ Incomplete data")
                        st.caption(s.get('title'))
    else:
        st.info("📌 Sources will appear here after analysis.")