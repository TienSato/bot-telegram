"""Django Admin — Read Mail Bot.

Quan ly nhieu bot, moi bot gan voi cac chuc nang rieng.
Bao gom:
  - Nut kiem thu bot (goi Telegram API getMe)
  - Quan ly quyen user nang cao
  - Ban/unban nhanh
  - Ma tran quyen (permission matrix)
"""
from __future__ import annotations

import json
import logging

import requests as http_requests
from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from core.models import (
    Bot,
    BotFeature,
    BotSetting,
    Feature,
    MailAccount,
    TelegramUser,
    UserPermission,
)

logger = logging.getLogger(__name__)

# ── Cau hinh trang admin ────────────────────────────────────────────────────
admin.site.site_header = "X-Bot — Admin"
admin.site.site_title = "X-Bot"
admin.site.index_title = "Quản lý hệ thống"


# ── Inline models ───────────────────────────────────────────────────────────


class BotFeatureInline(admin.TabularInline):
    model = BotFeature
    extra = 1
    fields = ("feature", "enabled")


class MailAccountInline(admin.TabularInline):
    model = MailAccount
    extra = 0
    fields = ("email", "client_id", "tenant_id", "note", "added_at")
    readonly_fields = ("added_at",)


class UserPermissionInline(admin.TabularInline):
    model = UserPermission
    extra = 0
    fields = ("feature", "allowed")


# ── Bot ─────────────────────────────────────────────────────────────────────


@admin.register(Bot)
class BotAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "masked_token",
        "feature_list",
        "is_active_icon",
        "test_button",
        "created_at",
    )
    list_filter = ("is_active",)
    search_fields = ("name", "description")
    list_per_page = 25
    actions = ["test_bot_connection", "activate_bots", "deactivate_bots"]

    inlines = [BotFeatureInline]

    fieldsets = (
        (None, {
            "fields": ("name", "token", "description", "is_active"),
        }),
        ("Thời gian", {
            "fields": ("created_at",),
            "classes": ("collapse",),
        }),
    )
    readonly_fields = ("created_at",)

    # ── Custom change form voi nut kiem thu ──

    change_form_template = "admin/core/bot_change_form.html"

    # ── Custom URLs ──

    def get_urls(self):
        custom_urls = [
            path(
                "<int:bot_id>/test-connection/",
                self.admin_site.admin_view(self.test_connection_view),
                name="core_bot_test_connection",
            ),
        ]
        return custom_urls + super().get_urls()

    def test_connection_view(
        self, request: HttpRequest, bot_id: int,
    ) -> JsonResponse:
        """API endpoint kiem thu ket noi bot qua Telegram API."""
        try:
            bot = Bot.objects.get(id=bot_id)
        except Bot.DoesNotExist:
            return JsonResponse(
                {"ok": False, "error": "Bot không tồn tại"}, status=404,
            )

        try:
            resp = http_requests.get(
                f"https://api.telegram.org/bot{bot.token}/getMe",
                timeout=10,
            )
            data = resp.json()

            if data.get("ok"):
                info = data["result"]
                return JsonResponse({
                    "ok": True,
                    "bot_id": info.get("id"),
                    "username": info.get("username", ""),
                    "first_name": info.get("first_name", ""),
                    "can_join_groups": info.get("can_join_groups", False),
                    "can_read_all_group_messages": info.get(
                        "can_read_all_group_messages", False,
                    ),
                })
            else:
                return JsonResponse({
                    "ok": False,
                    "error": data.get("description", "Lỗi không xác định"),
                })
        except http_requests.Timeout:
            return JsonResponse({
                "ok": False,
                "error": "Hết thời gian kết nối (timeout)",
            })
        except Exception as e:
            return JsonResponse({
                "ok": False,
                "error": f"Lỗi kết nối: {e}",
            })

    # ── Admin actions ──

    @admin.action(description="Kiểm thử kết nối bot")
    def test_bot_connection(
        self, request: HttpRequest, queryset: QuerySet,
    ) -> None:
        """Kiem thu ket noi cho cac bot duoc chon."""
        results = []
        for bot in queryset:
            try:
                resp = http_requests.get(
                    f"https://api.telegram.org/bot{bot.token}/getMe",
                    timeout=10,
                )
                data = resp.json()
                if data.get("ok"):
                    info = data["result"]
                    results.append(
                        f"{bot.name}: @{info.get('username', 'N/A')} "
                        f"(ID: {info.get('id')})"
                    )
                else:
                    results.append(
                        f"{bot.name}: "
                        f"{data.get('description', 'Lỗi không xác định')}"
                    )
            except Exception as e:
                results.append(f"{bot.name}: {e}")

        msg = " | ".join(results)
        level = (
            messages.SUCCESS
            if all("" in r for r in results)
            else messages.WARNING
        )
        self.message_user(request, msg, level=level)

    @admin.action(description="Bật bot")
    def activate_bots(
        self, request: HttpRequest, queryset: QuerySet,
    ) -> None:
        count = queryset.update(is_active=True)
        self.message_user(
            request,
            f"Đã bật {count} bot. Bot sẽ tự động khởi động trong vài giây.",
            messages.SUCCESS,
        )

    @admin.action(description="Tắt bot")
    def deactivate_bots(
        self, request: HttpRequest, queryset: QuerySet,
    ) -> None:
        count = queryset.update(is_active=False)
        self.message_user(
            request,
            f"Đã tắt {count} bot. Bot sẽ tự động dừng trong vài giây.",
            messages.SUCCESS,
        )

    # ── Display columns ──

    @admin.display(boolean=True, description="Hoạt động")
    def is_active_icon(self, obj: Bot) -> bool:
        return obj.is_active

    @admin.display(description="Token")
    def masked_token(self, obj: Bot) -> str:
        if obj.token and len(obj.token) > 10:
            return obj.token[:6] + "••••••" + obj.token[-4:]
        return "••••••••"

    @admin.display(description="Chức năng")
    def feature_list(self, obj: Bot) -> str:
        features = obj.bot_features.filter(
            enabled=True,
        ).values_list("feature_id", flat=True)
        if features:
            return ", ".join(features)
        return "(chưa gán)"

    @admin.display(description="Kiểm thử")
    def test_button(self, obj: Bot) -> str:
        if obj.pk:
            url = reverse("admin:core_bot_test_connection", args=[obj.pk])
            return format_html(
                '<button type="button" class="button" '
                'style="padding:4px 12px;font-size:12px;cursor:pointer" '
                'onclick="testBot(this, \'{}\')">'
                'Test</button>'
                '<span id="test-result-{}" style="margin-left:8px"></span>'
                '<script>'
                'function testBot(btn, url) {{'
                '  btn.disabled = true; btn.textContent = "...";'
                '  fetch(url)'
                '  .then(r => r.json())'
                '  .then(d => {{'
                '    if(d.ok) {{'
                '      btn.textContent = "OK";'
                '      btn.style.background = "#28a745";'
                '      btn.style.color = "white";'
                '    }} else {{'
                '      btn.textContent = "Lỗi";'
                '      btn.style.background = "#dc3545";'
                '      btn.style.color = "white";'
                '      btn.title = d.error;'
                '    }}'
                '    setTimeout(() => {{'
                '      btn.disabled = false;'
                '      btn.textContent = "Test";'
                '      btn.style.background = "";'
                '      btn.style.color = "";'
                '    }}, 3000);'
                '  }})'
                '  .catch(() => {{'
                '    btn.textContent = "Lỗi";'
                '    btn.disabled = false;'
                '  }});'
                '}}'
                '</script>',
                url,
                obj.pk,
            )
        return "-"


