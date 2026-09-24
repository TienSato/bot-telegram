#!/usr/bin/env bash
# =============================================================================
#  Cai dat nginx reverse proxy cho domain cua ban.
#
#  DOMAIN doc tu file .env (khong hardcode trong source code).
#  Script nay chay TREN SERVER. Goi tu trien-khai.sh hoac chay tay:
#    bash scripts/server/cai-nginx.sh
#    DOMAIN=vi-du.com bash scripts/server/cai-nginx.sh
# =============================================================================
set -euo pipefail

THU_MUC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

do_(){ printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok_(){ printf '    \033[32mv\033[0m %s\n' "$*"; }
canh_(){ printf '    \033[33m!\033[0m %s\n' "$*"; }
loi_(){ printf '\n\033[1;31mLOI: %s\033[0m\n' "$*" >&2; exit 1; }

# Doc DOMAIN va ADMIN_PORT tu .env (uu tien bien moi truong neu da dat)
ENV_FILE="$THU_MUC/.env"
if [ -f "$ENV_FILE" ]; then
  [ -z "${DOMAIN:-}" ] && DOMAIN=$(grep '^DOMAIN=' "$ENV_FILE" | cut -d= -f2- | tr -d '"' | tr -d "'")
  ADMIN_PORT=$(grep '^ADMIN_PORT=' "$ENV_FILE" | cut -d= -f2)
fi
ADMIN_PORT="${ADMIN_PORT:-8085}"
DOMAIN="${DOMAIN:-}"

if [ -z "$DOMAIN" ]; then
  loi_ "Chua co DOMAIN. Them dong 'DOMAIN=ten-mien-cua-ban.com' vao file .env,
       hoac chay: DOMAIN=ten-mien.com bash scripts/server/cai-nginx.sh"
fi

# -- Kiem tra va cai nginx --
do_ "Kiem tra nginx"
if ! command -v nginx >/dev/null 2>&1; then
  do_ "Cai nginx..."
  apt-get update -qq && apt-get install -y -qq nginx
fi
ok_ "nginx: $(nginx -v 2>&1)"

# -- Copy cau hinh --
do_ "Cau hinh nginx cho $DOMAIN"

NGINX_CONF="/etc/nginx/sites-available/$DOMAIN"
NGINX_LINK="/etc/nginx/sites-enabled/$DOMAIN"

if [ -f "$NGINX_CONF" ]; then
  canh_ "File $NGINX_CONF da ton tai. Giu nguyen."
  canh_ "Neu muon cap nhat port: sua proxy_pass trong $NGINX_CONF"
else
  sed -e "s/__ADMIN_PORT__/$ADMIN_PORT/g" \
      -e "s/__DOMAIN__/$DOMAIN/g" \
      -e "s#__PROJECT_DIR__#$THU_MUC#g" \
      "$THU_MUC/nginx.conf.mau" > "$NGINX_CONF"
  ok_ "Da tao $NGINX_CONF (domain $DOMAIN -> 127.0.0.1:$ADMIN_PORT)"
fi

if [ ! -L "$NGINX_LINK" ]; then
  ln -s "$NGINX_CONF" "$NGINX_LINK"
  ok_ "Da tao symlink $NGINX_LINK"
else
  ok_ "Symlink da ton tai"
fi

# -- Test va reload --
do_ "Test va reload nginx"
nginx -t || loi_ "Cau hinh nginx bi loi. Kiem tra $NGINX_CONF"
systemctl reload nginx
ok_ "Nginx da reload"

# -- Certbot (tuy chon) --
do_ "SSL Certificate"
if command -v certbot >/dev/null 2>&1; then
  echo "    Chay certbot de cai SSL:"
  echo "      certbot --nginx -d $DOMAIN"
  echo "    Hoac tu dong (khong tuong tac):"
  echo "      certbot --nginx -d $DOMAIN --non-interactive --agree-tos -m your@email.com"
else
  canh_ "Chua cai certbot. Cai: apt install certbot python3-certbot-nginx"
  echo "    Sau do: certbot --nginx -d $DOMAIN"
fi

echo
ok_ "Xong. Truy cap: http://$DOMAIN/admin/"
