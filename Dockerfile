FROM python:3.12-slim

# Tao thu muc lam viec
WORKDIR /app

# Cai dat cac thu vien he thong can thiet (psycopg2 can libpq)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Sao chep va cai dat cac thu vien Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Sao chep ma nguon
COPY . .

# Thu thap static files cua Django admin
RUN DJANGO_SECRET_KEY=build-only \
    DB_HOST=localhost \
    python manage.py collectstatic --noinput 2>/dev/null || true

# Mo cong cho trang quan tri
EXPOSE 8080

# Script khoi dong: migrate + chay app
COPY scripts/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