# ── TelegramUser ────────────────────────────────────────────────────────────


@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = (
        "telegram_id",
        "username",
        "first_name",
        "is_admin_icon",
        "is_banned_icon",
        "account_count",
        "permission_summary",
        "last_active",
    )
    list_filter = ("is_admin", "is_banned")
    search_fields = ("telegram_id", "username", "first_name")
    readonly_fields = ("created_at", "last_active")
    list_per_page = 25
    actions = [
        "ban_users",
        "unban_users",
        "make_admin",
        "remove_admin",
        "grant_all_features",
        "revoke_all_features",
    ]

    inlines = [MailAccountInline, UserPermissionInline]

    fieldsets = (
        (None, {
            "fields": ("telegram_id", "username", "first_name"),
        }),
        ("Quyền", {
            "fields": ("is_admin", "is_banned"),
        }),
        ("Thời gian", {
            "fields": ("created_at", "last_active"),
            "classes": ("collapse",),
        }),
    )

    def get_urls(self):
        custom_urls = [
            path(
                "permission-matrix/",
                self.admin_site.admin_view(self.permission_matrix_view),
                name="core_permission_matrix",
            ),
        ]
        return custom_urls + super().get_urls()

    def permission_matrix_view(self, request: HttpRequest) -> HttpResponse:
        """View ma tran quyen: luoi User x Feature."""
        features = list(Feature.objects.order_by("name"))
        users = list(
            TelegramUser.objects.filter(is_banned=False).order_by(
                "-is_admin", "username", "telegram_id",
            )
        )

        # Xu ly POST — luu quyen
        if request.method == "POST":
            # Parse form data
            changes = 0
            for user in users:
                for feature in features:
                    field_name = f"perm_{user.id}_{feature.name}"
                    is_allowed = field_name in request.POST

                    # Kiem tra co thay doi khong
                    perm, created = UserPermission.objects.get_or_create(
                        user=user,
                        feature=feature,
                        defaults={"allowed": is_allowed},
                    )
                    if not created and perm.allowed != is_allowed:
                        perm.allowed = is_allowed
                        perm.save()
                        changes += 1

            if changes:
                self.message_user(
                    request,
                    f"Đã cập nhật {changes} quyền.",
                    messages.SUCCESS,
                )
            else:
                self.message_user(
                    request, "Không có thay đổi nào.", messages.INFO,
                )

        # Lay tat ca quyen hien tai
        all_perms: dict[tuple[int, str], bool] = {}
        for p in UserPermission.objects.all():
            all_perms[(p.user_id, p.feature_id)] = p.allowed

        # Xay dung data cho template
        matrix = []
        for user in users:
            row = {
                "user": user,
                "permissions": [],
            }
            for feature in features:
                allowed = all_perms.get((user.id, feature.name), True)
                row["permissions"].append({
                    "feature_name": feature.name,
                    "allowed": allowed,
                    "feature_enabled": feature.enabled,
                    "field_name": f"perm_{user.id}_{feature.name}",
                })
            matrix.append(row)

        context = {
            **self.admin_site.each_context(request),
            "title": "Ma trận quyền",
            "features": features,
            "matrix": matrix,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request,
            "admin/core/permission_matrix.html",
            context,
        )

    # ── Admin actions ──

    @admin.action(description="Chặn user")
    def ban_users(
        self, request: HttpRequest, queryset: QuerySet,
    ) -> None:
        count = queryset.update(is_banned=True)
        self.message_user(
            request, f"Đã chặn {count} user.", messages.WARNING,
        )

    @admin.action(description="Bỏ chặn user")
    def unban_users(
        self, request: HttpRequest, queryset: QuerySet,
    ) -> None:
        count = queryset.update(is_banned=False)
        self.message_user(
            request, f"Đã bỏ chặn {count} user.", messages.SUCCESS,
        )

    @admin.action(description="Phong admin")
    def make_admin(
        self, request: HttpRequest, queryset: QuerySet,
    ) -> None:
        count = queryset.update(is_admin=True)
        self.message_user(
            request, f"Đã phong {count} user làm admin.", messages.SUCCESS,
        )

    @admin.action(description="Bỏ admin")
    def remove_admin(
        self, request: HttpRequest, queryset: QuerySet,
    ) -> None:
        count = queryset.update(is_admin=False)
        self.message_user(
            request, f"Đã bỏ quyền admin của {count} user.", messages.SUCCESS,
        )

    @admin.action(description="Cấp tất cả quyền")
    def grant_all_features(
        self, request: HttpRequest, queryset: QuerySet,
    ) -> None:
        features = Feature.objects.all()
        count = 0
        for user in queryset:
            for feature in features:
                _, created = UserPermission.objects.update_or_create(
                    user=user,
                    feature=feature,
                    defaults={"allowed": True},
                )
                count += 1
        self.message_user(
            request,
            f"Đã cấp tất cả quyền cho {queryset.count()} user.",
            messages.SUCCESS,
        )

    @admin.action(description="Thu hồi tất cả quyền")
    def revoke_all_features(
        self, request: HttpRequest, queryset: QuerySet,
    ) -> None:
        features = Feature.objects.all()
        for user in queryset:
            for feature in features:
                UserPermission.objects.update_or_create(
                    user=user,
                    feature=feature,
                    defaults={"allowed": False},
                )
        self.message_user(
            request,
            f"Đã thu hồi tất cả quyền của {queryset.count()} user.",
            messages.WARNING,
        )

    # ── Display columns ──

    @admin.display(boolean=True, description="Admin")
    def is_admin_icon(self, obj: TelegramUser) -> bool:
        return obj.is_admin

    @admin.display(boolean=True, description="Banned")
    def is_banned_icon(self, obj: TelegramUser) -> bool:
        return obj.is_banned

    @admin.display(description="Số TK")
    def account_count(self, obj: TelegramUser) -> int:
        return obj.accounts.count()

    @admin.display(description="Quyền")
    def permission_summary(self, obj: TelegramUser) -> str:
        """Hien thi tom tat quyen cua user."""
        perms = UserPermission.objects.filter(user=obj)
        if not perms.exists():
            return format_html(
                '<span style="color:#999">Mặc định (tất cả)</span>',
            )
        allowed = perms.filter(allowed=True).count()
        denied = perms.filter(allowed=False).count()
        parts = []
        if allowed:
            parts.append(f'<span style="color:green">{allowed}</span>')
        if denied:
            parts.append(f'<span style="color:red">{denied}</span>')
        return format_html(" ".join(parts))


