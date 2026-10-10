"""
python manage.py build_dark_theme

Writes core/static/core/css/theme/dark_auto.css: the dark-mode version of every
colour rule in the app's stylesheets, as  html[data-theme="dark"] <selector> { ... }.
Re-run it after changing colours in any stylesheet. Hand-picked touches
(sidebar, welcome heading, buttons) live in theme/dark.css, which loads after it.

How colours are turned dark:
  backgrounds  light -> dark navy surfaces (tinted ones keep their hue), navy stays navy
  text         dark  -> light (navy headings -> near white), white stays white
  borders      light -> dark lines, dark -> lighter lines
  shadows      -> black, a bit stronger
"""
import colorsys
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

OUTPUT = Path("core/static/core/css/theme/dark_auto.css")

# Same order the dashboard bases load them in, so later files still win
LOAD_ORDER = [
    "core/css/base/reset.css", "core/css/base/colors.css", "core/css/base/typography.css",
    "core/css/components/branding.css", "core/css/components/buttons.css", "core/css/components/forms.css",
    "core/css/components/sidebar.css", "core/css/pages/landlord_dashboard.css", "core/css/pages/renter_dashboard.css",
    "core_calendar/calendar.css", "core_inquiries/inquiries.css", "core_reports/reports.css",
    "core_listings/css/listings.css", "core_listings/css/property_form.css", "core_listings/css/steps.css",
    "core_maps/maps.css", "core_listings/css/photo_upload.css", "core_listings/css/review.css",
    "core_listings/css/property_card.css", "core_listings/css/unit_card.css", "core_listings/css/empty_state.css",
    "core/css/components/breadcrumbs.css", "core/css/components/toasts.css", "core/css/components/gallery.css",
    "core/css/components/feature_chips.css", "core/css/components/topbar_menus.css",
]
SKIP = {"login.css", "signup.css", "otp.css"}   # signed-out pages have no theme

VARIABLES = {
    "--navy": "#203a68", "--navy-dark": "#172f58", "--gold": "#f5b94c",
    "--cream": "#fffaf0", "--white": "#ffffff",
    "--text-primary": "#263a5c", "--text-secondary": "#69758a",
    "--border-light": "#d8e0e5", "--border-medium": "#a9afb6",
    "--error": "#c94b4b", "--success": "#3d8b5c",
}
NAMED = {"white": "#ffffff", "black": "#000000"}

# The two page surfaces from the sample: page background and cards
EXACT_BACKGROUNDS = {
    "#fffaf0": "#0b1424",   # --cream (page)
    "#ffffff": "#121d31",   # --white (cards)
    "#203a68": "#2b4a80",   # --navy buttons
    "#172f58": "#24406f",   # --navy-dark
}

PREFIX = 'html[data-theme="dark"]'
COLOR_RE = re.compile(
    r"#[0-9a-fA-F]{8}\b|#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3,4}\b"
    r"|rgba?\([^)]*\)"
    r"|var\(\s*--[\w-]+\s*(?:,[^)]*)?\)"
    r"|\b(?:white|black)\b"
)


# ------------------------------------------------------------------ colour maths

def parse(token):
    """'#abc' / 'rgba(1,2,3,.5)' / 'var(--navy)' / 'white' -> (r, g, b, a) in 0..1, or None."""
    token = token.strip()
    if token.startswith("var("):
        name = re.match(r"var\(\s*(--[\w-]+)", token).group(1)
        return parse(VARIABLES[name]) if name in VARIABLES else None
    if token in NAMED:
        return parse(NAMED[token])
    if token.startswith("#"):
        h = token[1:]
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1
        return int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, a
    parts = [p.strip() for p in re.split(r"[,/\s]+", token[token.index("(") + 1:-1].strip()) if p.strip()]
    if len(parts) < 3:
        return None
    try:
        r, g, b = (float(p.rstrip("%")) / (100 if p.endswith("%") else 255) for p in parts[:3])
        a = float(parts[3].rstrip("%")) / (100 if parts[3].endswith("%") else 1) if len(parts) > 3 else 1
    except ValueError:
        return None
    return r, g, b, a


def fmt(r, g, b, a=1):
    r, g, b = (max(0, min(255, round(v * 255))) for v in (r, g, b))
    if a >= 1:
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"rgba({r}, {g}, {b}, {round(a, 3)})"


def hls(r, g, b):
    return colorsys.rgb_to_hls(r, g, b)


def from_hls(h, l, s):
    return colorsys.hls_to_rgb(h, max(0, min(1, l)), max(0, min(1, s)))


NAVY_HUE = 218 / 360


def is_navy(h, l, s):
    return 0.55 < h < 0.67 and l < 0.42 and s > 0.25


