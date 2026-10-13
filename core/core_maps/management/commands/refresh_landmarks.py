# core_maps/management/commands/refresh_landmarks.py
#
#   python manage.py refresh_landmarks            -> complexes with a pin but no landmarks
#   python manage.py refresh_landmarks --all      -> every complex with a pin (keeps manual ones)
#   python manage.py refresh_landmarks --radius 5 --mode commute
#
# For listings saved while OpenStreetMap was slow or down (they ended up
# with no landmarks to show renters).
from django.core.management.base import BaseCommand
from django.db.models import Count

from core.core_listings.models import Complex
from core.core_maps.maps.geo import DEFAULT_MODE, DEFAULT_RADIUS_KM, TRAVEL_MODES
from core.core_maps.maps.services import complex_landmarks, nearby_landmarks, save_complex_landmarks


class Command(BaseCommand):
    help = "Find nearby landmarks again for complexes that have none (or for all with --all)."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Also complexes that already have landmarks.")
        parser.add_argument("--radius", type=float, default=DEFAULT_RADIUS_KM, help="Radius in km (default 3).")
        parser.add_argument("--mode", choices=list(TRAVEL_MODES), default=DEFAULT_MODE)

    def handle(self, *args, **options):
        complexes = Complex.objects.filter(latitude__isnull=False, longitude__isnull=False)
        if not options["all"]:
            complexes = complexes.annotate(n=Count("landmarks")).filter(n=0)

        done = 0
        for complex_obj in complexes:
            found, source = nearby_landmarks(float(complex_obj.latitude), float(complex_obj.longitude),
                                             options["radius"], options["mode"])
            if source != "live":
                self.stderr.write(f"OpenStreetMap is unreachable; stopped before {complex_obj.complex_name}.")
                break
            manual = [item for item in complex_landmarks(complex_obj) if item["manual"]]
            saved = save_complex_landmarks(complex_obj, manual + found, options["mode"])
            done += 1
            self.stdout.write(f"{complex_obj.complex_name}: {len(saved)} landmarks")

        self.stdout.write(self.style.SUCCESS(f"Updated {done} complex{'es' if done != 1 else ''}."))
