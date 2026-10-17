"""
The parent of LookApt's middleware (core_accounts/middleware.py, dev_timing.py).

Django builds each middleware once with the next step of the chain
(get_response), then calls the object for every request.
"""
from abc import ABC, abstractmethod


class Middleware(ABC):

    def __init__(self, get_response):
        self.get_response = get_response

    @abstractmethod
    def __call__(self, request):
        """Handle one request (call self.get_response(request) to go on)."""
