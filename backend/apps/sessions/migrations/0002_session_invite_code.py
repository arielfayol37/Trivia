from __future__ import annotations

import uuid

from django.db import migrations, models


def populate_invite_codes(apps, _schema_editor):
    session_model = apps.get_model("game_sessions", "Session")
    used_codes = set(
        session_model.objects.exclude(invite_code="").values_list("invite_code", flat=True)
    )

    for session in session_model.objects.filter(invite_code=""):
        while True:
            invite_code = uuid.uuid4().hex[:8].upper()
            if invite_code not in used_codes:
                used_codes.add(invite_code)
                break
        session.invite_code = invite_code
        session.save(update_fields=["invite_code"])


class Migration(migrations.Migration):
    dependencies = [
        ("game_sessions", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="session",
            name="invite_code",
            field=models.CharField(blank=True, db_index=True, max_length=10),
        ),
        migrations.RunPython(populate_invite_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="session",
            name="invite_code",
            field=models.CharField(db_index=True, max_length=10, unique=True),
        ),
    ]
