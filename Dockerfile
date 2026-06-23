FROM python:3.11-slim

# OS deps: tesseract, fonts (Liberation = Arial-metric-compatible), libs for OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        libgl1 \
        libglib2.0-0 \
        fonts-liberation \
        fonts-dejavu \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (cache-friendly)
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
        "python-telegram-bot==21.4" \
        "PyMuPDF==1.27.2" \
        "pillow>=10.0" \
        "pytesseract>=0.3.10" \
        "anthropic>=0.39.0" \
        "opencv-python-headless>=4.9.0" \
        "numpy>=1.26" \
        "pydantic>=2.5" \
        "pydantic-settings>=2.1" \
        "python-dotenv>=1.0" \
        "tenacity>=8.2"

COPY bol_bot/ ./bol_bot/

# Persistent dirs
RUN mkdir -p /app/data /app/logs
VOLUME ["/app/data", "/app/logs"]

ENV PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/bol_bot.db \
    CACHE_DIR=/app/data/cache \
    LOG_FILE=/app/logs/bol_bot.log

CMD ["python", "-m", "bol_bot.main"]
