import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from rag_engine import get_answer
from src.config import TICKERS

st.set_page_config(page_title="Market Analyst AI", page_icon="📈", layout="wide")
st.title("📈 Smart Financial Dashboard (RAG + VIZ)")

# --- 1. FONCTIONS D'AFFICHAGE (Graphiques & Sidebar) ---

def display_stock_chart(ticker):
    """Affiche un graphique interactif (Bougies) avec Plotly"""
    try:
        # On récupère un peu plus d'historique pour le graphique
        data = yf.Ticker(ticker).history(period="6mo")
        
        if data.empty:
            st.warning(f"Pas de données graphiques pour {ticker}")
            return

        # Graphique en Bougies
        fig = go.Figure(data=[go.Candlestick(
            x=data.index,
            open=data['Open'], high=data['High'],
            low=data['Low'], close=data['Close'],
            name=ticker
        )])
        
        # Moyenne Mobile 50 jours (Ligne Orange)
        fig.add_trace(go.Scatter(
            x=data.index, 
            y=data['Close'].rolling(window=50).mean(), 
            mode='lines', 
            name='MA 50', 
            line=dict(color='orange', width=1)
        ))
        
        fig.update_layout(
            title=f"Cours : {ticker} (6 mois)",
            xaxis_title="Date", yaxis_title="Prix",
            height=450, template="plotly_dark",
            margin=dict(l=20, r=20, t=50, b=20)
        )
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error(f"Erreur graphique {ticker}: {e}")

def display_sidebar_metrics():
    """Affiche les prix en direct et l'état du marché"""
    st.sidebar.header("🔴 Live Market")
    st.sidebar.caption("État des marchés & Cours en temps réel")
    
    for ticker in TICKERS:
        try:
            stock = yf.Ticker(ticker)
            
            # Récupération Info Rapide
            fast_info = stock.fast_info
            
            # État du marché (Ouvert/Fermé)
            market_state = stock.info.get('marketState', 'UNKNOWN')
            
            if market_state == "REGULAR":
                state_icon, state_color = "🟢", "green"
            elif "PRE" in market_state:
                state_icon, state_color = "🟠", "orange" # Pre-market
            elif "POST" in market_state:
                state_icon, state_color = "🌙", "orange" # Post-market
            elif "CLOSED" in market_state:
                state_icon, state_color = "🔴", "red"
            else:
                state_icon, state_color = "⚪", "grey"

            # Calculs Variation
            last = fast_info['last_price']
            prev = fast_info['previous_close']
            delta = last - prev
            delta_pct = (delta / prev) * 100
            
            # Affichage Badge Statut
            st.sidebar.markdown(f":{state_color}[{state_icon} **{ticker}**]")
            
            # Affichage Prix
            st.sidebar.metric(
                label="Prix",
                value=f"{last:.2f} {fast_info['currency']}",
                delta=f"{delta:.2f} ({delta_pct:.2f}%)",
                label_visibility="collapsed"
            )
            st.sidebar.divider()

        except Exception:
            st.sidebar.markdown(f"⚠️ **{ticker}**: Erreur Data")

# --- 2. EXÉCUTION DE LA SIDEBAR ---

# Bouton Rafraîchir
if st.sidebar.button("🔄 Rafraîchir les prix", use_container_width=True):
    display_sidebar_metrics()
else:
    display_sidebar_metrics() # Affichage par défaut

# --- 3. ZONE PRINCIPALE (CHAT & RAG) ---

col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("🤖 Chatbot Analyste")
    query = st.text_input("Posez votre question...", placeholder="Ex: Analyse la tendance de Tesla et affiche le graphique")
    
    if st.button("Analyser", type="primary"):
        if query:
            with st.spinner('🔍 Analyse Sémantique, Technique & Sentimentale...'):
                # On récupère la réponse ET le ticker dominant pour le graphique
                response, sources, dominant_ticker = get_answer(query)
                
                st.success("Analyse IA :")
                st.markdown(response)
                
                # AFFICHE LE GRAPHIQUE SI UN TICKER EST DÉTECTÉ
                if dominant_ticker:
                    st.divider()
                    st.subheader(f"📊 Focus : {dominant_ticker}")
                    display_stock_chart(dominant_ticker)
                else:
                    st.caption("Aucune action spécifique détectée pour afficher un graphique.")

with col2:
    st.subheader("📡 Flux & Sentiments")
    
    if 'sources' in locals() and sources:
        for s in sources:
            # --- GESTION VISUELLE DES SOURCES ---
            
            # 1. Type de source (Icône)
            if s['type'] == 'alert':
                icon = "🚨"
                st.toast(f"Alerte sur {s['ticker']}", icon="🚨")
            elif s['type'] == 'technical':
                icon = "📊"
            else:
                icon = "🗞️" # News

            # 2. Sentiment (Couleur & Jauge)
            sent = s['sentiment']
            if sent > 0.05:
                sent_txt = "Positif"
                sent_color = "green"
            elif sent < -0.05:
                sent_txt = "Négatif"
                sent_color = "red"
            else:
                sent_txt = "Neutre"
                sent_color = "grey"

            # 3. Affichage Carte (Expander)
            label = f"{icon} {s['ticker']} [{s['date']}]"
            with st.expander(label):
                st.caption(f"Type: {s['type'].upper()}")
                st.markdown(f"Sentiment: :{sent_color}[**{sent_txt}**] ({sent:.2f})")
                st.write(f"**{s['title']}**")
                
                if s['link'] and s['link'] != '#':
                    st.markdown(f"[🔗 Lire la source]({s['link']})")
    else:
        st.info("Les sources (News, Analyses Techniques, Alertes) apparaîtront ici.")