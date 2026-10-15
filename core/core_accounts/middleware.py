from django.http import Http404


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