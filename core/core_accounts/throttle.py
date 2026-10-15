"""
Rate limits: "too many tries, please wait a bit".

They stop tools that send thousands of requests (password guessing, ffuf-style
fuzzing, scripts hammering the search). The counts live in the cache, so
nothing is written to the database.

    RateLimit        one counter: N tries per key within a time window
    LoginAttempts    the log-in page's guard (per account + per IP address)
    RateLimitMixin   for class-based views: every request of one IP is counted

Settings: RATE_LIMITS = False turns them all off (a staging copy for a stress
test, where every request comes from the same machine).
"""
import hashlib
import math
import time

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse


class RateLimit:
    """At most `limit` tries per `key` within `window` seconds (counted from the first try)."""

    def __init__(self, scope, key, limit, window):
        self.limit = limit
        self.window = window
        # Hashed: the cache never holds an email address or IP in plain text
        digest = hashlib.sha256(str(key).strip().lower().encode()).hexdigest()[:32]
        self.cache_key = f"ratelimit:{scope}:{digest}"

    @staticmethod
    def enabled():
        return getattr(settings, "RATE_LIMITS", True)

    def _state(self):
        """(tries so far, when the window ends)."""
        return cache.get(self.cache_key) or (0, time.time() + self.window)

    @property
    def blocked(self):
        return self.enabled() and self._state()[0] >= self.limit

    @property
    def minutes_left(self):
        return max(1, math.ceil((self._state()[1] - time.time()) / 60))

    def hit(self):
        if not self.enabled():
            return
        count, until = self._state()
        cache.set(self.cache_key, (count + 1, until), timeout=max(1, math.ceil(until - time.time())))

    def reset(self):
        cache.delete(self.cache_key)

    @staticmethod
    def client_ip(request):
        """The visitor's address. Behind Render's proxy it's the first one in X-Forwarded-For."""
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        return forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")


class LoginAttempts:
    """The log-in page's guard against password guessing.
    5 wrong passwords for one account, or 30 from one IP address (many accounts),
    and log-in is paused for 15 minutes."""

    PER_ACCOUNT = 5
    PER_IP = 30
    WINDOW = 15 * 60

    def __init__(self, request, identifier):
        self._account = RateLimit("login-account", identifier, self.PER_ACCOUNT, self.WINDOW)
        self._ip = RateLimit("login-ip", RateLimit.client_ip(request), self.PER_IP, self.WINDOW)

    @property
    def _blocking(self):
        return next((limit for limit in (self._account, self._ip) if limit.blocked), None)

    @property
    def blocked(self):
        return self._blocking is not None

    @property
    def message(self):
        minutes = self._blocking.minutes_left if self._blocking else self.WINDOW // 60
        return (f"Too many failed log-in attempts. Please try again in {minutes} minute{'s' if minutes != 1 else ''}, "
                f"or use Forgot password.")

    def failed(self):
        self._account.hit()
        self._ip.hit()

    def succeeded(self):
        self._account.reset()


class RateLimitMixin:
    """For a class-based view: at most `rate_limit` requests per IP address within
    `rate_window` seconds (only for the methods in `rate_methods`). Over the
    limit, rate_limited() answers instead of the view: by default a 429 JSON."""

    rate_scope = ""              # defaults to the view's class name
    rate_limit = 120
    rate_window = 60
    rate_methods = ("GET", "POST")
    rate_message = "Too many requests. Please wait a minute and try again."

    def dispatch(self, request, *args, **kwargs):
        if request.method in self.rate_methods:
            limit = RateLimit(self.rate_scope or type(self).__name__, RateLimit.client_ip(request),
                              self.rate_limit, self.rate_window)
            if limit.blocked:
                return self.rate_limited(limit)
            limit.hit()
        return super().dispatch(request, *args, **kwargs)

    def rate_limited(self, limit):
        return JsonResponse({"error": self.rate_message, "errors": {"__all__": self.rate_message}}, status=429)