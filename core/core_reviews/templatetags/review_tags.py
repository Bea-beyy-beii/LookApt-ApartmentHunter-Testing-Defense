# core_reviews/templatetags/review_tags.py
#   {% load review_tags %}
#   {% star_rating 4.3 %}                -> ★★★★☆ (the 5th star 30% filled)
#   {% star_rating 4.3 12 %}             -> ★★★★☆ 4.3 (12)
#   {% star_rating 4.3 12 size="lg" %}
from django import template
from django.utils.html import format_html, mark_safe

register = template.Library()

STAR = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.8l2.8 5.8 6.3.9-4.6 4.4 1.1 6.3L12 17.2l-5.6 3 1.1-6.3L2.9 9.5l6.3-.9z"/></svg>'


@register.simple_tag
def star_rating(value, count=None, size="sm"):
    value = float(value or 0)
    stars = mark_safe(STAR * 5)
    html = format_html(
        '<span class="stars stars--{}" role="img" aria-label="{} out of 5 stars">'
        '<span class="stars-empty">{}</span><span class="stars-fill" style="width: {}%">{}</span></span>',
        size, f"{value:.1f}", stars, round(value * 20, 1), stars,
    )
    if count is None:
        return html
    return format_html(
        '<span class="star-rating star-rating--{}">{}<b>{}</b><small>({})</small></span>',
        size, html, f"{value:.1f}", count,
    )
