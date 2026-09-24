#!/usr/bin/env bash
# =============================================================================
#  Read Mail Bot — Thiet lap va khoi dong tren server
#
#  Script nay duoc goi TU TREN SERVER boi trien-khai.sh sau khi rsync xong.
#  Khong nen chay tay — hay dung:  bash scripts/trien-khai.sh
#
#    --rebuild    build lai image Docker (mac dinh)
#    --no-cache   build lai tu dau, khong dung cache
# =============================================================================
set -euo pipefail

THU_MUC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$THU_MUC"

do_(){ printf '\n\033[1;36m    [server] %s\033[0m\n' "$*"; }
ok_(){ printf '    \033[32mv\033[0m %s\n' "$*"; }
canh_(){ printf '    \033[33m!\033[0m %s\n' "$*"; }
loi_(){ printf '\n\033[1;31m    LOI: %s\033[0m\n' "$*" >&2; exit 1; }

# Ham sinh mat khau ngau nhien
sinh_mk(){
  python3 -c "import secrets; print(secrets.token_urlsafe($1))" 2>/dev/null \
    || head -c "$1" /dev/urandom | base64 | tr -d '\n/+=' | head -c "$1"
}
# Ham tim cong trong (bat dau tu 8080, bo qua cong da dung)
tim_cong_trong(){
  local bat_dau="${1:-8080}"
  local ket_thuc="${2:-9000}"
  local cong
  for cong in $(seq "$bat_dau" "$ket_thuc"); do
    if ! ss -tlnp 2>/dev/null | grep -qE ":${cong}\b"; then
      echo "$cong"
      return 0
    fi
  done
  # Khong tim thay cong trong — tra ve mac dinh
  echo "$bat_dau"
  return 1
}


BUILD_OPT=""
for a in "$@"; do
  case "$a" in
    --no-cache) BUILD_OPT="--no-cache" ;;
    --rebuild)  ;;
    *) ;;
  esac
done

# =============================================================================
do_ "Kiem tra moi truong server"
# =============================================================================

# -- Docker --
if ! command -v docker >/dev/null 2>&1; then
  do_ "Cai Docker..."
  curl -fsSL https://get.docker.com | sh
  systemctl enable docker
  systemctl start docker
fi
ok_ "Docker: $(docker --version)"

# docker compose
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  do_ "Cai docker compose plugin..."
  apt-get update -qq && apt-get install -y -qq docker-compose-plugin 2>/dev/null \
    || loi_ "Khong cai duoc docker compose. Thu: apt install docker-compose-plugin"
  DC="docker compose"
fi
ok_ "$DC version: $($DC version --short 2>/dev/null || $DC version)"

# -- Nginx --
if command -v nginx >/dev/null 2>&1; then
  ok_ "nginx: $(nginx -v 2>&1 | head -1)"
else
  canh_ "Chua cai nginx. Neu muon dung domain: apt install nginx"
fi

# -- Cac cong cu khac --
for cmd in curl git; do
  if command -v "$cmd" >/dev/null 2>&1; then
    ok_ "$cmd: co"
  else
    canh_ "Thieu $cmd — khong bat buoc nhung nen cai"
  fi
done

# =============================================================================
do_ "Kiem tra .env va cong"
# =============================================================================

# Dung container cu (neu co) de giai phong port truoc khi do
if [ -f docker-compose.prod.yml ] && [ -f .env ]; then
  $DC -f docker-compose.prod.yml --env-file .env down 2>/dev/null &&     ok_ "Da dung container cu" || true
fi

if [ ! -f .env ]; then
  _SECRET=$(sinh_mk 50)
  _DB_PASS=$(sinh_mk 24)

  # Tu dong tim cong trong tren server
  if _CONG=$(tim_cong_trong 8080 9000); then
    ok_ "Tim thay cong trong: $_CONG"
  else
    canh_ "Khong tim thay cong trong 8080-9000, dung $_CONG (co the bi trung)"
  fi

  # Domain: lay tu bien moi truong DOMAIN neu co (vi du: DOMAIN=abc.com bash ...)
  _DOMAIN="${DOMAIN:-}"
  if [ -n "$_DOMAIN" ]; then
    _CSRF="https://$_DOMAIN"
  else
    _CSRF=""
    canh_ "Chua dat DOMAIN. Nho sua DOMAIN + CSRF_TRUSTED_ORIGINS trong .env sau."
  fi

  cat > .env <<ENVFILE
# === Tu dong sinh boi thiet-lap.sh — $(date +%Y-%m-%d) ===
# Bot va tai khoan admin: cau hinh qua trang web (/setup/ roi /admin/).

# Ten mien cong khai cua ban (dung cho nginx + webview xem mail)
DOMAIN=$_DOMAIN

DJANGO_SECRET_KEY=$_SECRET
DEBUG=0
ALLOWED_HOSTS=*
CSRF_TRUSTED_ORIGINS=$_CSRF

# Dia chi web cong khai — dung cho nut mo webview xem mail trong Telegram.
# De trong thi vao Admin -> Bot Settings -> PUBLIC_BASE_URL de dat.
PUBLIC_BASE_URL=$_CSRF

DB_NAME=readmailbot
DB_USER=readmailbot
DB_PASSWORD=$_DB_PASS
DB_HOST=db
DB_PORT=5432

ADMIN_PORT=$_CONG
ENVFILE

  chmod 600 .env
  ok_ "Da tao .env (SECRET_KEY, DB_PASSWORD sinh ngau nhien, ADMIN_PORT=$_CONG)"
else
  ok_ ".env da ton tai"
  # Kiem tra port hien tai co bi chiem khong
  _CONG_CU=$(grep '^ADMIN_PORT=' .env | cut -d= -f2)
  _CONG_CU="${_CONG_CU:-8085}"
  if ss -tlnp 2>/dev/null | grep -qE ":${_CONG_CU}\b"; then
    canh_ "ADMIN_PORT=$_CONG_CU dang bi chiem boi app khac"
    if _CONG_MOI=$(tim_cong_trong 8080 9000); then
      sed -i "s/^ADMIN_PORT=.*/ADMIN_PORT=$_CONG_MOI/" .env
      ok_ "Da doi ADMIN_PORT: $_CONG_CU -> $_CONG_MOI"
    else
      canh_ "Khong tim thay cong trong 8080-9000!"
    fi
  else
    ok_ "ADMIN_PORT=$_CONG_CU — cong trong, OK"
  fi
fi

# =============================================================================
do_ "Build va khoi dong"
# =============================================================================

# shellcheck disable=SC2086
$DC -f docker-compose.prod.yml --env-file .env build $BUILD_OPT
ok_ "Build xong"

$DC -f docker-compose.prod.yml --env-file .env up -d
ok_ "Container dang chay"

echo
$DC -f docker-compose.prod.yml --env-file .env ps

echo
printf '\033[1;32mXong.\033[0m\n'
echo "  Truy cap trang web de tao tai khoan admin va thiet lap bot."
echo "  Cai nginx:  bash scripts/server/cai-nginx.sh   (doc DOMAIN tu .env)"
echo "  Cai SSL:    certbot --nginx -d \$DOMAIN"
