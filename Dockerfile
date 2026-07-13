FROM python:3.11-slim

WORKDIR /app

# postgresql-client cho pg_dump/pg_restore (GOV-002 backup tự động)
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY telegram-bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot code + scripts (t2_arima/t2_xgboost/t2_ensemble/backup_db — bug tìm thấy khi thêm
# GOV-002: scripts/ CHƯA TỪNG được copy vào image trước đây, nghĩa là mọi _run_t2_script()
# gọi từ bot.py (job_t2_predict/job_t2_retrain/job_t2_reweight) luôn fail "không tìm thấy"
# trên Railway — chỉ hoạt động khi test local. Sửa luôn ở đây.
COPY telegram-bot/ ./telegram-bot/
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
