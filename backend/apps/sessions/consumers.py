from __future__ import annotations

from uuid import UUID

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.sessions.models import Session
from apps.sessions.realtime import session_group_name, session_snapshot


class SessionConsumer(AsyncJsonWebsocketConsumer):
    session_id: UUID
    group_name: str

    async def connect(self):
        try:
            self.session_id = UUID(self.scope["url_route"]["kwargs"]["session_id"])
        except (KeyError, ValueError):
            await self.close(code=4400)
            return

        exists = await self._session_exists(self.session_id)
        if not exists:
            await self.close(code=4404)
            return

        self.group_name = session_group_name(self.session_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json(
            {
                "type": "session.snapshot",
                "session": await database_sync_to_async(session_snapshot)(self.session_id),
            }
        )

    async def disconnect(self, _close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

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
