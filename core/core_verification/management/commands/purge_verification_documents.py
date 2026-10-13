# python manage.py purge_verification_documents
#
# Deletes the ID / selfie / ownership files of rejected or replaced verification
# requests older than 90 days (Privacy Notice). The app also does this by itself
# once a day; this command is for running it right away.
from django.core.management.base import BaseCommand

from core.core_verification.services import DocumentPurge


class Command(BaseCommand):
    help = (f"Delete documents of rejected / replaced verification requests older than "
            f"{DocumentPurge.RETENTION.days} days.")

    def handle(self, *args, **options):
        count = DocumentPurge().run()
        self.stdout.write(self.style.SUCCESS(f"Cleaned {count} verification request(s)."))
