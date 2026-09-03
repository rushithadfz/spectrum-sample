"""URL configuration for the agent portal."""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from portal.views import role_select

urlpatterns = [
    path("admin/", admin.site.urls),
    # POC sign-in: pick a role, no credentials. See portal.views.role_select.
    path("login/", role_select, name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("portal.urls")),
]
