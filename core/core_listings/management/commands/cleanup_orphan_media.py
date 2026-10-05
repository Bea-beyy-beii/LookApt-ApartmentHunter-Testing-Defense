# python manage.py cleanup_orphan_media            -> dry run (only lists)
# python manage.py cleanup_orphan_media --delete   -> really deletes
#
# Finds uploaded files (S3 or local) that no database row points to anymore,
# e.g. left behind by deletes that crashed halfway.
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from core.core_listings.models import ComplexPicture, UnitPicture, UnitVideo

FOLDERS = {
    "complex_pictures": (ComplexPicture, "image"),
    "unit_pictures": (UnitPicture, "image"),
    "unit_videos": (UnitVideo, "video"),
}


class Command(BaseCommand):
    help = "List (or delete with --delete) media files that no database row uses."

    def add_arguments(self, parser):
        parser.add_argument("--delete", action="store_true", help="Actually delete the orphaned files.")

    def handle(self, *args, **options):
        delete = options["delete"]
        orphans = 0

        for folder, (model, field) in FOLDERS.items():
            used = set(model.objects.values_list(field, flat=True))
            try:
                _, files = default_storage.listdir(folder)
            except FileNotFoundError:
                continue

            for name in files:
                path = f"{folder}/{name}"
                if path in used:
                    continue
                orphans += 1
                self.stdout.write(f"{'Deleting' if delete else 'Orphan'}: {path}")
                if delete:
                    default_storage.delete(path)

        if delete:
            self.stdout.write(self.style.SUCCESS(f"{orphans} orphaned file(s) deleted."))
        else:
            self.stdout.write(self.style.WARNING(f"{orphans} orphaned file(s) found. Run again with --delete to remove them."))