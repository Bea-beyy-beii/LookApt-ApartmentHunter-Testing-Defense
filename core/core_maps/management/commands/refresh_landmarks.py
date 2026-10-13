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
from core.core_maps.maps.geo import GeoPoint, SearchRadius, TravelMode
from core.core_maps.maps.services import ComplexLandmarks, LandmarkFinder


class Command(BaseCommand):
    help = "Find nearby landmarks again for complexes that have none (or for all with --all)."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Also complexes that already have landmarks.")
        parser.add_argument("--radius", type=float, default=SearchRadius.DEFAULT_KM, help="Radius in km (default 3).")
        parser.add_argument("--mode", choices=TravelMode.keys(), default=TravelMode.DEFAULT_KEY)

    def handle(self, *args, **options):
        complexes = Complex.objects.filter(latitude__isnull=False, longitude__isnull=False)
        if not options["all"]:
            complexes = complexes.annotate(n=Count("landmarks")).filter(n=0)

        done = 0
        for complex_obj in complexes:
            point = GeoPoint(complex_obj.latitude, complex_obj.longitude)
            found, source = LandmarkFinder(point, SearchRadius(options["radius"]), options["mode"]).find()
            if source != "live":
                self.stderr.write(f"OpenStreetMap is unreachable; stopped before {complex_obj.complex_name}.")
                break
            saved_landmarks = ComplexLandmarks(complex_obj)
            manual = [item for item in saved_landmarks.as_list() if item["manual"]]
            saved = saved_landmarks.replace(manual + found, options["mode"])
            done += 1
            self.stdout.write(f"{complex_obj.complex_name}: {len(saved)} landmarks")

        self.stdout.write(self.style.SUCCESS(f"Updated {done} complex{'es' if done != 1 else ''}."))
