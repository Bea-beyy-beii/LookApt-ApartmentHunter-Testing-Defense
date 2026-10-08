# core/storage.py
# Static files in production (WhiteNoise): compressed, with a fingerprint in
# each file name so browsers can cache them for a long time.
#
# Django's default refuses to render a page that links a static file that
# doesn't exist ("Missing staticfiles manifest entry" = 500 error). Here a
# missing file only logs a warning and the page still loads (that one image
# or script is just missing), like during development.
import logging

from django.contrib.staticfiles.storage import StaticFilesStorage
from whitenoise.storage import CompressedManifestStaticFilesStorage

logger = logging.getLogger(__name__)


class StaticStorage(CompressedManifestStaticFilesStorage):

    def url(self, name, force=False):
        try:
            return super().url(name, force)
        except ValueError:
            logger.warning("Static file not found: %s (check the {%% static %%} path)", name)
            return StaticFilesStorage.url(self, name)