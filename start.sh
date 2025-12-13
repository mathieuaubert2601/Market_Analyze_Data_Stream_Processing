#!/bin/bash
set -e

ENV_NAME="dsp-project"
CONDA_DIR="$HOME/miniconda3"
REQ_FILE="requirements.txt"

echo "==================================================="
echo "🚀 Lancement Financial RAG (Env: $ENV_NAME)"
echo "==================================================="

# ---------------------------------------------------
# 1. Docker / Kafka
# ---------------------------------------------------
echo ""
echo "🐳 Démarrage de l'infrastructure Docker..."
docker compose up -d

echo "⏳ Waiting for Kafka to be ready..."
while ! nc -z localhost 9092; do
  sleep 1
done
echo "✅ Kafka is up!"
sleep 5

# ---------------------------------------------------
# 2. Vérification Conda
# ---------------------------------------------------
echo ""
echo "🔍 Vérification Conda..."

if [ ! -f "$CONDA_DIR/etc/profile.d/conda.sh" ]; then
  echo "❌ Conda introuvable dans $CONDA_DIR"
  echo "➡️  Installe Miniconda sous WSL avant de continuer"
  exit 1
fi

source "$CONDA_DIR/etc/profile.d/conda.sh"

# ---------------------------------------------------
# 3. Création de l'environnement si nécessaire
# ---------------------------------------------------
if conda env list | grep -q "^$ENV_NAME "; then
  echo "✅ Environnement $ENV_NAME trouvé"
else
  echo "🆕 Création de l'environnement $ENV_NAME"
  conda create -n "$ENV_NAME" python=3.10 -y
fi

conda activate "$ENV_NAME"

# ---------------------------------------------------
# 4. Installation des dépendances
# ---------------------------------------------------
echo ""
echo "📦 Installation des dépendances Python..."

if [ -f "$REQ_FILE" ]; then
  pip install --upgrade pip
  pip install -r "$REQ_FILE"
else
  echo "⚠️  $REQ_FILE introuvable, dépendances non installées"
fi

# ---------------------------------------------------
# 5. Lancer Producer
# ---------------------------------------------------
echo ""
echo "📤 Lancement du Producer..."
python src/ingestion/producer.py &
PRODUCER_PID=$!
sleep 5

# ---------------------------------------------------
# 6. Lancer Consumer
# ---------------------------------------------------
echo ""
echo "📥 Lancement du Consumer..."
python src/processing/consumer.py &
CONSUMER_PID=$!
sleep 5

# ---------------------------------------------------
# 7. Lancer Streamlit (foreground)
# ---------------------------------------------------
echo ""
echo "🌐 Lancement de Streamlit..."
streamlit run src/app/main.py \
  --server.address 0.0.0.0 \
  --server.port 8501