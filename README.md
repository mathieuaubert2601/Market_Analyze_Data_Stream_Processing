# Market_Analyze_Data_Stream_Processing

Description
-----------
Market_Analyze_Data_Stream_Processing is a Python project designed to ingest, process, and analyze market data streams (ticks, quotes, orders, etc.). The repository includes:
- Python code in `src/` (producers, consumers, processing jobs)
- a minimal `docker-compose.yml` to launch Kafka/Zookeeper locally
- a `requirements.txt` listing Python dependencies
- a `data/` folder for sample datasets

This README explains how to set up the environment, launch the infrastructure (Docker), run components locally, and test the data flow.

Table of Contents
------------------
- Prerequisites
- Installation
- Configuration (.env)
- Launching Infrastructure (Docker Compose)
- Running Python Components Locally
- Quick Examples (Producer / Consumer)
- Usage of Main Dependencies
- Testing & Development
- Troubleshooting
- Contribution
- License & Contact

Prerequisites
-------------
- Git
- Python 3.8+
- pip
- Docker & Docker Compose (recommended for infrastructure)
- (Optional) virtualenv / venv

Installation
------------
1. Clone the repository:
   ```bash
   git clone https://github.com/mathieuaubert2601/Market_Analyze_Data_Stream_Processing.git
   cd Market_Analyze_Data_Stream_Processing
   ```

2. (Optional) Create and activate a Python virtual environment:
   - macOS / Linux:
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```
   - Windows (PowerShell):
     ```powershell
     python -m venv .venv
     .venv\Scripts\activate
     ```

3. Install dependencies:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

Main Dependencies
-----------------
The `requirements.txt` includes, among others:
- kafka-python — Kafka client for Python
- yfinance — market data retrieval (Yahoo Finance)
- chromadb — local vector database
- sentence-transformers — embeddings
- streamlit — rapid UI
- groq — Groq API client (key in .env)
- python-dotenv — environment variable loading from .env
- pandas, plotly — data manipulation and visualization
- vaderSentiment — sentiment analysis
- watchdog — file monitoring

Configuration (.env)
--------------------
The project uses a `.env` file for environment variables. Minimal example (DO NOT commit real keys):

```
GROQ_API_KEY=your_groq_api_key_here
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_TOPIC=market-ticks
```

Launching Infrastructure (Docker Compose)
-----------------------------------------
A `docker-compose.yml` is provided with at least Zookeeper and Kafka (Confluent), exposing:
- Zookeeper: 2181
- Kafka: 9092

Start services:
```bash
docker compose up --build
```

Start in background:
```bash
docker compose up -d
```

View logs:
```bash
docker compose logs -f
```

Stop and remove:
```bash
docker compose down
```

Important:
- The `docker-compose.yml` sets `KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092`. If running from a VM or different container, adjust `KAFKA_ADVERTISED_LISTENERS` so Python clients can connect.

Running Python Components Locally
---------------------------------
1. Ensure Kafka is available (`docker compose up`) or use an external Kafka broker.
2. Install dependencies (see Installation).
3. Browse `src/` for entry scripts (producers, consumers, stream jobs). Script names may vary; check for README/entrypoints in `src/` if needed.

Usage of Main Dependencies
--------------------------
- yfinance: fetch historical/real-time market data (e.g., for backfill)
- sentence-transformers + chromadb: build/index embeddings and perform semantic search
- streamlit: launch a quick UI: `streamlit run path/to/app.py`
- vaderSentiment: sentiment analysis on text (news, tweets)
- watchdog: monitor directories/files to trigger automatic ingestion

---