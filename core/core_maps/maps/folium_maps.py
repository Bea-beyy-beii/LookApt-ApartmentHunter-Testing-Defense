# core_maps/maps/folium_maps.py
# Builds the Folium (Leaflet) map that is shown inside an <iframe>.
#
# Clicking the map does not reload anything by itself: a small script
# (ClickBridge) sends the clicked lat/lng to the parent page with
# window.postMessage. The parent page then calls the JSON API and reloads
# the iframe with the new point / radius so Folium redraws everything.
import folium
from branca.element import MacroElement
from jinja2 import Template
from markupsafe import escape

from .categories import COMPLEX_STYLE, svg
from .geo import DEFAULT_CENTER, bounding_box

PIN_COLOR = "#203a68"
RADIUS_COLOR = "#f5b94c"


class ClickBridge(MacroElement):
    """Sends map clicks to the parent window (the page that holds the iframe)."""

    _template = Template("""
        {% macro script(this, kwargs) %}
            (function () {
                var map = {{ this._parent.get_name() }};
                map.getContainer().style.cursor = "crosshair";
                map.on("click", function (e) {
                    window.parent.postMessage({
                        type: "lookapt:map-click",
                        lat: e.latlng.lat,
                        lng: e.latlng.lng
                    }, window.location.origin);
                });
            })();
        {% endmacro %}
    """)

    def __init__(self):
        super().__init__()
        self._name = "ClickBridge"


class FitRadius(MacroElement):
    """Zoom so the whole radius circle is visible, and keep it that way when
    the iframe is resized (e.g. it was laid out while a wizard step was hidden)."""

    _template = Template("""
        {% macro script(this, kwargs) %}
            (function () {
                var map = {{ this._parent.get_name() }};
                var bounds = {{ this.bounds|tojson }};
                function fit() {
                    map.invalidateSize();
                    // A hidden iframe has no size yet; "resize" fires once it is shown
                    var size = map.getSize();
                    if (!size.x || !size.y) return;
                    map.fitBounds(bounds, {padding: [16, 16]});
                }
                fit();
                window.addEventListener("load", fit);
                window.addEventListener("resize", fit);
            })();
        {% endmacro %}
    """)

    def __init__(self, bounds):
        super().__init__()
        self._name = "FitRadius"
        self.bounds = bounds


def _pin_icon():
    return folium.DivIcon(
        icon_size=(34, 44),
        icon_anchor=(17, 42),
        html=(
            f'<svg viewBox="0 0 24 30" width="34" height="44">'
            f'<path d="M12 29s10-9.3 10-17A10 10 0 0 0 2 12c0 7.7 10 17 10 17z" fill="{PIN_COLOR}" stroke="#fff" stroke-width="1.5"/>'
            f'<circle cx="12" cy="12" r="4" fill="#fff"/></svg>'
        ),
    )


def _badge_icon(style, size=30):
    return folium.DivIcon(
        icon_size=(size, size),
        icon_anchor=(size // 2, size // 2),
        html=(
            f'<div style="width:{size}px;height:{size}px;border-radius:50%;display:grid;place-items:center;'
            f'background:{style["bg"]};color:{style["color"]};border:2px solid {style["color"]};'
            f'box-shadow:0 2px 6px rgba(0,0,0,.25)">{svg(style["icon"], size=size - 14, stroke_width=2.2)}</div>'
        ),
    )


def build_map(lat=None, lng=None, radius_km=None, landmarks=(), complexes=(), editable=True, label="Selected Location"):
    """Return the full HTML document of the map."""
    has_point = lat is not None and lng is not None

    fmap = folium.Map(
        location=(lat, lng) if has_point else DEFAULT_CENTER,
        zoom_start=15 if has_point else 13,
        tiles="OpenStreetMap",
        control_scale=True,
    )

    if has_point:
        if radius_km:
            folium.Circle(
                location=(lat, lng),
                radius=radius_km * 1000,
                color=RADIUS_COLOR,
                weight=2,
                fill=True,
                fill_color=RADIUS_COLOR,
                fill_opacity=0.12,
                interactive=False,
            ).add_to(fmap)

            min_lat, max_lat, min_lng, max_lng = bounding_box(lat, lng, radius_km)
            fmap.add_child(FitRadius([[min_lat, min_lng], [max_lat, max_lng]]))

        for item in landmarks:
            tooltip = f'{escape(item["name"])}<br><small>{item["distance_label"]} · ~{item["minutes"]} min</small>'
            folium.Marker(
                location=(item["lat"], item["lng"]),
                icon=_badge_icon(item, size=28),
                tooltip=tooltip,
            ).add_to(fmap)

        for item in complexes:
            popup = (
                f'<b>{escape(item["name"])}</b><br>{escape(item["address"])}<br>'
                f'₱{item["min_price"]:,.0f} – ₱{item["max_price"]:,.0f} / month<br>'
                f'{item["distance_label"]} · ~{item["minutes"]} min'
            )
            if item.get("url"):
                # target=_top: the map is inside an iframe, open the page in the real tab
                popup += f'<br><a href="{escape(item["url"])}" target="_top" style="font-weight:600">View listing →</a>'
            folium.Marker(
                location=(item["lat"], item["lng"]),
                icon=_badge_icon(COMPLEX_STYLE, size=34),
                tooltip=escape(item["name"]),
                popup=folium.Popup(popup, max_width=260),
            ).add_to(fmap)

        folium.Marker(
            location=(lat, lng),
            icon=_pin_icon(),
            tooltip=folium.Tooltip(f"<b>{escape(label)}</b>", permanent=True, direction="top", offset=(0, -40)),
            z_index_offset=1000,
        ).add_to(fmap)

    if editable:
        fmap.add_child(ClickBridge())

    return fmap.get_root().render()
