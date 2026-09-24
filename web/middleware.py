"""Middleware — Read Mail Bot.

FirstRunMiddleware: chuyen huong den trang setup khi chua co admin.
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.shortcuts import redirect


class FirstRunMiddleware:
    """Khi chua co tai khoan admin nao, chuyen moi request den /setup/."""

    def __init__(self, get_response):
        self.get_response = get_response
        self._has_users = False

    def __call__(self, request):
        # Cache ket qua — chi query DB khi chua co user
        if not self._has_users:
            self._has_users = User.objects.exists()

        if not self._has_users:
            # Cho phep truy cap /setup/ va /static/
            if request.path not in ("/setup/",) and not request.path.startswith("/static/"):
                return redirect("/setup/")

        return self.get_response(request)
