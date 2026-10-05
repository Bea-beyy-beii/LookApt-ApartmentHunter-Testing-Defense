# core_listings/templatetags/listing_tags.py
#   {% load listing_tags %}
#   {% feature_icon "pet_friendly" %}  -> inline SVG icon
from django import template

from core.core_listings.icons import icon_svg

register = template.Library()


@register.simple_tag
def feature_icon(name):
    return icon_svg(name)