# ── MailAccount ─────────────────────────────────────────────────────────────


@admin.register(MailAccount)
class MailAccountAdmin(admin.ModelAdmin):
    list_display = ("email", "user_link", "tenant_id", "note_short", "added_at")
    list_filter = ("tenant_id",)
    search_fields = ("email", "user__username", "user__telegram_id", "note")
    readonly_fields = ("added_at",)
    list_per_page = 25
    raw_id_fields = ("user",)

    @admin.display(description="Ghi chú")
    def note_short(self, obj: MailAccount) -> str:
        note = obj.note or ""
        return (note[:40] + "…") if len(note) > 40 else note

    @admin.display(description="User")
    def user_link(self, obj: MailAccount) -> str:
        return format_html(
            '<a href="/admin/core/telegramuser/{}/change/">{}</a>',
            obj.user_id,
            obj.user,
        )


# ── Feature ─────────────────────────────────────────────────────────────────


@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "description",
        "enabled_icon",
        "bot_count",
        "user_count",
    )
    list_editable = ("description",)
    list_filter = ("enabled",)
    search_fields = ("name", "description")
    actions = ["enable_features", "disable_features"]

    @admin.action(description="Bật chức năng")
    def enable_features(
        self, request: HttpRequest, queryset: QuerySet,
    ) -> None:
        count = queryset.update(enabled=True)
        self.message_user(
            request, f"Đã bật {count} chức năng.", messages.SUCCESS,
        )

    @admin.action(description="Tắt chức năng")
    def disable_features(
        self, request: HttpRequest, queryset: QuerySet,
    ) -> None:
        count = queryset.update(enabled=False)
        self.message_user(
            request, f"Đã tắt {count} chức năng.", messages.WARNING,
        )

    @admin.display(boolean=True, description="Bật")
    def enabled_icon(self, obj: Feature) -> bool:
        return obj.enabled

    @admin.display(description="Số bot")
    def bot_count(self, obj: Feature) -> int:
        return obj.bot_features.filter(enabled=True).count()

    @admin.display(description="Số user được phép")
    def user_count(self, obj: Feature) -> str:
        denied = UserPermission.objects.filter(
            feature=obj, allowed=False,
        ).count()
        total_users = TelegramUser.objects.filter(is_banned=False).count()
        allowed = total_users - denied
        if denied == 0:
            return format_html(
                '<span style="color:green">Tất cả ({0})</span>',
                total_users,
            )
        return format_html(
            '<span>{0}/{1}</span>',
            allowed,
            total_users,
        )


