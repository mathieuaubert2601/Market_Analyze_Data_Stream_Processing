import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import os
from rag_engine import get_answer
from src.config import TICKERS, HISTORY_PATH # On a besoin du chemin

st.set_page_config(page_title="Market Analyst AI", page_icon="📈", layout="wide")
st.title("Financial Market Analyst")

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
    if st.sidebar.button("🔄 Refresh"):
        st.rerun()
    st.sidebar.header("🕑 Live Market")
    for ticker in TICKERS:
        try:
            stock = yf.Ticker(ticker)
            info = stock.fast_info
            last = info['last_price']
            prev = info['previous_close']
            delta = ((last - prev) / prev) * 100
            
            color = "green" if delta >= 0 else "red"
            icon = "+" if delta >= 0 else ""
            #Green if the market is open, red if closed
            market_state = "🟢" if stock.info.get("marketState") == "REGULAR" else "🔴"
            st.sidebar.markdown(f"**{ticker}** - {market_state}")
            st.sidebar.markdown(f"{last:.4f} {info['currency']} (:{color}[{icon} {delta:.2f}%])")
            st.sidebar.divider()
        except: pass

display_sidebar()

# --- CHATBOT ---
col1, col2 = st.columns([2, 1])

with col1:
    with st.form(key='analysis_form'):
        query = st.text_input("Question...", placeholder="Ex: Could you perfom an analysis about STM ?")
        submit_button = st.form_submit_button(label="Analyze", type="primary")

    if submit_button and query:
        with st.spinner('Kafka analyses in progress...'):
            response, sources, dominant_ticker = get_answer(query)
            st.success("AI Response generated!")
            st.markdown(response)
            
            if dominant_ticker:
                st.divider()
                st.subheader(f"📊 Historical Data: {dominant_ticker}")
                display_stock_chart(dominant_ticker)

with col2:
    st.subheader("📡 Sources")
    if 'sources' in locals() and sources:
        for s in sources:
            icon = "📰" if s['type'] == 'news' else "📈"

            if(s['type'] == 'technical'):
                with st.expander(f"{icon} {s['ticker']} - Technical Analysis"):
                    st.write(f"Date : {s['date']}")
                    def fmt(val):
                        if val is None or val == 'N/A' or val != val: # val != val détecte aussi NaN
                            return "N/A"
                        try:
                            return f"{float(val):.2f}"
                        except:
                            return str(val)
                        
                    current_price = s.get('current_price')
                    mean_200 = s.get('mean_200')
                    mean_50 = s.get('mean_50')
                    mean_10 = s.get('mean_10')
                    last_close = s.get('last_close')
                    opening_price = s.get('opening_price')
                    price_12h_ago = s.get('price_12h_ago')
                    price_6h_ago = s.get('price_6h_ago')
                    price_3h_ago = s.get('price_3h_ago')
                    price_1h_ago = s.get('price_1h_ago')
                    price_30min_ago = s.get('price_30min_ago')
                    price_10min_ago = s.get('price_10min_ago')


                    if current_price is not None:
                        st.write(f"Current Price: {fmt(current_price)}")
                    if mean_200 is not None:
                        st.write(f"Long term mean (200j): {fmt(mean_200)}")
                    if mean_50 is not None:
                        st.write(f"Medium term mean (50j): {fmt(mean_50)}")
                    if mean_10 is not None:
                        st.write(f"Short term mean (10j): {fmt(mean_10)}")
                    if last_close is not None:
                        st.write(f"Last Close: {fmt(last_close)}")
                    if opening_price is not None:
                        st.write(f"Opening Price: {fmt(opening_price)}")
                    if price_12h_ago is not None:
                        st.write(f"Price 12h ago: {fmt(price_12h_ago)}")
                    if price_6h_ago is not None:
                        st.write(f"Price 6h ago: {fmt(price_6h_ago)}")
                    if price_3h_ago is not None:
                        st.write(f"Price 3h ago: {fmt(price_3h_ago)}")
                    if price_1h_ago is not None:
                        st.write(f"Price 1h ago: {fmt(price_1h_ago)}") 
                    if price_30min_ago is not None:
                        st.write(f"Price 30min ago: {fmt(price_30min_ago)}")
                    if price_10min_ago is not None:
                        st.write(f"Price 10min ago: {fmt(price_10min_ago)}")
                    st.markdown(f"[Read more]({s['link']})")

            
            if(s['type'] == 'news'):
                with st.expander(f"{icon} {s['ticker']} - News Article"):
                    st.write(f"Date : {s['date']}")
                    st.write(f"**{s['title']}**")
                    st.caption(f"Sentiment: {s['sentiment']:.2f}")
                    st.markdown(f"[Read more]({s['link']})")
        