def chroma(l, s):
    return (1 - abs(2 * l - 1)) * s


def dark_background(rgba):
    r, g, b, a = rgba
    key = fmt(r, g, b)
    if a >= 1 and key in EXACT_BACKGROUNDS:
        return EXACT_BACKGROUNDS[key]
    h, l, s = hls(r, g, b)
    if a < 1:
        if l > 0.85:                      # white veil -> card-coloured veil
            return fmt(*parse(EXACT_BACKGROUNDS["#ffffff"])[:3], a)
        if a <= 0.2 and l < 0.5:          # faint dark tint (hover) -> faint light tint
            return fmt(*from_hls(h, 0.78, min(s, 0.6)), a)
        return None                       # backdrops etc. stay
    if l > 0.85:                          # light surface -> dark surface
        warm = 25 / 360 < h < 60 / 360    # creams / beiges would turn brown
        if chroma(l, s) < 0.045 or (warm and chroma(l, s) < 0.13):
            return fmt(*from_hls(NAVY_HUE, min(0.13 + (1 - l) * 1.4, 0.2), 0.45))
        return fmt(*from_hls(h, 0.17 + (1 - l) * 0.3, min(s, 0.5)))
    if is_navy(h, l, s):
        return fmt(*from_hls(h, max(l, 0.33), s))
    if 0.6 < l <= 0.85 and s < 0.25:      # light greys (disabled, tracks)
        return fmt(*from_hls(NAVY_HUE, 0.24, 0.3))
    return None                           # gold, red, green buttons keep their colour


def light_text(rgba):
    r, g, b, a = rgba
    h, l, s = hls(r, g, b)
    if is_navy(h, l, s) or (l < 0.45 and s < 0.35):
        return fmt(*from_hls(NAVY_HUE, 0.92, 0.45), a)        # headings / body text
    if l < 0.62 and s < 0.3:
        return fmt(*from_hls(NAVY_HUE, 0.68, 0.18), a)        # secondary text
    if l < 0.55:
        return fmt(*from_hls(h, 0.68, min(s, 0.75)), a)       # coloured text (green, red, blue)
    if l > 0.9:
        return None                                           # white on buttons stays
    return None


def dark_border(rgba):
    r, g, b, a = rgba
    h, l, s = hls(r, g, b)
    if l > 0.75:
        if chroma(l, s) < 0.15:           # warm / cool greys -> neutral dark line
            return fmt(*from_hls(NAVY_HUE, 0.22, 0.32), a)
        return fmt(*from_hls(h, 0.3, min(s, 0.45)), a)
    if is_navy(h, l, s):
        return fmt(*from_hls(h, 0.5, 0.4), a)
    if l < 0.4 and a < 1:                                     # faint dark lines
        return fmt(*from_hls(NAVY_HUE, 0.75, 0.3), a)
    return None


def dark_shadow(rgba):
    r, g, b, a = rgba
    h, l, s = hls(r, g, b)
    if s > 0.6 and 0.3 < l < 0.8:
        return None                                           # coloured glows (gold) stay
    if l > 0.85:
        return "rgba(0, 0, 0, 0)"                             # light glows disappear
    return fmt(0, 0, 0, min(0.55, a * 2.2))


ROLES = {
    "background": dark_background, "background-color": dark_background, "background-image": dark_background,
    "color": light_text, "fill": light_text, "stroke": dark_border, "caret-color": light_text,
    "-webkit-text-fill-color": light_text, "text-decoration-color": light_text, "accent-color": None,
    "box-shadow": dark_shadow, "text-shadow": dark_shadow, "filter": dark_shadow,
}


def role_for(prop):
    if prop in ROLES:
        return ROLES[prop]
    if prop.startswith(("border", "outline", "column-rule")):
        return dark_border
    return None


def role_for_variable(name, value):
    """Local colour variables (--card-bg, --cat, --warning-light ...): guess the role from the name."""
    if "shadow" in name:
        return dark_shadow
    if "border" in name or "line" in name:
        return dark_border
    if re.search(r"bg|background|light|surface|soft|tint", name):
        return dark_background
    colors = COLOR_RE.findall(value)
    if len(colors) != 1 or not parse(colors[0]):
        return None
    _, l, _ = hls(*parse(colors[0])[:3])
    return dark_background if l > 0.85 else light_text


