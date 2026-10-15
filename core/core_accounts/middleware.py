from django.http import Http404
from django.utils.cache import add_never_cache_headers


class HideAdminMiddleware:
    """Django's built-in admin (/lookapt-manage/) doesn't exist for anyone but staff:
    visitors and scanning tools get a plain 404, not a login page to guess passwords on.
    Staff log in on the normal /login/ page first, then open /lookapt-manage/."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/lookapt-manage/'):
            user = request.user
            if not (user.is_authenticated and user.is_staff):
                raise Http404
        return self.get_response(request)

class NoCacheWhenLoggedInMiddleware:
    """Pages shown to a logged-in user are never stored by the browser.
    Without this, pressing Back after logging out shows the account's pages
    again from the browser's memory (the session is gone, but the copy isn't)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.user.is_authenticated and 'Cache-Control' not in response:
            add_never_cache_headers(response)    # no-cache, no-store, must-revalidate, private
        return response
