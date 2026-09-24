"""URL configuration — Read Mail Bot."""
from django.contrib import admin
from django.urls import path

from web.views import mail_view, setup_view

urlpatterns = [
    path("setup/", setup_view, name="setup"),
    path("mail/view/", mail_view, name="mail_view"),
    path("admin/", admin.site.urls),
]
