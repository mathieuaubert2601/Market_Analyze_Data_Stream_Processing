import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import os
from rag_engine import get_answer
from src.config import TICKERS, HISTORY_PATH # On a besoin du chemin

st.set_page_config(page_title="Market Analyst AI", page_icon="📈", layout="wide")
st.title("📈 Smart Dashboard (Full Kafka Architecture)")

# --- FONCTION GRAPHIQUE (SOURCE : FICHIERS LOCAUX) ---
def display_stock_chart(ticker):
    """Lit le CSV généré par Kafka/Consumer et affiche le graphique"""
    csv_file = os.path.join(HISTORY_PATH, f"{ticker}.csv")
    
    if not os.path.exists(csv_file):
        st.warning(f"⏳ Données pour {ticker} en cours d'arrivée via Kafka... (Attendez quelques secondes)")
        return

    try:
        # Lecture du CSV local
        data = pd.read_csv(csv_file, index_col='date', parse_dates=True)
        
        if data.empty:
            st.warning("Données vides.")
            return

        # Graphique
        fig = go.Figure(data=[go.Candlestick(
            x=data.index,
            open=data['Open'], high=data['High'],
            low=data['Low'], close=data['Close'],
            name=ticker
        )])
        
        # Moyenne Mobile 50j (calculée sur les données locales)
        data['MA50'] = data['Close'].rolling(window=50).mean()
        fig.add_trace(go.Scatter(x=data.index, y=data['MA50'], mode='lines', name='MA 50', line=dict(color='orange')))
        
        fig.update_layout(title=f"{ticker} (Source: Kafka/Local)", height=450, template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)
        
    except Exception as e:
        st.error(f"Erreur lecture fichier : {e}")

# --- SIDEBAR (PRIX LIVE) ---
# Note: Pour le "Live" ultra-rapide (la seconde), on garde yfinance.fast_info en direct
# car Kafka est utilisé ici pour le "Trend" (l'historique) et l'analyse.
def display_sidebar():
    st.sidebar.header("🔴 Live Market")
    if st.sidebar.button("🔄 Rafraîchir"):
        st.rerun()
        
    for ticker in TICKERS:
        try:
            stock = yf.Ticker(ticker)
            info = stock.fast_info
            last = info['last_price']
            prev = info['previous_close']
            delta = ((last - prev) / prev) * 100
            
            color = "green" if delta >= 0 else "red"
            icon = "🟢" if delta >= 0 else "🔴"
            
            st.sidebar.markdown(f"**{ticker}**")
            st.sidebar.markdown(f"{last:.2f} {info['currency']} (:{color}[{icon} {delta:.2f}%])")
            st.sidebar.divider()
        except: pass

display_sidebar()

# --- CHATBOT ---
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("🤖 Analyste")
    query = st.text_input("Question...", placeholder="Ex: Analyse STM")
    
    if st.button("Analyser", type="primary") and query:
        with st.spinner('Analyses Kafka en cours...'):
            response, sources, dominant_ticker = get_answer(query)
            st.success("Réponse IA")
            st.markdown(response)
            
            if dominant_ticker:
                st.divider()
                st.subheader(f"📊 Données Historiques : {dominant_ticker}")
                display_stock_chart(dominant_ticker)

with col2:
    st.subheader("📡 Flux Kafka")
    if 'sources' in locals() and sources:
        for s in sources:
            icon = "🚨" if s['type'] == 'alert' else ("📊" if s['type'] == 'technical' else "🗞️")
            with st.expander(f"{icon} {s['ticker']} [{s['date']}]"):
                st.write(f"**{s['title']}**")
                st.caption(f"Sentiment: {s['sentiment']:.2f}")
                st.markdown(f"[Lire la suite]({s['link']})")