# core/dev_timing.py
# DEBUG only: prints how long each request took and how much of that was the
# database, e.g.
#   [timing] GET /listing/…/ 200 — 840 ms total, 12 queries (790 ms in the database)
# If "in the database" is most of the time, the lag is the connection to the
# remote database (distance/region), not the app code.
import time

from django.db import connection

SKIP_PREFIXES = ("/static/", "/media/", "/favicon")


class RequestTimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(SKIP_PREFIXES):
            return self.get_response(request)

        start = time.perf_counter()
        first_query = len(connection.queries)   # Django records queries when DEBUG = True
        response = self.get_response(request)

        queries = connection.queries[first_query:]
        total_ms = (time.perf_counter() - start) * 1000
        db_ms = sum(float(q["time"]) for q in queries) * 1000
        print(f"[timing] {request.method} {request.path} {response.status_code} — "
              f"{total_ms:.0f} ms total, {len(queries)} queries ({db_ms:.0f} ms in the database)")
        return response