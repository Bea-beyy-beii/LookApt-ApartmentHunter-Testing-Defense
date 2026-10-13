# core_listings/templatetags/listing_tags.py
#   {% load listing_tags %}
#   {% feature_icon "pet_friendly" %}  -> inline SVG icon
#   {% if complex|admits:user %}        -> the renter fits the sex restriction
from django import template

from core.core_listings.icons import Icon

register = template.Library()


@register.simple_tag
def feature_icon(name):
    return Icon(name).svg()


@register.filter
def admits(complex_obj, user):
    return complex_obj.admits(user)
