from __future__ import annotations

from uuid import UUID

from asgiref.sync import async_to_sync, sync_to_async
from channels.layers import get_channel_layer

from apps.sessions.models import Session
from apps.sessions.serializers import SessionSerializer


def session_group_name(session_id: str | UUID) -> str:
    return f"session_{str(session_id).replace('-', '_')}"


def session_snapshot(session_id: str | UUID) -> dict:
    session = (
        Session.objects.select_related("quiz", "quiz__source_material")
        .prefetch_related(
            "players",
            "quiz__rounds__questions",
        )
        .get(pk=session_id)
    )
    return SessionSerializer(session).data


async def broadcast_session_snapshot(session_id: str | UUID, event: str = "session.updated") -> None:
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    snapshot = await sync_to_async(session_snapshot)(session_id)
    await channel_layer.group_send(
        session_group_name(session_id),
        {
            "type": "session_snapshot",
            "event": event,
            "session": snapshot,
        },
    )


def broadcast_session_snapshot_sync(session_id: str | UUID, event: str = "session.updated") -> None:
    try:
        async_to_sync(broadcast_session_snapshot)(session_id, event)
    except Exception:
        # REST remains the source of truth. A transient channel-layer failure should
        # not make player actions fail.
        return
