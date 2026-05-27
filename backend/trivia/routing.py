from apps.sessions.routing import websocket_urlpatterns as session_websocket_urlpatterns

websocket_urlpatterns = [
    *session_websocket_urlpatterns,
]