# ── BotSetting ──────────────────────────────────────────────────────────────


@admin.register(BotSetting)
class BotSettingAdmin(admin.ModelAdmin):
    list_display = ("key", "display_value", "category", "is_secret_icon")
    list_filter = ("category", "is_secret")
    search_fields = ("key", "description")
    list_per_page = 50

    fieldsets = (
        (None, {
            "fields": ("key", "value", "category"),
        }),
        ("Chi tiết", {
            "fields": ("description", "is_secret"),
        }),
    )

    @admin.display(boolean=True, description="Ẩn")
    def is_secret_icon(self, obj: BotSetting) -> bool:
        return obj.is_secret

    @admin.display(description="Giá trị")
    def display_value(self, obj: BotSetting) -> str:
        if obj.is_secret and obj.value:
            return "••••••••"
        return obj.value[:80] if obj.value else "(trống)"


# ── UserPermission ──────────────────────────────────────────────────────────


@admin.register(UserPermission)
class UserPermissionAdmin(admin.ModelAdmin):
    list_display = ("user", "feature", "allowed_icon")
    list_filter = ("allowed", "feature")
    search_fields = ("user__username", "user__telegram_id", "feature__name")
    list_per_page = 50
    raw_id_fields = ("user",)
    actions = ["allow_selected", "deny_selected"]

    @admin.action(description="Cho phép")
    def allow_selected(
        self, request: HttpRequest, queryset: QuerySet,
    ) -> None:
        count = queryset.update(allowed=True)
        self.message_user(
            request, f"Đã cho phép {count} quyền.", messages.SUCCESS,
        )

    @admin.action(description="Từ chối")
    def deny_selected(
        self, request: HttpRequest, queryset: QuerySet,
    ) -> None:
        count = queryset.update(allowed=False)
        self.message_user(
            request, f"Đã từ chối {count} quyền.", messages.WARNING,
        )

    @admin.display(boolean=True, description="Cho phép")
    def allowed_icon(self, obj: UserPermission) -> bool:
        return obj.allowed
