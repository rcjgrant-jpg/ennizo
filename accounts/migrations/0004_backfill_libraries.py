"""Give every existing user a Library and an "Unsorted" folder if missing.

Companion to the post_save receiver in accounts/signals.py, which handles
users created from now on. Idempotent: safe to run against a database
where some or all users are already provisioned.
"""

from django.db import migrations


DEFAULT_FOLDER_NAME = "Unsorted"


def backfill(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Library = apps.get_model("accounts", "Library")
    Folder = apps.get_model("library", "Folder")

    for user in User.objects.all():
        library, _ = Library.objects.get_or_create(user=user)
        Folder.objects.get_or_create(library=library, name=DEFAULT_FOLDER_NAME)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_user_avatar_user_bio"),
        ("library", "0009_sample_last_active_at"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
