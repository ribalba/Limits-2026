import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files import File
from django.core.management.base import BaseCommand

from todoapp.models import ToDo


class Command(BaseCommand):
    help = "Import sample users and todos from a JSON file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default="sample_data.json",
            help="Path to JSON file (default: sample_data.json)",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.is_absolute():
            path = settings.BASE_DIR / path

        if not path.exists():
            self.stderr.write(f"Sample data file not found: {path}")
            return

        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)

        users = data.get("users", [])
        todos = data.get("todos", [])

        for user_data in users:
            username = user_data.get("username")
            password = user_data.get("password")
            if not username or not password:
                continue

            user, created = User.objects.get_or_create(username=username)
            if created or not user.check_password(password):
                user.set_password(password)
                user.save()

        for todo_data in todos:
            username = todo_data.get("username")
            if not username:
                continue

            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                continue

            title = todo_data.get("title") or "Untitled"
            text = todo_data.get("text") or ""
            done = bool(todo_data.get("done", False))

            todo = ToDo.objects.create(user=user, title=title, text=text, done=done)

            file_path_value = todo_data.get("file")
            if file_path_value:
                file_path = Path(file_path_value)
                if not file_path.is_absolute():
                    file_path = settings.BASE_DIR / file_path
                if file_path.exists():
                    with file_path.open("rb") as file_handle:
                        todo.file.save(file_path.name, File(file_handle), save=True)

        self.stdout.write("Sample data imported.")
