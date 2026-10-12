"""
Who may use the preview-only parts of other apps (e.g. the map in core_maps).

Opening /preview/renter/ or /preview/landlord/ marks the visitor's session, so
the map on those pages works without an account. Everything that saves data
still needs a real login.
"""
PREVIEW_SESSION_KEY = "lookapt_preview"


def start_preview(request):
    request.session[PREVIEW_SESSION_KEY] = True


def is_previewing(request):
    return bool(request.session.get(PREVIEW_SESSION_KEY))


def signed_in_or_previewing(request):
    return request.user.is_authenticated or is_previewing(request)
