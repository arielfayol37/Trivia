from django.urls import re_path

from apps.sessions.consumers import SessionConsumer

websocket_urlpatterns = [
    re_path(r"^ws/session/(?P<session_id>[0-9a-f-]+)/$", SessionConsumer.as_asgi()),
]
