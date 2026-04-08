FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_DATA_DIR=/app/data \
    PYPPETEER_HOME=/app/data/pyppeteer

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libc6 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libexpat1 \
    libfontconfig1 \
    libgbm1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libstdc++6 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    wget \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Pyppeteer 2.0.0 declara urllib3<2, mas o runtime foi validado com urllib3 2.6.3
# para remover CVEs reportadas no urllib3 1.26.20. Migração futura recomendada: Playwright.
RUN python -m pip install --no-cache-dir --upgrade pip==26.0.1 \
    && pip install --no-cache-dir -r requirements.txt \
    && pyppeteer-install \
    && pip install --no-cache-dir --upgrade urllib3==2.6.3

COPY . .

RUN mkdir -p /app/data && useradd -ms /bin/bash appuser && chown -R appuser:appuser /app

USER appuser

EXPOSE 5000

CMD ["gunicorn", "--workers", "1", "--threads", "2", "--timeout", "600", "--graceful-timeout", "60", "-b", "0.0.0.0:5000", "app:app"]
