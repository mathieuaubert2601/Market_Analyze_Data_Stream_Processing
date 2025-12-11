@echo off
echo ===================================================
echo 🚀 Lancement Financial RAG (Env: dsp-project)
echo ===================================================

:: 1. Démarrer l'infrastructure (Kafka)
echo.
echo 🐳 Vérification de Docker...
docker-compose up -d

echo ⏳ Attente de l'initialisation (10 secondes)...
timeout /t 10 /nobreak >nul

:: 2. Lancer le Producer (Avec activation Conda)
echo.
echo 📤 Lancement du Producer...
start "PRODUCER (dsp-project)" cmd /k "conda activate dsp-project && python src/ingestion/producer.py"
echo ⏳ Attente de l'initialisation (10 secondes)...
timeout /t 10 /nobreak >nul
:: 3. Lancer le Consumer (Avec activation Conda)
echo.
echo 📥 Lancement du Consumer...
start "CONSUMER (dsp-project)" cmd /k "conda activate dsp-project && python src/processing/consumer.py"
echo ⏳ Attente de l'initialisation (10 secondes)...
timeout /t 10 /nobreak >nul
:: 4. Lancer l'App (Avec activation Conda)
echo.
echo 🌐 Lancement de Streamlit...
start "STREAMLIT (dsp-project)" cmd /k "conda activate dsp-project && streamlit run src/app/main.py"
echo ⏳ Attente de l'initialisation (10 secondes)...
timeout /t 10 /nobreak >nul
echo.
echo ✅ TOUT EST LANCÉ ! 
echo.