# core/dev_timing.py
# DEBUG only: prints how long each request took and how much of that was the
# database, e.g.
#   [timing] GET /listing/…/ 200 — 840 ms total, 12 queries (790 ms in the database)
# If "in the database" is most of the time, the lag is the connection to the
# remote database (distance/region), not the app code.
import time

from django.conf import settings
from django.db import connection

from core.middleware import Middleware


class RequestTimingMiddleware(Middleware):
    SKIP_PREFIXES = ("/static/", "/media/", "/favicon")

    def _skip(self, request):
        # settings.DEBUG is checked per request: tests switch it off at runtime
        return not settings.DEBUG or request.path.startswith(self.SKIP_PREFIXES)

    def __call__(self, request):
        if self._skip(request):
            return self.get_response(request)

        start = time.perf_counter()
        first_query = len(connection.queries)   # Django records queries when DEBUG = True
        response = self.get_response(request)
        self._report(request, response, start, connection.queries[first_query:])
        return response

    def _report(self, request, response, start, queries):
        total_ms = (time.perf_counter() - start) * 1000
        db_ms = sum(float(q["time"]) for q in queries) * 1000
        print(f"[timing] {request.method} {request.path} {response.status_code} — "
              f"{total_ms:.0f} ms total, {len(queries)} queries ({db_ms:.0f} ms in the database)")
