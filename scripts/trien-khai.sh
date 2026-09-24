#!/usr/bin/env bash
# =============================================================================
#  Read Mail Bot — DAY LEN SERVER (chay tren may cua ban)
#
#    bash scripts/trien-khai.sh              day ma nguon + build lai + khoi dong
#    bash scripts/trien-khai.sh --chi-day    chi dong bo file, khong dung lai app
#    bash scripts/trien-khai.sh --no-cache   build lai tu dau
#    bash scripts/trien-khai.sh --nhat-ky    xem log truc tiep tren server
#    bash scripts/trien-khai.sh --trang-thai xem tinh trang container
#    bash scripts/trien-khai.sh --dung       tat toan bo
#
#  Lan dau chay se tao file deploy.conf va hoi thong tin server. File do khong
#  bao gio bi commit (da co trong .gitignore).
#
#  Viet theo bash 3.2 de chay duoc tren bash mac dinh cua macOS.
# =============================================================================
set -euo pipefail

THU_MUC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CAU_HINH="$THU_MUC/deploy.conf"

do_(){ printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok_(){ printf '    \033[32mv\033[0m %s\n' "$*"; }
canh_(){ printf '    \033[33m!\033[0m %s\n' "$*"; }
loi_(){ printf '\n\033[1;31mLOI: %s\033[0m\n' "$*" >&2; exit 1; }

VIEC="day"
CO_SERVER=""
for a in "$@"; do
  case "$a" in
    --chi-day)    VIEC="chi-day" ;;
    --rebuild)    CO_SERVER="$CO_SERVER --rebuild" ;;
    --no-cache)   CO_SERVER="$CO_SERVER --no-cache" ;;
    --nhat-ky)    VIEC="nhat-ky" ;;
    --trang-thai) VIEC="trang-thai" ;;
    --dung)       VIEC="dung" ;;
    -h|--help)    sed -n '2,16p' "$0"; exit 0 ;;
    *) loi_ "Co la: $a" ;;
  esac
done

# -----------------------------------------------------------------------------
do_ "Kiem tra may cua ban"

command -v rsync >/dev/null || loi_ "Thieu rsync. Cai: brew install rsync (macOS) hoac apt install rsync (Linux)"
command -v ssh   >/dev/null || loi_ "Thieu ssh"
ok_ "rsync: $(rsync --version 2>/dev/null | head -1)"

# -----------------------------------------------------------------------------
if [ ! -f "$CAU_HINH" ]; then
  do_ "Lan dau - tao deploy.conf"
  [ -t 0 ] || loi_ "Chua co deploy.conf. Chay lai trong terminal de nhap thong tin."

  read -rp "    Dia chi server (IP hoac ten mien): " _HOST
  read -rp "    Tai khoan ssh [root]: " _USER; _USER="${_USER:-root}"
  read -rp "    Cong ssh [22]: " _PORT; _PORT="${_PORT:-22}"
  read -rp "    Thu muc tren server [/www/wwwroot/read-mail-bot]: " _DIR
  _DIR="${_DIR:-/www/wwwroot/read-mail-bot}"

  [ -z "$_HOST" ] && loi_ "Chua nhap dia chi server"

  umask 077
  cat > "$CAU_HINH" <<CONF
# Thong tin server. File nay KHONG duoc commit (da nam trong .gitignore).
SSH_HOST="$_HOST"
SSH_USER="$_USER"
SSH_PORT="$_PORT"
REMOTE_DIR="$_DIR"
CONF
  umask 022
  chmod 600 "$CAU_HINH"
  ok_ "Da luu $CAU_HINH"
fi

# shellcheck disable=SC1090
. "$CAU_HINH"
: "${SSH_HOST:?thieu SSH_HOST trong deploy.conf}"
: "${SSH_USER:=root}"
: "${SSH_PORT:=22}"
: "${REMOTE_DIR:=/www/wwwroot/read-mail-bot}"

# An toan: khong cho rsync --delete vao nhung thu muc he thong
case "${REMOTE_DIR%/}" in
  ''|'/'|'/www'|'/www/wwwroot'|'/home'|'/root'|'/usr'|'/var'|'/etc'|'/opt')
    loi_ "REMOTE_DIR trong deploy.conf la '$REMOTE_DIR' - qua rong, tu choi dong bo." ;;
