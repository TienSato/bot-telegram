# X-Bot

Nền tảng bot Telegram **đa bot + đa chức năng**, quản lý qua trang admin Django.

Mỗi chức năng là một **plugin nằm trong thư mục riêng** (`features/<tên>/`). Bạn tạo
nhiều bot Telegram, rồi gán cho từng bot những chức năng khác nhau ngay trên admin —
bot tự khởi động lại, không cần restart server.

Chức năng có sẵn: **readmail** — đọc mail Hotmail/Outlook qua Microsoft Graph API.

---

## Tính năng

**Nền tảng**
- Quản lý nhiều bot trong một hệ thống; mỗi bot gán chức năng riêng (bảng `BotFeature`).
- **Tự động nạp bot**: thêm/sửa/tắt bot trên admin → bot tự khởi động/dừng sau ~10s.
- **Nút kiểm thử bot** trong admin (gọi `getMe` của Telegram, hiện kết quả ngay).
- **Phân quyền theo từng user × từng chức năng**, kèm màn hình **ma trận quyền**.
- Hoạt động cả chat riêng lẫn **nhóm Telegram**.
- **Tự dọn tin nhắn**: xoá tin lệnh của user, xoá tin chứa thông tin tài khoản,
  phản hồi lệnh thông tin tự biến mất trong nhóm → chat không bị spam.

**Chức năng readmail**
- Thêm tài khoản mail bằng `refresh_token` + `client_id` (Microsoft Graph API).
- Đọc mail, tự tách **mã OTP/xác nhận**, xem chi tiết mail.
- **Webview xem mail ngay trong Telegram**: render HTML thật của mail (ảnh, layout,
  link) qua trang `/mail/view/`, bảo vệ bằng token ký có hạn.
- Xuất lại tài khoản đúng như lúc nhập, kèm ghi chú.
- Ghi chú cho từng tài khoản, hiện ngay cạnh tài khoản trong danh sách.

---

## Yêu cầu

