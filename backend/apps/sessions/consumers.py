from __future__ import annotations

from urllib.parse import parse_qs
from uuid import UUID

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db import transaction
from django.utils import timezone

from apps.sessions.models import Session, SessionPlayer
from apps.sessions.realtime import broadcast_session_snapshot, session_group_name, session_snapshot


class SessionConsumer(AsyncJsonWebsocketConsumer):
    session_id: UUID
    group_name: str
    player_id: UUID | None = None

    async def connect(self):
        try:
            self.session_id = UUID(self.scope["url_route"]["kwargs"]["session_id"])
        except (KeyError, ValueError):
            await self.close(code=4400)
            return

        self.player_id = self._query_player_id()
        if self.player_id and not await self._player_exists(self.session_id, self.player_id):
            await self.close(code=4403)
            return

        exists = await self._session_exists(self.session_id)
        if not exists:
            await self.close(code=4404)
            return

        self.group_name = session_group_name(self.session_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        if self.player_id:
            await self._set_player_presence(self.session_id, self.player_id, online=True)
        await self.send_json(
            {
                "type": "session.snapshot",
                "session": await database_sync_to_async(session_snapshot)(self.session_id),
            }
        )
        if self.player_id:
            await broadcast_session_snapshot(self.session_id, "session.presence")

    async def disconnect(self, _close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        if self.player_id:
            await self._set_player_presence(self.session_id, self.player_id, online=False)
            await broadcast_session_snapshot(self.session_id, "session.presence")

    async def receive_json(self, content, **_kwargs):
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def session_snapshot(self, event):
        await self.send_json(
            {
                "type": event.get("event", "session.updated"),
                "session": event["session"],
            }
        )

    @database_sync_to_async
    def _session_exists(self, session_id: UUID) -> bool:
        return Session.objects.filter(pk=session_id).exists()

    def _query_player_id(self) -> UUID | None:
        raw_query = self.scope.get("query_string", b"").decode("utf-8")
        raw_player_id = (parse_qs(raw_query).get("player_id") or [""])[0]
        if not raw_player_id:
            return None
        try:
            return UUID(raw_player_id)
        except ValueError:
            return None

    @database_sync_to_async
    def _player_exists(self, session_id: UUID, player_id: UUID) -> bool:
        return SessionPlayer.objects.filter(pk=player_id, session_id=session_id).exists()

    @database_sync_to_async
    def _set_player_presence(self, session_id: UUID, player_id: UUID, *, online: bool) -> None:
        with transaction.atomic():
            session = Session.objects.select_for_update().get(pk=session_id)
            if not SessionPlayer.objects.filter(pk=player_id, session=session).exists():
                return

            state = session.state or {}
            raw_presence = state.get("presence")
            presence = raw_presence if isinstance(raw_presence, dict) else {}
            player_key = str(player_id)
            raw_entry = presence.get(player_key)
            entry = raw_entry if isinstance(raw_entry, dict) else {}
            connection_count = int(entry.get("connection_count") or 0)
            now = timezone.now().isoformat()

            if online:
                connection_count += 1
                entry.setdefault("connected_at", now)
            else:
                connection_count = max(0, connection_count - 1)

            entry.update(
                {
                    "online": connection_count > 0,
                    "connection_count": connection_count,
                    "last_seen_at": now,
                }
            )
            presence[player_key] = entry
            state["presence"] = presence
            session.state = state
            session.save(update_fields=["state"])