esac
case "$REMOTE_DIR" in
  /*) ;;
  *) loi_ "REMOTE_DIR phai la duong dan tuyet doi, dang la '$REMOTE_DIR'" ;;
esac

# Dung chung MOT ket noi ssh cho ca rsync lan cac lenh sau
DUONG_OD="${TMPDIR:-/tmp}/rmbot-ssh-%r-%h-%p"
OD_SSH="-o ControlMaster=auto -o ControlPath=$DUONG_OD -o ControlPersist=10m"

SSH="ssh -p $SSH_PORT -o ConnectTimeout=10 $OD_SSH $SSH_USER@$SSH_HOST"

# -----------------------------------------------------------------------------
do_ "Ket noi server"
# shellcheck disable=SC2086
if $SSH -o BatchMode=yes "echo ok" >/dev/null 2>&1; then
  ok_ "$SSH_USER@$SSH_HOST:$SSH_PORT (dang nhap bang khoa)"
else
  canh_ "Khong dang nhap duoc bang khoa - se hoi mat khau"
  echo "      Muon khoi phai go mat khau: ssh-copy-id -p $SSH_PORT $SSH_USER@$SSH_HOST"
  # shellcheck disable=SC2086
  $SSH "echo ok" >/dev/null || loi_ "Khong ket noi duoc toi $SSH_USER@$SSH_HOST:$SSH_PORT"
  ok_ "Da ket noi"
fi

DC_REMOTE="cd $REMOTE_DIR && docker compose -f docker-compose.prod.yml --env-file .env"

case "$VIEC" in
  nhat-ky)    exec $SSH -t "$DC_REMOTE logs -f --tail 100" ;;
  trang-thai) exec $SSH -t "$DC_REMOTE ps" ;;
  dung)       exec $SSH -t "$DC_REMOTE down" ;;
esac

# -----------------------------------------------------------------------------
do_ "Dong bo ma nguon -> $REMOTE_DIR"

LOAI_TRU="$THU_MUC/scripts/loai-tru-dong-bo.txt"
[ -f "$LOAI_TRU" ] || loi_ "Khong thay $LOAI_TRU"

# shellcheck disable=SC2086
$SSH "mkdir -p $REMOTE_DIR"

# shellcheck disable=SC2086
rsync -az --delete \
  --exclude-from="$LOAI_TRU" \
  -e "ssh -p $SSH_PORT $OD_SSH" \
  "$THU_MUC/" "$SSH_USER@$SSH_HOST:$REMOTE_DIR/"

# Dem file nguon hai ben de dam bao dong bo day du
DEM='find core bot features web templates -path "*/__pycache__" -prune -o -type f \( -name "*.py" -o -name "*.html" -o -name "*.css" -o -name "*.txt" \) -print'
SO_MAY=$(cd "$THU_MUC" && eval "$DEM" | wc -l | tr -d " ")
# shellcheck disable=SC2086
SO_SERVER=$($SSH "cd $REMOTE_DIR && $DEM" | wc -l | tr -d " ")
if [ "$SO_MAY" = "$SO_SERVER" ]; then
  ok_ "Da dong bo ($SO_MAY file nguon, khop hai ben)"
else
  canh_ "May ban co $SO_MAY file nguon, server co $SO_SERVER."
  echo "      Co the mot mau loai tru dang an di file. Kiem tra scripts/loai-tru-dong-bo.txt"
fi

if [ "$VIEC" = "chi-day" ]; then
  echo
  ok_ "Xong (chi dong bo file, app tren server van chay ban cu)"
  echo "    Muon ap dung: bash scripts/trien-khai.sh"
  exit 0
fi

# -----------------------------------------------------------------------------
do_ "Thiet lap va khoi dong tren server"
echo "    (lan dau se cai Docker + build — co the mat 5-10 phut)"
echo

# shellcheck disable=SC2086
$SSH -t "bash $REMOTE_DIR/scripts/server/thiet-lap.sh${CO_SERVER}"

# -----------------------------------------------------------------------------
do_ "Kiem tra tu ben ngoai"
ADMIN_PORT_CHECK=$($SSH "grep '^ADMIN_PORT=' $REMOTE_DIR/.env 2>/dev/null | cut -d= -f2" || echo "8085")
ADMIN_PORT_CHECK="${ADMIN_PORT_CHECK:-8085}"
MA=$(curl -fsS -o /dev/null -w '%{http_code}' --max-time 10 "http://$SSH_HOST:$ADMIN_PORT_CHECK/admin/login/" 2>/dev/null || echo "-")
if [ "$MA" = "200" ] || [ "$MA" = "302" ]; then
  ok_ "http://$SSH_HOST:$ADMIN_PORT_CHECK/admin/ tra ve $MA"
else
  canh_ "Admin panel chua goi duoc tu ben ngoai (ma: $MA)"
  echo "      Binh thuong neu firewall chua mo port $ADMIN_PORT_CHECK."
  echo "      Hoac ban dang dung reverse proxy (nginx)."
fi

echo
printf '\033[1;32mXong.\033[0m  Xem log:  bash scripts/trien-khai.sh --nhat-ky\n'
printf '       Admin:  http://%s:%s/admin/\n' "$SSH_HOST" "$ADMIN_PORT_CHECK"
