#!/usr/bin/env bash
# =============================================================================
#  Docker entrypoint — Read Mail Bot
#
#  1. Doi PostgreSQL san sang
#  2. Chay Django migrations
#  3. Collect static files
#  4. Khoi dong app (run.py)
#
#  Tai khoan admin duoc tao qua trang /setup/ khi truy cap lan dau.
# =============================================================================
set -e

echo "[entrypoint] Doi PostgreSQL..."
for i in $(seq 1 30); do
    if python -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.connect(('${DB_HOST:-db}', ${DB_PORT:-5432}))
    s.close()
    exit(0)
except:
    exit(1)
" 2>/dev/null; then
        echo "[entrypoint] PostgreSQL da san sang."
        break
    fi
    if [ "$i" = "30" ]; then
        echo "[entrypoint] CANH BAO: Khong ket noi duoc PostgreSQL sau 30 giay."
    fi
    sleep 1
done

echo "[entrypoint] Chay migrations..."
python manage.py migrate --noinput

echo "[entrypoint] Collect static files..."
python manage.py collectstatic --noinput 2>/dev/null || true

echo "[entrypoint] Khoi dong ung dung..."
exec python run.py
