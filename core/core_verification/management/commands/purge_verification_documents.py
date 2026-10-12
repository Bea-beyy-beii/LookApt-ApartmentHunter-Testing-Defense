# python manage.py purge_verification_documents
#
# Deletes the ID / selfie / ownership files of rejected or replaced verification
# requests older than 90 days (Privacy Notice). The app also does this by itself
# once a day; this command is for running it right away.
from django.core.management.base import BaseCommand

from core.core_verification.services import DOCUMENT_RETENTION, purge_old_documents


class Command(BaseCommand):
    help = f"Delete documents of rejected / replaced verification requests older than {DOCUMENT_RETENTION.days} days."

    def handle(self, *args, **options):
        count = purge_old_documents()
        self.stdout.write(self.style.SUCCESS(f"Cleaned {count} verification request(s)."))
