FROM python:3.11-slim-bookworm

WORKDIR /app

# postgresql-client cho pg_dump/pg_restore (GOV-002 backup tự động).
# GOV-011-part3 (2026-07-16): Railway Postgres đã lên bản 18 (image
# ghcr.io/railwayapp-templates/postgres-ssl:18), nhưng gói postgresql-client mặc định
# của Debian base image chỉ có v17 — lệch major version khiến pg_dump từ chối chạy
# ("aborting because of server version mismatch"), backup tự động fail âm thầm mỗi
# đêm. Cài trực tiếp từ repo chính thức PGDG để lấy đúng postgresql-client-18, pin
# base image về "bookworm" tường minh (PGDG hỗ trợ ổn định) thay vì để trôi theo
# codename Debian mặc định của image gốc.
RUN apt-get update && apt-get install -y --no-install-recommends wget gnupg ca-certificates \
    && wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/postgresql.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/postgresql.gpg] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-18 \
    && apt-get purge -y wget gnupg \
    && apt-get autoremove -y \
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

CMD ["sh", "-c", "python scripts/emergency_cleanup.py; exec python -u bot.py"]
