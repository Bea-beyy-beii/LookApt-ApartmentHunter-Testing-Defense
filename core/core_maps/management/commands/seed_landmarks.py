# python manage.py seed_landmarks
#
# Seeds well-known Davao City landmarks into the Landmark table so the map
# feature works even when OpenStreetMap (Overpass/Nominatim) is unreachable.
# Coordinates are approximate (±100 m); fix them in the admin if needed.
from django.core.management.base import BaseCommand

from core.core_listings.models import Landmark

T = Landmark.LandmarkTypes

DAVAO_LANDMARKS = [
    ("Mapúa Malayan Colleges Mindanao", T.SCHOOL, 7.0588, 125.5962),
    ("Ateneo de Davao University", T.SCHOOL, 7.0716, 125.6131),
    ("University of Mindanao", T.SCHOOL, 7.0659, 125.6020),
    ("University of Southeastern Philippines", T.SCHOOL, 7.0855, 125.6170),
    ("SM City Davao", T.MALL, 7.0497, 125.5881),
    ("SM Lanang Premier", T.MALL, 7.0985, 125.6310),
    ("Abreeza Mall", T.MALL, 7.0906, 125.6113),
    ("Gaisano Mall of Davao", T.MALL, 7.0784, 125.6142),
    ("Davao Doctors Hospital", T.HEALTHCENTER, 7.0700, 125.6040),
    ("Southern Philippines Medical Center", T.HEALTHCENTER, 7.0981, 125.6194),
    ("Roxas Night Market", T.MARKET, 7.0718, 125.6104),
    ("Bankerohan Public Market", T.MARKET, 7.0670, 125.6000),
    ("People's Park", T.PARK, 7.0725, 125.6082),
    ("San Pedro Cathedral", T.CHURCH, 7.0650, 125.6085),
    ("Davao City Hall", T.GOVERNMENT, 7.0644, 125.6088),
    ("Davao City Overland Transport Terminal", T.TERMINAL, 7.0524, 125.5883),
    ("Francisco Bangoy International Airport", T.AIRPORT, 7.1255, 125.6458),
]


class Command(BaseCommand):
    help = "Seed common Davao City landmarks (offline fallback for the map feature)."

    def handle(self, *args, **options):
        created = 0
        for name, category, lat, lng in DAVAO_LANDMARKS:
            _, was_created = Landmark.objects.update_or_create(
                name=name, category=category,
                defaults={"latitude": lat, "longitude": lng},
            )
            created += was_created
        self.stdout.write(self.style.SUCCESS(
            f"{created} landmarks created, {len(DAVAO_LANDMARKS) - created} updated."
        ))
