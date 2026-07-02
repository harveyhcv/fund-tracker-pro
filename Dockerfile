FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY telegram-bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot code
COPY telegram-bot/ ./telegram-bot/

# Copy scripts (fetch_gold.py, etc.) — cần thiết cho job_morning
COPY scripts/ ./scripts/

# /data = persistent volume (mount qua Railway Volumes UI)
RUN mkdir -p /data

WORKDIR /app/telegram-bot

# Secrets qua ENV — không hardcode trong image
ENV DATA_DIR=/data \
    BOT_TOKEN="" \
    ADMIN_TELEGRAM_ID="" \
    MORNING_TIME="08:00" \
    EVENING_TIME="17:30" \
    SIGNAL_INTERVAL="60"

CMD ["python", "-u", "bot.py"]
