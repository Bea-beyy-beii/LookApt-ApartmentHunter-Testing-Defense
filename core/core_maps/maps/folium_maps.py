# core_maps/maps/folium_maps.py
# Builds the Folium (Leaflet) map that is shown inside an <iframe>.
#
# Clicking the map does not reload anything by itself: a small script
# (ClickBridge) sends the clicked lat/lng to the parent page with
# window.postMessage. The parent page then calls the JSON API and reloads
# the iframe with the new point / radius so Folium redraws everything.
#
# While the parent waits for the API, it posts {type: "lookapt:scan"} back
# and ScanRadius draws the new circle right away with a radar sweep
# (also played once when a map with a radius loads).
import folium
from branca.element import MacroElement
from jinja2 import Template
from markupsafe import escape

from .categories import COMPLEX_STYLE, svg
from .geo import DEFAULT_CENTER, bounding_box

PIN_COLOR = "#203a68"
RADIUS_COLOR = "#f5b94c"

# Folium loads jQuery, Bootstrap, Font Awesome and Awesome Markers by default
# (10 files on every iframe load). These maps only use Leaflet, plus jQuery
# where there are pop-ups (folium builds pop-up content with it).
LEAFLET_JS = [("leaflet", "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js")]
JQUERY_JS = [("jquery", "https://code.jquery.com/jquery-3.7.1.min.js")]
LEAFLET_CSS = [("leaflet_css", "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.css")]


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


class ScanRadius(MacroElement):
    """Radar sweep around the pin.

    - On load (when the map has a radius): the circle grows from the pin and a
      sweep goes round once, then the plain circle stays.
    - {type: "lookapt:scan", lat, lng, radius_m} from the parent page: the new
      circle is drawn at once and the sweep keeps turning until the parent
      reloads the iframe with the results.
    """

    _template = Template("""
        {% macro script(this, kwargs) %}
            (function () {
                var map = {{ this._parent.get_name() }};
                var color = {{ this.color|tojson }};
                var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
                var layers = [], frame = null;

                function clear() {
                    if (frame) cancelAnimationFrame(frame);
                    frame = null;
                    layers.forEach(function (layer) { map.removeLayer(layer); });
                    layers = [];
                }

                // A slice of the circle from `start` degrees, `width` degrees wide
                function wedge(center, radius, start, width) {
                    var points = [center], R = 6371000;
                    var lat = center[0] * Math.PI / 180, lng = center[1] * Math.PI / 180;
                    for (var i = 0; i <= 12; i++) {
                        var bearing = (start + width * i / 12) * Math.PI / 180, d = radius / R;
                        var lat2 = Math.asin(Math.sin(lat) * Math.cos(d) + Math.cos(lat) * Math.sin(d) * Math.cos(bearing));
                        var lng2 = lng + Math.atan2(Math.sin(bearing) * Math.sin(d) * Math.cos(lat),
                                                    Math.cos(d) - Math.sin(lat) * Math.sin(lat2));
                        points.push([lat2 * 180 / Math.PI, lng2 * 180 / Math.PI]);
                    }
                    return points;
                }

                // keep: the sweep never stops (waiting for results); otherwise one turn
                function scan(center, radius, keep, showCircle) {
                    clear();
                    if (showCircle) {
                        layers.push(L.circle(center, {radius: radius, color: color, weight: 2, fillColor: color,
                                                      fillOpacity: 0.08, interactive: false}).addTo(map));
                        layers.push(L.circleMarker(center, {radius: 6, color: "#fff", weight: 2, fillColor: "#203a68",
                                                            fillOpacity: 1, interactive: false}).addTo(map));
                    }
                    if (reduce) return;
                    var sweep = L.polygon(wedge(center, radius, 0, 40), {stroke: false, fillColor: color,
                                                                          fillOpacity: 0.35, interactive: false}).addTo(map);
                    var ring = L.circle(center, {radius: 1, color: color, weight: 2, fill: false, interactive: false}).addTo(map);
                    layers.push(sweep, ring);
                    var started = performance.now();
                    function step(now) {
                        var t = (now - started) / 1400;               // one turn every 1.4 s
                        if (!keep && t >= 1) { map.removeLayer(sweep); map.removeLayer(ring); return; }
                        sweep.setLatLngs(wedge(center, radius, (t % 1) * 360, 40));
                        ring.setRadius(radius * ((t * 1.4) % 1));     // a ring pulsing outwards
                        ring.setStyle({opacity: 1 - ((t * 1.4) % 1)});
                        frame = requestAnimationFrame(step);
                    }
                    frame = requestAnimationFrame(step);
                }

                {% if this.center %}
                    // First load: grow the radius in with one sweep
                    scan({{ this.center|tojson }}, {{ this.radius }}, false, false);
                {% endif %}

                // "Pick on map" for a hand-added landmark: mark the chosen spot
                var mark = null;
                window.addEventListener("message", function (event) {
                    if (event.origin !== window.location.origin || !event.data) return;
                    if (event.data.type !== "lookapt:mark") return;
                    if (mark) map.removeLayer(mark);
                    mark = L.circleMarker([event.data.lat, event.data.lng], {radius: 9, color: "#203a68", weight: 3,
                                                                             fillColor: "#f5b94c", fillOpacity: 1}).addTo(map);
                });

                window.addEventListener("message", function (event) {
                    if (event.origin !== window.location.origin || !event.data) return;
                    if (event.data.type !== "lookapt:scan") return;
                    var center = [event.data.lat, event.data.lng], radius = event.data.radius_m;
                    map.eachLayer(function (layer) {
                        // Hide the old pin, circle and markers: they belong to the previous point
                        if (layer instanceof L.Marker || (layer instanceof L.Circle && layers.indexOf(layer) < 0)) map.removeLayer(layer);
                    });
                    var bounds = L.latLng(center).toBounds(radius * 2);
                    map.fitBounds(bounds, {padding: [16, 16], animate: true});
                    scan(center, radius, true, true);
                });
            })();
        {% endmacro %}
    """)

    def __init__(self, center=None, radius_m=0, color=RADIUS_COLOR):
        super().__init__()
        self._name = "ScanRadius"
        self.center = list(center) if center else None
        self.radius = radius_m
        self.color = color


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
    fmap.default_js = LEAFLET_JS + (JQUERY_JS if complexes else [])    # complexes have pop-ups
    fmap.default_css = LEAFLET_CSS

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

    # Radar sweep: once on load, and while the parent page waits for new results
    has_radius = has_point and radius_km
    fmap.add_child(ScanRadius((lat, lng) if has_radius else None, radius_km * 1000 if has_radius else 0))

    return fmap.get_root().render()
