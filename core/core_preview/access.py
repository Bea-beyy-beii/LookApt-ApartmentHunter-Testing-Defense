"""
Who may use the preview-only parts of other apps (e.g. the map in core_maps).

Opening /preview/renter/ or /preview/landlord/ marks the visitor's session, so
the map on those pages works without an account. Everything that saves data
still needs a real login.

    PreviewAccess(request).start()
    PreviewAccess(request).is_previewing
    PreviewAccess(request).allowed       signed in, or trying a preview
"""


class PreviewAccess:
    """The visitor's preview mark, kept in their session."""

    SESSION_KEY = "lookapt_preview"

    def __init__(self, request):
        self.request = request

    def start(self):
        self.request.session[self.SESSION_KEY] = True

    @property
    def is_previewing(self):
        return bool(self.request.session.get(self.SESSION_KEY))

    @property
    def allowed(self):
        return self.request.user.is_authenticated or self.is_previewing
