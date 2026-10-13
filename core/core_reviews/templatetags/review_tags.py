# core_reviews/templatetags/review_tags.py
#   {% load review_tags %}
#   {% star_rating 4.3 %}                -> ★★★★☆ (the 5th star 30% filled)
#   {% star_rating 4.3 12 %}             -> ★★★★☆ 4.3 (12)
#   {% star_rating 4.3 12 size="lg" %}
from django import template
from django.utils.html import format_html, mark_safe

register = template.Library()


class StarRating:
    """Five stars filled up to `value` (out of 5), optionally with the number and review count."""

    STAR = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.8l2.8 5.8 6.3.9-4.6 4.4 1.1 6.3L12 17.2l-5.6 3 1.1-6.3L2.9 9.5l6.3-.9z"/></svg>'

    def __init__(self, value, count=None, size="sm"):
        self.value = float(value or 0)
        self.count = count
        self.size = size

    def _stars(self):
        stars = mark_safe(self.STAR * 5)
        return format_html(
            '<span class="stars stars--{}" role="img" aria-label="{} out of 5 stars">'
            '<span class="stars-empty">{}</span><span class="stars-fill" style="width: {}%">{}</span></span>',
            self.size, f"{self.value:.1f}", stars, round(self.value * 20, 1), stars,
        )

    def render(self):
        if self.count is None:
            return self._stars()
        return format_html(
            '<span class="star-rating star-rating--{}">{}<b>{}</b><small>({})</small></span>',
            self.size, self._stars(), f"{self.value:.1f}", self.count,
        )


@register.simple_tag
def star_rating(value, count=None, size="sm"):
    return StarRating(value, count, size).render()
