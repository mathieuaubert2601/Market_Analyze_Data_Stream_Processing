# 📈 Market Analyze Data Stream Processing

A real-time **Financial Market Analysis System** powered by **Apache Kafka**, **RAG (Retrieval-Augmented Generation)**, and **LLM** (Llama 3.3 70B via Groq). This project ingests live market data, financial news, and technical indicators, then provides AI-powered insights through an interactive Streamlit dashboard.

Acces to the streamlit live of our application (the data are those published on the github, there is no update because streamlit live do not allow to run kafka) https://marketanalyzedatastreamprocessing-2gecwcwivwcr54mfuqrjmh.streamlit.app/

---

## 📑 Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Quick Start](#quick-start)
- [Usage](#usage)
  - [Producer](#producer)
  - [Consumer](#consumer)
  - [Streamlit App](#streamlit-app)
- [Kafka Topics](#kafka-topics)
- [Technical Details](#technical-details)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

**Market Analyze Data Stream Processing** is a real-time financial analytics platform that: 

1. **Ingests** live market data from Yahoo Finance and Google News RSS
2. **Processes** data through Apache Kafka streams with sentiment analysis
3. **Stores** enriched documents in ChromaDB vector database for semantic search
4. **Analyzes** user queries using RAG with Llama 3.3 70B LLM
5. **Visualizes** insights through an interactive Streamlit dashboard

The system monitors **10 major CAC 40 stocks** (LVMH, TotalEnergies, L'Oréal, Hermès, Sanofi, Safran, Schneider Electric, Air Liquide, BNP Paribas, Vinci) and provides institutional-grade market analysis. 

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DATA SOURCES                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│  Yahoo Finance API          Google News RSS                                  │
│  • Real-time prices         • Financial news articles                        │
│  • Historical OHLCV         • Company-specific news                          │
│  • Company info             • Multi-language support                         │
└──────────────────┬──────────────────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         KAFKA PRODUCER                                       │
│  src/ingestion/producer.py                                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  • Fetches live market data (price, volume, MA indicators)                   │
│  • Scrapes Google News RSS for financial news                                │
│  • Generates intraday metrics (10m, 30m, 1h, 3h, 6h momentum)                │
│  • Calculates technical analysis (MA10, MA50, MA200, trend)                  │
│  • Creates daily summaries (OHLCV + variation)                               │
└──────────────────┬──────────────────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         APACHE KAFKA                                         │
│  docker-compose.yml (Zookeeper + Kafka)                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│  Topics:                                                                     │
│  • financial-news      → News articles + Technical analysis                  │
│  • stock-history       → OHLCV history for charts                            │
│  • hot-news-events     → Intraday metrics & momentum                         │
│  • daily-summary       → End-of-day summaries                                │
└──────────────────┬──────────────────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         KAFKA CONSUMER                                       │
│  src/processing/consumer.py                                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  • Translates news to English (deep-translator)                              │
│  • Performs sentiment analysis (VADER)                                       │
│  • Generates embeddings (sentence-transformers)                              │
│  • Stores in ChromaDB vector database                                        │
│  • Saves OHLCV history to CSV files                                          │
│  • Enforces 30-day data retention policy                                     │
└──────────────────┬──────────────────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CHROMADB + CSV                                       │
│  data/chromadb/ + data/history/                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  • Vector embeddings for semantic search                                     │
│  • Metadata:  ticker, timestamp, sentiment, prices, MA indicators             │
│  • CSV files for candlestick charts                                          │
└──────────────────┬──────────────────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         RAG ENGINE                                           │
│  src/app/rag_engine.py                                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│  • Query Router Agent (intent detection + time window calculation)           │
│  • Semantic search in ChromaDB                                               │
│  • Re-ranking with time decay for real-time queries                          │
│  • Context building for LLM                                                  │
│  • Llama 3.3 70B (Groq API) for response generation                          │
└──────────────────┬──────────────────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         STREAMLIT APP                                        │
│  src/app/main.py                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  • Real-time market watch sidebar                                            │
│  • AI-powered market analyst chat interface                                  │
│  • Interactive candlestick charts (MA50 + MA200)                             │
│  • Source context display (news, technicals, daily summaries)                │
│  • Pipeline health monitoring                                                │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Features

### 🔄 Real-Time Data Ingestion
- **Yahoo Finance Integration**: Live prices, OHLCV data, company info
- **Google News RSS**:  Financial news scraping with multi-language support
- **Intraday Momentum**: 10min, 30min, 1h, 3h, 6h price variations
- **Technical Indicators**: MA10, MA50, MA200, trend detection (Bullish/Bearish/Neutral)

### 🧠 AI-Powered Analysis
- **RAG Architecture**: Retrieval-Augmented Generation for context-aware responses
- **Query Router Agent**:  Automatic intent detection (REAL_TIME vs HISTORICAL)
- **Time-Aware Search**: Dynamic time windows based on user queries
- **Sentiment Analysis**: VADER sentiment scoring on translated news
- **LLM Integration**: Llama 3.3 70B via Groq API for institutional-grade analysis

### 📊 Interactive Dashboard
- **Market Watch Sidebar**: Real-time prices with delta indicators
- **Candlestick Charts**: Interactive Plotly charts with MA overlays
- **Context Sources Panel**: Display retrieved documents with metadata
- **Pipeline Health Monitor**: Real-time consumer status monitoring

### 🗃️ Data Management
- **Vector Database**: ChromaDB for semantic search
- **Data Retention**:  Automatic 30-day cleanup policy
- **Deduplication**: Unique ID-based deduplication for news and metrics

---

## Project Structure

```
Market_Analyze_Data_Stream_Processing/
├── src/
│   ├── config. py                 # Global configuration (Kafka, tickers, paths)
│   ├── ingestion/
│   │   └── producer.py           # Kafka producer (data fetching)
│   ├── processing/
│   │   └── consumer.py           # Kafka consumer (data processing + storage)
│   └── app/
│       ├── main.py               # Streamlit dashboard
│       └── rag_engine.py         # RAG logic + LLM integration
├── data/
│   ├── chromadb/                 # Vector database storage
│   └── history/                  # CSV files for charts
├── docker-compose.yml            # Kafka + Zookeeper infrastructure
├── requirements.txt              # Python dependencies
├── start.sh                      # Linux/macOS startup script
├── start.bat                     # Windows startup script
├── . env                          # Environment variables (API keys)
└── README.md                     # This file
```

---

## Prerequisites

- **Python** 3.10+
- **Docker** & **Docker Compose**
- **Conda** (Miniconda/Anaconda) - recommended for environment management
- **Groq API Key** (free tier available at [console.groq.com](https://console.groq.com))

---

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/mathieuaubert2601/Market_Analyze_Data_Stream_Processing.git
cd Market_Analyze_Data_Stream_Processing
```

### 2. Create Conda Environment

```bash
conda create -n dsp-project python=3.10 -y
conda activate dsp-project
```

### 3. Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Start Kafka Infrastructure

```bash
docker compose up -d
```

Wait for Kafka to be ready (port 9092):

```bash
# Linux/macOS
while ! nc -z localhost 9092; do sleep 1; done && echo "Kafka is ready!"

# Windows PowerShell
while (!(Test-NetConnection localhost -Port 9092).TcpTestSucceeded) { Start-Sleep 1 }; Write-Host "Kafka is ready!"
```

---

## Configuration

Create a `.env` file in the project root:

```env
GROQ_API_KEY=your_groq_api_key_here
```

### Configuration Options (src/config.py)

| Variable | Description | Default |
|----------|-------------|---------|
| `KAFKA_HOST` | Kafka broker address | `localhost:9092` |
| `TICKERS` | List of stock symbols to monitor | CAC 40 top 10 |
| `SLEEP_TIME` | Interval between data fetches (seconds) | `60` |
| `CHROMA_PATH` | ChromaDB storage path | `./data/chromadb` |
| `HISTORY_PATH` | CSV history storage path | `./data/history` |
| `EMBEDDING_MODEL_NAME` | Sentence transformer model | `all-MiniLM-L6-v2` |
| `LLM_MODEL_NAME` | Groq LLM model | `llama-3.3-70b-versatile` |

### Monitored Stocks

| Ticker | Company |
|--------|---------|
| MC. PA | LVMH Moët Hennessy |
| TTE.PA | TotalEnergies |
| OR.PA | L'Oréal |
| RMS.PA | Hermès International |
| SAN.PA | Sanofi |
| SAF.PA | Safran |
| SU.PA | Schneider Electric |
| AI.PA | Air Liquide |
| BNP.PA | BNP Paribas |
| DG.PA | Vinci |

---

## Quick Start

### Option 1: Automated Scripts

**Linux/macOS (WSL):**
```bash
chmod +x start.sh
./start.sh
```

**Windows:**
```batch
start.bat
```

### Option 2: Manual Start

```bash
# Terminal 1: Start Kafka
docker compose up -d

# Terminal 2: Start Producer
conda activate dsp-project
python src/ingestion/producer.py

# Terminal 3: Start Consumer (wait ~10 seconds after producer)
conda activate dsp-project
python src/processing/consumer.py

# Terminal 4: Start Streamlit App (wait ~10 minutes for initial data)
conda activate dsp-project
streamlit run src/app/main. py
```

Access the dashboard at:  **http://localhost:8501**

---

## Usage

### Producer

The producer fetches data every 60 seconds and sends it to Kafka:

```python
# Data sources: 
# 1. Google News RSS - Financial news for each ticker
# 2. Yahoo Finance - Real-time prices, history, company info

# Generated data types:
# • News articles (from Yahoo API + Google RSS)
# • Intraday metrics (10m, 30m, 1h, 3h, 6h momentum)
# • Technical analysis (MA10, MA50, MA200, trend)
# • Daily summaries (OHLCV + daily variation)
# • History data (for candlestick charts)
```

### Consumer

The consumer processes messages from all Kafka topics:

```python
# Processing pipeline:
# 1. Translate news to English (deep-translator)
# 2. Compute sentiment score (VADER)
# 3. Generate embeddings (sentence-transformers)
# 4. Store in ChromaDB with metadata
# 5. Save OHLCV to CSV files
# 6. Enforce 30-day retention policy
```

### Streamlit App

The dashboard provides:

1. **Market Watch Sidebar**
   - Real-time prices with delta percentages
   - Market state indicator (🟢 Open / 🔴 Closed)
   - Last update timestamp

2. **AI Market Analyst**
   - Natural language queries about market trends
   - Automatic ticker detection from context
   - Time-aware responses (real-time vs historical)

3. **Candlestick Charts**
   - Interactive Plotly charts
   - MA50 and MA200 overlays
   - Auto-updates from Kafka stream

4. **Context Sources**
   - Retrieved documents with metadata
   - Sentiment scores
   - Direct links to original sources

### Example Queries

```
• "Why is LVMH dropping today?"
• "What happened to TotalEnergies last week?"
• "Give me a technical analysis of Hermès"
• "What's the sentiment around BNP Paribas?"
• "Compare Air Liquide and Schneider Electric performance"
```

---

## Kafka Topics

| Topic | Description | Data Type |
|-------|-------------|-----------|
| `financial-news` | News articles + Technical analysis | JSON |
| `stock-history` | OHLCV data for charts | JSON |
| `hot-news-events` | Intraday metrics & momentum | JSON |
| `daily-summary` | End-of-day summaries | JSON |

---

## Technical Details

### RAG Pipeline

1. **Query Routing**: LLM-based intent detection extracts: 
   - Target ticker (e.g., "LVMH" → `MC.PA`)
   - Time window (e.g., "last week" → start/end timestamps)
   - Intent type (REAL_TIME vs HISTORICAL)

2. **Semantic Search**: ChromaDB query with:
   - Vector similarity (sentence-transformers embeddings)
   - Time filtering (timestamp range)
   - Ticker filtering (if specified)

3. **Re-Ranking**: Score calculation based on:
   - Semantic similarity (cosine distance)
   - Time decay (for real-time queries)
   - Formula: `score = similarity * 0.6 + time_decay * 0.4`

4. **Context Building**: Top 8 documents formatted with:
   - Document type indicators (📊 metrics, 📈 technical, 📰 news)
   - Timestamps and metadata
   - Sentiment scores

5. **LLM Generation**: Llama 3.3 70B produces:
   - Executive verdict
   - Macro & fundamental drivers
   - Technical analysis
   - Forward outlook

### Sentiment Analysis

- **Model**: VADER (Valence Aware Dictionary for Sentiment Reasoning)
- **Translation**: French → English via deep-translator
- **Score Range**: -1 (negative) to +1 (positive)
- **Thresholds**: > 0.5 (positive), < -0.5 (negative)

### Data Retention

- **ChromaDB**: 30-day retention for daily summaries
- **CSV Files**: Unlimited (manual cleanup required)
- **Deduplication**: ID-based for news, date-based for summaries

---

## Troubleshooting

### Kafka Connection Issues

```bash
# Check if Kafka is running
docker compose ps

# View Kafka logs
docker compose logs kafka

# Restart infrastructure
docker compose down && docker compose up -d
```

### Consumer Not Processing

```bash
# Check consumer heartbeat
cat data/history/consumer_heartbeat.txt

# Verify ChromaDB collection
python -c "import chromadb; c=chromadb.PersistentClient('./data/chromadb'); print(c.list_collections())"
```

### Missing Data in Dashboard

1. Wait 10+ minutes for initial data backfill
2. Check producer logs for API errors
3. Verify `.env` file contains valid GROQ_API_KEY

### Groq API Errors

- Verify API key at [console.groq.com](https://console.groq.com)
- Check rate limits (free tier:  30 requests/minute)
- Monitor for model availability issues

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `kafka-python` | Kafka client |
| `yfinance` | Yahoo Finance API |
| `feedparser` | RSS parsing |
| `chromadb` | Vector database |
| `sentence-transformers` | Text embeddings |
| `streamlit` | Web dashboard |
| `groq` | LLM API client |
| `vaderSentiment` | Sentiment analysis |
| `deep-translator` | Text translation |
| `pandas` | Data manipulation |
| `plotly` | Interactive charts |
| `python-dotenv` | Environment variables |
| `watchdog` | File monitoring |

---