- **Server**: Linux, Docker + Docker Compose v2, nginx (cho HTTPS).
- **Máy cá nhân** (để deploy): `rsync`, `ssh`, bash.
- **Tên miền** trỏ về server + SSL (bắt buộc `https` nếu muốn dùng webview trong Telegram).
- Bot token từ [@BotFather](https://t.me/BotFather).

---

## Cấu hình

Mọi thông tin nhạy cảm nằm trong `.env` (đã bị `.gitignore`, **không bao giờ commit**).

```bash
cp .env.example .env
# rồi sửa các giá trị trong .env
```

| Biến | Ý nghĩa |
|---|---|
| `DOMAIN` | Tên miền công khai (dùng cho nginx) |
| `PUBLIC_BASE_URL` | Địa chỉ https công khai — dùng cho nút mở webview xem mail |
| `DJANGO_SECRET_KEY` | Khoá bí mật Django (**bắt buộc đổi**, dùng để ký token webview) |
| `DB_*` | Thông tin PostgreSQL |
| `ADMIN_PORT` | Cổng trang admin **trên host** (trong container luôn là 8080) |
| `BOT_CHECK_INTERVAL` | Số giây BotManager kiểm tra thay đổi bot (mặc định 10) |

Sinh `DJANGO_SECRET_KEY`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

---

## Deploy lên server

### Cách 1 — dùng script (khuyên dùng)

**Bước 1.** Trên server, lấy source và thiết lập lần đầu:

```bash
git clone https://github.com/TienSato/bot-telegram.git /www/wwwroot/x-bot
cd /www/wwwroot/x-bot
DOMAIN=ten-mien-cua-ban.com bash scripts/server/thiet-lap.sh
```

Script sẽ: tự sinh `.env` (SECRET_KEY + mật khẩu DB ngẫu nhiên), **tự tìm cổng trống**,
build image và khởi động container.

**Bước 2.** Cài nginx reverse proxy (đọc `DOMAIN` từ `.env`):

```bash
bash scripts/server/cai-nginx.sh
certbot --nginx -d ten-mien-cua-ban.com      # cài SSL
```

**Bước 3.** Mở `https://ten-mien-cua-ban.com/setup/` để tạo tài khoản admin, sau đó
vào `/admin/` để thêm bot.

**Cập nhật code về sau** — chạy trên máy cá nhân:

```bash
bash scripts/trien-khai.sh          # đẩy code + build lại + khởi động
bash scripts/trien-khai.sh --nhat-ky    # xem log trực tiếp
bash scripts/trien-khai.sh --trang-thai # xem trạng thái container
```

Lần đầu chạy sẽ hỏi thông tin server và lưu vào `deploy.conf` (file này cũng bị gitignore).

### Cách 2 — Docker Compose thủ công

```bash
cp .env.example .env    # sửa giá trị trong .env
docker compose -f docker-compose.prod.yml --env-file .env up -d --build
docker compose -f docker-compose.prod.yml logs -f bot
```

---

## Chạy ở máy local (phát triển)

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Sửa DB_HOST=localhost và trỏ tới PostgreSQL của bạn

python manage.py migrate
python run.py     # chạy admin panel + tất cả bot đang bật
```

Trang admin: `http://localhost:8080/admin/`

---

## Thiết lập bot

1. Tạo bot với [@BotFather](https://t.me/BotFather), lấy token.
2. Vào `/admin/` → **Bots** → *Add* → dán token → **Save**.
3. Bấm **Kiểm thử kết nối bot** để chắc token đúng.
4. Trong phần **Bot features**, gán chức năng (ví dụ `readmail`) cho bot.
5. Chờ ~10 giây — BotManager tự khởi động bot, không cần restart.

Muốn bot chạy trong **nhóm**: thêm bot vào nhóm và cấp quyền **admin có "Delete messages"**
để bot tự dọn tin nhắn lệnh.

---

## Lệnh của bot

| Lệnh | Chức năng |
|---|---|
| `/start`, `/help`, `/id`, `/features` | Thông tin chung, danh sách lệnh, quyền truy cập |
| `/them` | Thêm tài khoản mail (giao diện nút bấm) |
| `/menu` | Mở bảng chọn tài khoản |
| `/listmail`, `/delmail` | Danh sách / xoá tài khoản |
| `/mail`, `/readall` | Đọc mail |
| `/code`, `/codes` | Lấy mã xác nhận |
| `/maildetail` | Xem chi tiết một mail |

Định dạng thêm tài khoản (mỗi dòng một tài khoản):

```
email|password|refresh_token|client_id[|tenant_id]
```

> Bot **chỉ dùng** `refresh_token` + `client_id` để đọc mail qua Microsoft Graph API.
> Trường `password` chỉ có sẵn trong combo, **không dùng để đăng nhập**.

---

## Thêm chức năng mới

Mỗi chức năng là một thư mục trong `features/`:

```
features/
  registry.py          # FeatureRegistry — nơi mỗi chức năng tự đăng ký
  readmail/            # 1 chức năng = 1 thư mục
    __init__.py        # from features.readmail import handlers
    handlers.py        # router + lệnh + callback, cuối file gọi register()
    ...
```

**Các bước:**

1. Tạo `features/<tên>/handlers.py`:

```python
from aiogram import Router
from features.registry import FeatureRegistry

FEATURE_NAME = "<tên>"
router = Router(name=FEATURE_NAME)

@router.message(Command("lenh_cua_ban"))
async def cmd_abc(message, db_user):
    await message.answer("Xin chào")

FeatureRegistry.register(
    name=FEATURE_NAME,
    description="Mô tả chức năng",
    commands=["lenh_cua_ban"],
    router=router,
)
```

2. Tạo `features/<tên>/__init__.py`:

```python
from features.<tên> import handlers  # noqa: F401
```

3. Thêm một dòng vào `run.py`:

```python
import features.<tên>.handlers  # noqa: F401
```

4. Vào admin → **Bot** → gán chức năng mới cho bot muốn dùng.

---

## Cấu trúc project

```
bot/              Khởi tạo Bot/Dispatcher, middleware (xác thực, quyền, dọn tin nhắn)
core/             Model Django, admin panel, truy vấn DB, token webview
features/         Các chức năng dạng plugin (mỗi thư mục = 1 chức năng)
web/              Django settings, URL, view (setup wizard + webview xem mail)
templates/        Giao diện admin tuỳ biến + trang webview xem mail
scripts/          Script deploy (máy cá nhân) và thiết lập server
run.py            Điểm khởi chạy: admin panel (uvicorn) + BotManager
```

---

## Bảo mật

- `.env`, `deploy.conf`, `data/`, `staticfiles/` đã nằm trong `.gitignore` — **không commit**.
- **Đổi `DJANGO_SECRET_KEY`** trước khi chạy thật: khoá này dùng để ký token webview.
- Webview xem mail dùng **token ký (HMAC), hết hạn sau 30 phút**; mail được lấy ở
  **phía server** nên `refresh_token` không bao giờ lộ ra trình duyệt.
- Nội dung HTML của mail được render trong **iframe sandbox** (chặn JavaScript của mail).
- Nên đặt `ALLOWED_HOSTS` và `CSRF_TRUSTED_ORIGINS` đúng tên miền thay vì `*`.

---

## Công nghệ

Python 3.12 · aiogram 3 · Django 5 · PostgreSQL 16 · uvicorn · Docker Compose

## License

MIT