def convert(prop, value):
    convert_one = role_for_variable(prop, value) if prop.startswith("--") else role_for(prop)
    if not convert_one:
        return None
    changed = False

    def swap(match):
        nonlocal changed
        token = match.group(0)
        rgba = parse(token)
        if rgba is None:
            return token
        new = convert_one(rgba)
        if new is None and token.startswith("var("):
            # dark.css redefines the root colours for dark mode; pin the
            # light value here so e.g. white text on a navy button stays white
            new = fmt(*rgba)
        if new is None or new == token:
            return token
        changed = True
        return new

    new_value = COLOR_RE.sub(swap, value)
    if changed:
        return new_value
    # Unchanged colours are repeated too: every colour rule gets the same
    # html[data-theme] boost, so the original cascade order still holds
    # (otherwise a converted base rule would beat an untouched modifier rule)
    return value if any(parse(t) for t in COLOR_RE.findall(value)) else None


# ------------------------------------------------------------------ CSS parsing

def strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def matching_brace(css, start):
    depth = 0
    for i in range(start, len(css)):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return len(css) - 1


def split_top(text, sep):
    parts, depth, current = [], 0, ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    parts.append(current)
    return [p.strip() for p in parts if p.strip()]


def prefix(selector):
    out = []
    for sel in split_top(selector, ","):
        if sel.startswith(":root"):
            out.append(PREFIX + sel[5:])
        elif re.match(r"html\b", sel):
            out.append(PREFIX + sel[4:])
        else:
            out.append(f"{PREFIX} {sel}")
    return ",\n".join(out)


def family(prop):
    head = prop.split("-")[0]
    return head if head in ("background", "border", "outline") else None


def walk(css, indent=""):
    """Yield the dark-mode CSS for one block of rules."""
    pos = 0
    while True:
        open_at = css.find("{", pos)
        if open_at == -1:
            return
        prelude = css[pos:open_at].strip().split(";")[-1].strip()   # skip stray @import / @charset
        close_at = matching_brace(css, open_at)
        body = css[open_at + 1:close_at]
        pos = close_at + 1

        if prelude.startswith(("@media", "@supports")):
            inner = "".join(walk(body, indent + "    "))
            if inner:
                yield f"{indent}{prelude} {{\n{inner}{indent}}}\n\n"
            continue
        if prelude.startswith("@"):
            continue                       # @keyframes, @font-face ...

        parsed = []                        # (prop, original value, dark value or None)
        for decl in split_top(body, ";"):
            if ":" not in decl:
                continue
            prop, value = decl.split(":", 1)
            prop = prop.strip() if prop.strip().startswith("--") else prop.strip().lower()
            if prop.startswith("--") and (prelude.startswith(":root") or "var(" in value):
                continue                   # root colours: dark.css redefines them by hand; aliases follow them
            parsed.append((prop, value.strip(), convert(prop, value.strip())))

        # A re-emitted shorthand (background: ...) resets the rule's longhands
        # (background-size ...), so the whole family is repeated in order
        families = {family(prop) for prop, _, new in parsed if new and family(prop)}
        declarations = [
            f"{indent}    {prop}: {new or value};"
            for prop, value, new in parsed
            if new or family(prop) in families
        ]
        if declarations:
            selector = prefix(prelude).replace("\n", "\n" + indent)
            yield f"{indent}{selector} {{\n" + "\n".join(declarations) + f"\n{indent}}}\n\n"


class Command(BaseCommand):
    help = "Generate core/static/core/css/theme/dark_auto.css from the app's stylesheets."

    def handle(self, *args, **options):
        base = Path(settings.BASE_DIR)
        files = {}
        for path in sorted(base.glob("core/**/static/**/*.css")):
            if "theme" in path.parts or path.name in SKIP:
                continue
            files[path.relative_to(base).as_posix().split("/static/", 1)[1]] = path
        ordered = [name for name in LOAD_ORDER if name in files] + sorted(set(files) - set(LOAD_ORDER))
        sources = {name: strip_comments(files[name].read_text(encoding="utf-8")) for name in ordered}

        # Know the local colour variables too, so  background: var(--card-bg)  converts.
        # One set per category (--cat in the calendar) can't be pinned to one value:
        # those follow their own (converted) definitions instead.
        local = {}
        for css in sources.values():
            for name, value in re.findall(r"(--[\w-]+)\s*:\s*([^;{}]+)", css):
                local.setdefault(name, set()).add(value.strip())
        for name, values in local.items():
            value = next(iter(values))
            if name not in VARIABLES and len(values) == 1 and COLOR_RE.fullmatch(value):
                VARIABLES[name] = value

        chunks = [
            "/* GENERATED by `python manage.py build_dark_theme`. Don't edit by hand:\n"
            "   re-run the command after changing colours. Hand-tuned bits: theme/dark.css */\n\n",
        ]
        for name in ordered:
            rules = "".join(walk(sources[name]))
            if rules:
                chunks.append(f"/* ===== {name} ===== */\n\n{rules}")

        out = base / OUTPUT
        out.write_text("".join(chunks).rstrip() + "\n", encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Wrote {OUTPUT} from {len(ordered)} stylesheets."))