# Immagine dell'API di Radar Gare IT (T0.7).
# DA VERIFICARE: la build non è stata provata (Docker non installato sulla macchina di sviluppo).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dipendenze e codice. Si esegue dalla cartella /app, quindi `backend` è importato dai sorgenti.
COPY pyproject.toml README.md ./
COPY backend ./backend
RUN pip install .

# Utente non privilegiato; /data contiene i documenti scaricati (volume nel compose).
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data/documents \
    && chown -R app:app /data
USER app

EXPOSE 8000

# Il database si configura con DATABASE_URL. Le migrazioni si applicano all'avvio nel compose.
CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
