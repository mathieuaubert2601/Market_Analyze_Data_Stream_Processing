# Market_Analyze_Data_Stream_Processing

Description
-----------
Market_Analyze_Data_Stream_Processing est un projet Python destiné à ingérer, traiter et analyser des flux de données de marché (ticks, cotations, ordres, etc.). Le dépôt contient :
- le code Python dans `src/` (producteurs, consommateurs, traitements),
- un `docker-compose.yml` minimal pour lancer Kafka/Zookeeper localement,
- un `requirements.txt` listant les dépendances Python,
- un dossier `data/` pour exemples / jeux de données.

Ce README explique comment configurer l'environnement, lancer l'infrastructure (Docker), exécuter les composants localement et tester le flux.

Table des matières
------------------
- Prérequis
- Installation
- Configuration (.env)
- Lancer l'infrastructure (Docker Compose)
- Exécuter localement les composants Python
- Exemples rapides (producteur / consommateur)
- Utilisation des dépendances importantes
- Tests & développement
- Dépannage
- Contribution
- Licence & contact

Prérequis
---------
- Git
- Python 3.8+
- pip
- Docker & Docker Compose (recommandé pour reproduire l'infrastructure)
- (Optionnel) virtualenv / venv

Installation
------------
1. Cloner le dépôt
   git clone https://github.com/mathieuaubert2601/Market_Analyze_Data_Stream_Processing.git
   cd Market_Analyze_Data_Stream_Processing

2. (Optionnel) Créer et activer un environnement virtuel Python
   - python3 -m venv .venv
   - source .venv/bin/activate   # macOS / Linux
   - .venv\Scripts\activate      # Windows (PowerShell)

3. Installer les dépendances
   pip install --upgrade pip
   pip install -r requirements.txt

Dépendances principales
-----------------------
Le fichier `requirements.txt` du dépôt contient, entre autres :
- kafka-python — client Kafka en Python
- yfinance — récupération de données de marché (Yahoo Finance)
- chromadb — base de vecteurs locale
- sentence-transformers — embeddings
- streamlit — UI rapide
- groq — client pour Groq API (clé dans .env)
- python-dotenv — chargement des variables d'environnement depuis .env
- pandas, plotly — manipulation et visualisation
- vaderSentiment — analyse de sentiment
- watchdog — surveillance de fichiers

Configuration (.env)
--------------------
Le projet utilise un fichier `.env` pour stocker des variables d'environnement. Un exemple minimal (NE PAS mettre de vraies clés dans le repo) :

GROQ_API_KEY=your_groq_api_key_here
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_TOPIC=market-ticks

Lancer l'infrastructure (Docker Compose)
----------------------------------------
Un `docker-compose.yml` est fourni et contient au minimum Zookeeper et Kafka (Confluent) exposant :
- Zookeeper : 2181
- Kafka : 9092

Démarrer les services :
- docker compose up --build

Démarrer en arrière-plan :
- docker compose up -d

Voir les logs :
- docker compose logs -f

Arrêter et supprimer :
- docker compose down

Important :
- Le `docker-compose.yml` configure `KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092`. Si vous exécutez depuis une VM ou un container différent, adaptez la valeur `KAFKA_ADVERTISED_LISTENERS` afin que vos clients Python puissent se connecter correctement.

Exécuter localement les composants Python
----------------------------------------
1. Vérifiez que Kafka est disponible (docker compose up) ou utilisez un broker Kafka externe.
2. Installez les dépendances (voir Installation).
3. Parcourez `src/` pour trouver les scripts d'entrée (producteurs, consommateurs, stream jobs). Les noms exacts des scripts peuvent varier ; si vous ne les trouvez pas, cherchez les README/entrypoints dans `src/`.

Commandes génériques :
- python src/<nom_du_script>.py --help
- python -m src.<package>    # si `src` est un package

Utilisation des composants listés dans requirements
-------------------------------------------------
- yfinance : récupération de données historiques/temps réel (ex. pour backfill).
- sentence-transformers + chromadb : construire / indexer embeddings et faire des recherches sémantiques.
- streamlit : lancer une interface rapide : streamlit run path/to/app.py
- vaderSentiment : analyse de sentiment sur textes (news, tweets).
- watchdog : surveiller des répertoires / fichiers pour déclencher ingestion automatique.
