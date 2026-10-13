// =========================================================
// LookApt map picker (core_maps)
//
// The map itself is a Folium map rendered by Django inside an <iframe>.
// When the user clicks it, the iframe posts {type: "lookapt:map-click"}
// to this page. We then:
//   1. tell the iframe to draw the new radius with a radar sweep (lookapt:scan)
//   2. call the JSON API (landmarks for landlords, complexes for renters)
//   3. render the side panel
//   4. reload the iframe so Folium redraws the pin, radius and markers
// Landlords can also add landmarks by hand (name + category + a spot on the
// map) and find the pin from the typed address.
// =========================================================

(function () {

    const MODE_ICONS = {
        walking: '<svg class="lk-mode-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="13" cy="4" r="1.6"/><path d="M10 21l2-6 2.5 2.5V21M8 12l2.5-4.5 3 1 2 3.5 2.5 1M10.5 7.5 9 13"/></svg>',
        commute: '<svg class="lk-mode-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="6" width="18" height="10" rx="2"/><path d="M3 11h18M7 6V4h10v2"/><circle cx="7.5" cy="18" r="1.6"/><circle cx="16.5" cy="18" r="1.6"/></svg>',
        driving: '<svg class="lk-mode-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 16V11l2-5h10l2 5v5M3 16h18v2H3z"/><circle cx="7.5" cy="16.5" r="1.5"/><circle cx="16.5" cy="16.5" r="1.5"/><path d="M5 11h14"/></svg>',
    };

    const MODE_WORDS = { walking: "walk", commute: "commute", driving: "drive" };

    // Same numbers as core_maps/maps/geo.py (travel time from a straight-line distance)
    const SPEED_KMH = { walking: 4.8, commute: 15, driving: 25 };
    const ROAD_DETOUR = 1.3;

    function haversineM(lat1, lng1, lat2, lng2) {
        const rad = Math.PI / 180, R = 6371000;
        const dLat = (lat2 - lat1) * rad, dLng = (lng2 - lng1) * rad;
        const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLng / 2) ** 2;
        return 2 * R * Math.asin(Math.sqrt(a));
    }

    function minutesFor(distanceM, mode) {
        return Math.max(1, Math.round(distanceM * ROAD_DETOUR / 1000 / SPEED_KMH[mode] * 60));
    }

    // Distance / time fields like the API's (_travel_info in services.py)
    function travelInfo(distanceM, mode) {
        const minutesByMode = {};
        Object.keys(SPEED_KMH).forEach(m => { minutesByMode[m] = minutesFor(distanceM, m); });
        return {
            distance_m: Math.round(distanceM),
            distance_km: Math.round(distanceM / 100) / 10,
            distance_label: distanceM < 1000 ? `${Math.max(10, Math.round(distanceM / 10) * 10)} m` : `${(distanceM / 1000).toFixed(1)} km`,
            minutes: minutesByMode[mode],
            minutes_by_mode: minutesByMode,
        };
    }

    function readJSON(selector, scope) {
        const node = (scope || document).querySelector(selector);
        if (!node) return null;
        try { return JSON.parse(node.textContent); } catch (error) { return null; }
    }

    const BUILDING_ICON = '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 21h18M5 21V7l7-4 7 4v14"/><path d="M9 10h1M14 10h1M9 14h1M14 14h1M10 21v-3h4v3"/></svg>';

    const peso = new Intl.NumberFormat("en-PH", { maximumFractionDigits: 0 });


    // ---------------------------------------------------------
    // Small DOM helper (always uses textContent for user/OSM data)
    // ---------------------------------------------------------

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function debounce(fn, wait) {
        let timer;
        return (...args) => {
            clearTimeout(timer);
            timer = setTimeout(() => fn(...args), wait);
        };
    }


    class LookAptMap {

        constructor(root) {
            this.root = root;
            this.kind = root.dataset.kind;                 // "landlord" | "renter"
            this.editable = root.dataset.editable === "1";
            this.urls = {
                frame: root.dataset.frameUrl,
                landmarks: root.dataset.landmarksUrl,
                complexes: root.dataset.complexesUrl,
                search: root.dataset.searchUrl,
                reverse: root.dataset.reverseUrl,
            };

            this.state = {
                lat: parseFloat(root.dataset.lat) || null,
                lng: parseFloat(root.dataset.lng) || null,
                radius: parseFloat(root.dataset.radius) || 3,
                mode: root.dataset.mode || "walking",
                minutes: null,
                label: root.dataset.label || "",
            };

            this.landmarks = [];     // from the API (OpenStreetMap + our saved ones)
            this.manual = [];        // added by the landlord by hand
            this.removed = new Set();
            this.requestId = 0;
            this.frameDirty = true;
            this.picking = null;     // "pick on map" for a manual landmark

            this.frame = root.querySelector(".lk-map-frame");
            this.status = root.querySelector(".lk-map-status");
            this.results = root.dataset.results ? document.querySelector(root.dataset.results) : null;
            this.summary = root.dataset.results ? document.querySelector(root.dataset.results + "-summary") : null;
            this.form = root.closest("form");

            this.bindControls();
            this.bindFrameMessages();
            this.watchVisibility();
            this.updateRadiusHints();
            this.bindManual();
            this.bindAddressSearch();

            // Editing a property: start from its saved landmarks (no waiting for
            // OpenStreetMap, and nothing is lost if it's down). The landmarks are
            // only looked up again when the pin, radius or travel time changes.
            const saved = this.editable && this.kind === "landlord" ? readJSON(`#${root.id}-saved`) : null;
            if (saved && saved.length) {
                this.state.mode = saved[0].travel_mode || this.state.mode;
                this.markActive(".lk-mode-chip", chip => chip.dataset.mode === this.state.mode);
                this.updateRadiusHints();
                this.manual = saved.filter(item => item.manual);
                this.landmarks = saved.filter(item => !item.manual);
                this.loaded = true;
                this.useSaved = true;
                this.renderLandmarks();
                // Let the wizard's Review map show them too
                setTimeout(() => this.root.dispatchEvent(new CustomEvent("lookapt:map-change", { bubbles: true, detail: this.snapshot() })));
            } else if (this.hasPoint() && this.editable) {
                this.fetchResults();
            }
        }

        hasPoint() {
            return this.state.lat !== null && this.state.lng !== null;
        }


        // ---------------------------------------------------------
        // Controls
        // ---------------------------------------------------------

        bindControls() {
            this.root.querySelectorAll(".lk-mode-chip").forEach(chip => {
                chip.addEventListener("click", () => this.setMode(chip.dataset.mode));
            });

            this.root.querySelectorAll(".lk-radius-chip").forEach(chip => {
                chip.addEventListener("click", () => this.setRadius(parseFloat(chip.dataset.km)));
            });

            const minutes = this.root.querySelector(".lk-minutes-select");
            if (minutes) {
                minutes.addEventListener("change", () => {
                    this.state.minutes = minutes.value ? Number(minutes.value) : null;
                    if (!this.state.minutes) return;
                    this.markActive(".lk-radius-chip", null);
                    this.refresh();
                });
            }

            const search = this.root.querySelector(".lk-map-search-input");
            if (search) this.bindSearch(search);
        }

        markActive(selector, matcher) {
            this.root.querySelectorAll(selector).forEach(chip => {
                const on = matcher ? matcher(chip) : false;
                chip.classList.toggle("active", on);
                chip.setAttribute("aria-checked", on ? "true" : "false");
            });
        }

        setMode(mode) {
            this.state.mode = mode;
            this.markActive(".lk-mode-chip", chip => chip.dataset.mode === mode);
            this.updateRadiusHints();
            // "within 15 min" depends on the mode: that changes the radius, so ask again.
            // Otherwise the results are the same places; only their travel times change.
            if (this.state.minutes || !this.hasPoint() || (this.kind === "renter" ? !this.complexes : !this.loaded)) {
                this.refresh();
                return;
            }
            if (this.kind === "renter") this.renderComplexes(this.complexes);
            else this.renderLandmarks();
            this.writeFormFields();
            this.root.dispatchEvent(new CustomEvent("lookapt:map-change", { bubbles: true, detail: this.snapshot() }));
        }

        setRadius(km) {
            this.state.radius = km;
            this.state.minutes = null;
            const minutes = this.root.querySelector(".lk-minutes-select");
            if (minutes) minutes.value = "";
            this.markActive(".lk-radius-chip", chip => parseFloat(chip.dataset.km) === km);
            this.refresh();
        }

        // "< 1 km  ~16 min walk" — the hint follows the chosen transport mode
        updateRadiusHints() {
            this.root.querySelectorAll(".lk-radius-chip").forEach(chip => {
                const hint = chip.querySelector(".lk-radius-time");
                if (hint) hint.textContent = `~${chip.dataset[this.state.mode]} min ${MODE_WORDS[this.state.mode]}`;
            });
        }

        setPoint(lat, lng, label) {
            this.state.lat = Math.round(lat * 1e6) / 1e6;
            this.state.lng = Math.round(lng * 1e6) / 1e6;
            this.state.label = label || "";
            this.removed.clear();
            this.root.classList.add("has-point");
            if (this.kind === "landlord" && this.editable) this.reverseGeocode();
            this.refresh();
        }


        // ---------------------------------------------------------
        // Search box
        // ---------------------------------------------------------

        bindSearch(input) {
            this.attachSuggestions(input, this.root.querySelector(".lk-map-search-results"), place => {
                input.value = place.name;
                this.setPoint(place.lat, place.lng, place.name);
            });
        }


        // ---------------------------------------------------------
        // Suggestions under a text box (place search API)
        // ---------------------------------------------------------

        // Calls onPick(place) when a suggestion is chosen (click or Enter)
        attachSuggestions(input, list, onPick, minLength = 3) {
            const run = debounce(async () => {
                const q = input.value.trim();
                if (q.length < minLength) { list.hidden = true; return; }
                list.replaceChildren(el("li", "lk-search-empty", "Searching…"));
                list.hidden = false;
                try {
                    const data = await this.getJSON(this.urls.search, { q });
                    if (input.value.trim() !== q) return;          // typed on since
                    list.replaceChildren();
                    if (!data.results.length) {
                        list.append(el("li", "lk-search-empty", "No places found."));
                        return;
                    }
                    data.results.forEach(place => {
                        const item = el("li", "lk-search-result");
                        item.setAttribute("role", "option");
                        item.tabIndex = 0;
                        item.append(el("strong", "", place.name), el("small", "", place.address));
                        const choose = () => { list.hidden = true; onPick(place); };
                        item.addEventListener("click", choose);
                        item.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); choose(); } });
                        list.append(item);
                    });
                } catch (error) {
                    list.replaceChildren(el("li", "lk-search-empty", "Search is unavailable right now."));
                }
            }, 450);

            input.addEventListener("input", () => { if (input.dataset.autofilled !== "1") run(); });
            // Enter must not submit the property form: it picks the first suggestion
            input.addEventListener("keydown", e => {
                if (e.key !== "Enter") return;
                e.preventDefault();
                e.stopPropagation();
                list.querySelector(".lk-search-result")?.click();
            });
            document.addEventListener("click", e => {
                if (e.target !== input && !list.contains(e.target)) list.hidden = true;
            });
        }


        // ---------------------------------------------------------
        // Landlord: type the address -> pin
        // ---------------------------------------------------------

        bindAddressSearch() {
            if (this.kind !== "landlord" || !this.editable || !this.form) return;
            const box = this.form.querySelector("[data-address-search]");
            if (!box) return;
            const input = box.querySelector("input, textarea");
            const list = box.querySelector(".lk-map-search-results");
            input.addEventListener("input", () => { delete input.dataset.autofilled; });
            this.attachSuggestions(input, list, place => {
                // Keep what the landlord typed; just move the pin there
                if (!input.value.trim()) input.value = place.address || place.name;
                this.setPoint(place.lat, place.lng, place.name);
            });
        }


        // ---------------------------------------------------------
        // Landlord: add a landmark by hand
        // ---------------------------------------------------------

        bindManual() {
            if (this.kind !== "landlord" || !this.editable || !this.results) return;
            const panel = this.results.closest(".lk-landmarks-panel");
            const box = panel && panel.querySelector("[data-lk-manual]");
            if (!box) return;

            const categories = {};
            (readJSON("#lk-manual-categories") || []).forEach(c => { categories[c.category] = c; });
            const formBox = box.querySelector("[data-manual-form]");
            const toggle = box.querySelector("[data-manual-toggle]");
            const name = box.querySelector("[data-manual-name]");
            const category = box.querySelector("[data-manual-category]");
            const where = box.querySelector("[data-manual-point]");
            const error = box.querySelector("[data-manual-error]");
            let point = null;

            const showError = text => { error.textContent = text; error.hidden = !text; };
            const setPoint = (lat, lng, text) => {
                point = { lat: Math.round(lat * 1e6) / 1e6, lng: Math.round(lng * 1e6) / 1e6 };
                where.textContent = text;
                where.classList.add("is-set");
                showError("");
            };
            const reset = () => {
                name.value = "";
                category.value = "";
                point = null;
                where.textContent = where.dataset.empty;
                where.classList.remove("is-set");
                showError("");
                this.picking = null;
                this.root.classList.remove("is-picking");
            };
            const open = show => {
                formBox.hidden = !show;
                toggle.hidden = show;
                if (show) name.focus();
                else reset();
            };

            toggle.addEventListener("click", () => open(true));
            box.querySelector("[data-manual-cancel]").addEventListener("click", () => open(false));

            // Typing a name suggests places; choosing one fills its spot (and category if known)
            const suggest = box.querySelector("[data-manual-suggest]");
            this.attachSuggestions(name, suggest, place => {
                name.value = place.name;
                if (place.category && categories[place.category] && !category.value) category.value = place.category;
                setPoint(place.lat, place.lng, place.address || "Spot found");
                this.postToFrame({ type: "lookapt:mark", lat: place.lat, lng: place.lng });
            });

            box.querySelector("[data-manual-pick]").addEventListener("click", () => {
                if (!this.hasPoint()) return showError("Drop your property's pin on the map first.");
                suggest.hidden = true;
                this.picking = (lat, lng) => {
                    setPoint(lat, lng, "Picked on the map");
                    this.setStatus("");
                };
                this.root.classList.add("is-picking");
                where.textContent = "Now click the landmark's spot on the map…";
                this.setStatus(`Click where "${name.value.trim() || "the landmark"}" is on the map.`);
                this.root.querySelector(".lk-map-frame-wrap")?.scrollIntoView({ behavior: "smooth", block: "center" });
            });

            box.querySelector("[data-manual-add]").addEventListener("click", () => {
                const label = name.value.trim();
                if (!this.hasPoint()) return showError("Drop your property's pin on the map first.");
                if (!label) return showError("Type the landmark's name.");
                if (!categories[category.value]) return showError("Pick a category.");
                if (!point) return showError("Search the place above or pick its spot on the map.");
                const distance = haversineM(this.state.lat, this.state.lng, point.lat, point.lng);
                if (distance > 20000) return showError("That spot is more than 20 km from your property.");

                this.manual.push({
                    name: label.slice(0, 120), lat: point.lat, lng: point.lng, manual: true,
                    ...categories[category.value], ...travelInfo(distance, this.state.mode),
                });
                open(false);
                this.renderLandmarks();
                this.reloadFrame();
                this.writeFormFields();
                this.root.dispatchEvent(new CustomEvent("lookapt:map-change", { bubbles: true, detail: this.snapshot() }));
            });
        }


        // ---------------------------------------------------------
        // Iframe <-> page
        // ---------------------------------------------------------

        bindFrameMessages() {
            if (!this.editable) return;
            window.addEventListener("message", event => {
                if (event.origin !== window.location.origin) return;
                if (!this.frame || event.source !== this.frame.contentWindow) return;
                if (!event.data || event.data.type !== "lookapt:map-click") return;
                if (this.picking) {
                    const done = this.picking;
                    this.picking = null;
                    this.root.classList.remove("is-picking");
                    this.postToFrame({ type: "lookapt:mark", lat: event.data.lat, lng: event.data.lng });
                    done(event.data.lat, event.data.lng);
                    return;
                }
                this.setPoint(event.data.lat, event.data.lng);
            });
        }

        postToFrame(message) {
            try {
                this.frame?.contentWindow?.postMessage(message, window.location.origin);
            } catch (error) { /* frame not loaded yet */ }
        }

        // Radius in metres for the scan animation (the server sends the exact one)
        scanRadiusM() {
            if (this.state.minutes) {
                const km = SPEED_KMH[this.state.mode] * (this.state.minutes / 60) / ROAD_DETOUR;
                return Math.min(20, Math.max(0.2, km)) * 1000;
            }
            return this.state.radius * 1000;
        }

        // Leaflet sizes itself wrong inside a hidden iframe, so only
        // (re)load the frame while it is visible.
        watchVisibility() {
            if (!("IntersectionObserver" in window)) { this.reloadFrame(); return; }
            this.observer = new IntersectionObserver(entries => {
                this.visible = entries.some(entry => entry.isIntersecting);
                if (this.visible && this.frameDirty) this.reloadFrame();
            });
            this.observer.observe(this.root.querySelector(".lk-map-frame-wrap"));
        }

        reloadFrame(force) {
            if (!this.frame) return;
            if (!force && this.observer && !this.visible) { this.frameDirty = true; return; }
            this.frameDirty = false;

            const params = {
                kind: this.kind,
                editable: this.editable ? "1" : "0",
                mode: this.state.mode,
                radius_km: this.state.radius,
            };
            if (this.hasPoint()) {
                params.lat = this.state.lat;
                params.lng = this.state.lng;
            }
            if (this.state.label) params.label = this.state.label;
            if (this.root.dataset.complex) params.complex = this.root.dataset.complex;
            if (this.kind === "landlord" && this.editable) {
                // Until the landlord changes something, draw the property's saved landmarks
                if (this.useSaved && this.root.dataset.savedComplex) params.complex = this.root.dataset.savedComplex;
                if (this.manual.length) {
                    params.pins = JSON.stringify(this.manual.map(({ name, category, lat, lng }) => ({ name, category, lat, lng })));
                }
            }

            this.frame.src = `${this.urls.frame}?${new URLSearchParams(params)}`;
        }

        refresh() {
            if (!this.hasPoint()) { this.reloadFrame(); return; }
            this.fetchResults();
        }


        // ---------------------------------------------------------
        // API
        // ---------------------------------------------------------

        async getJSON(url, params) {
            const response = await fetch(`${url}?${new URLSearchParams(params)}`, {
                headers: { "Accept": "application/json" },
                credentials: "same-origin",
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || "Request failed");
            return data;
        }

        async fetchResults() {
            const id = ++this.requestId;
            this.useSaved = false;
            const params = { lat: this.state.lat, lng: this.state.lng, mode: this.state.mode };
            if (this.state.minutes) params.minutes = this.state.minutes;
            else params.radius_km = this.state.radius;

            this.setStatus(this.kind === "renter" ? "Finding apartments…" : "Scanning for nearby landmarks…");
            this.root.classList.add("is-loading");
            // Draw the new radius at once, with a radar sweep until the results come
            this.postToFrame({ type: "lookapt:scan", lat: this.state.lat, lng: this.state.lng, radius_m: this.scanRadiusM() });

            let failed = false;
            try {
                if (this.kind === "renter") {
                    const data = await this.getJSON(this.urls.complexes, params);
                    if (id !== this.requestId) return;
                    this.state.radius = data.radius_km;
                    this.complexes = data.complexes;
                    this.renderComplexes(data.complexes);
                    this.setStatus("");
                } else {
                    const data = await this.getJSON(this.urls.landmarks, params);
                    if (id !== this.requestId) return;
                    this.state.radius = data.radius_km;
                    this.landmarks = data.landmarks;
                    this.loaded = true;
                    this.renderLandmarks();
                    this.setStatus(data.source === "offline"
                        ? "OpenStreetMap is unreachable right now — showing saved landmarks only. You can add landmarks by hand."
                        : "");
                }
            } catch (error) {
                if (id !== this.requestId) return;
                failed = true;
                this.setStatus("Couldn't load the results.", () => this.fetchResults());
            } finally {
                if (id === this.requestId) this.root.classList.remove("is-loading");
            }

            this.reloadFrame();
            // A failed lookup keeps the list it had (it must not save "no landmarks")
            this.writeFormFields(!failed);
            this.root.dispatchEvent(new CustomEvent("lookapt:map-change", { bubbles: true, detail: this.snapshot() }));
        }

        async reverseGeocode() {
            const { lat, lng } = this.state;
            try {
                const data = await this.getJSON(this.urls.reverse, { lat, lng });
                if (lat !== this.state.lat || lng !== this.state.lng) return;  // a newer pin exists
                this.setField("area_name", data.area || "");
                const address = this.form && this.form.querySelector('[name="address"]');
                // Fill the address unless the landlord typed their own
                if (address && (!address.value || address.dataset.autofilled === "1")) {
                    address.value = data.address || "";
                    address.dataset.autofilled = "1";
                }
                if (data.address) {
                    this.state.label = data.address;
                    this.root.dispatchEvent(new CustomEvent("lookapt:map-change", { bubbles: true, detail: this.snapshot() }));
                }
            } catch (error) {
                /* address stays editable by hand */
            }
        }

        // Optional retry: shows a "Try again" link after the text
        setStatus(text, retry) {
            if (!this.status) return;
            this.status.textContent = text;
            if (retry) {
                const button = el("button", "lk-retry", "Try again");
                button.type = "button";
                button.addEventListener("click", retry);
                this.status.append(" ", button);
            }
        }

        snapshot() {
            return {
                ...this.state,
                kind: this.kind,
                landmarks: this.keptLandmarks(),
                address: this.form && this.form.querySelector('[name="address"]') ? this.form.querySelector('[name="address"]').value : "",
            };
        }

        keptLandmarks() {
            // Manual ones first (the landlord added them on purpose), then the nearest found ones
            const found = this.landmarks.filter(item => !this.removed.has(this.landmarkKey(item)));
            return [...this.manual, ...found];
        }

        landmarkKey(item) {
            return `${item.name}|${item.category}|${item.lat}|${item.lng}`;
        }


        // ---------------------------------------------------------
        // Landlord: hidden form fields
        // ---------------------------------------------------------

        setField(name, value) {
            if (!this.form || !this.editable) return;
            const input = this.form.querySelector(`[name="${name}"]`);
            if (input) {
                input.value = value;
                input.dispatchEvent(new Event("change", { bubbles: true }));
            }
        }

        writeFormFields(withLandmarks = true) {
            if (this.kind !== "landlord" || !this.hasPoint()) return;
            this.setField("latitude", this.state.lat);
            this.setField("longitude", this.state.lng);
            this.setField("travel_mode", this.state.mode);
            if (!withLandmarks) return;
            this.setField("landmarks_json", JSON.stringify(
                this.keptLandmarks().map(({ name, category, lat, lng, manual }) => ({ name, category, lat, lng, manual: !!manual }))
            ));
        }


        // ---------------------------------------------------------
        // Rendering
        // ---------------------------------------------------------

        renderLandmarks() {
            if (!this.results) return;
            this.results.replaceChildren(...LookAptMap.landmarkRows(this.keptLandmarks(), this.state.mode, this.editable ? item => {
                if (item.manual) this.manual = this.manual.filter(other => other !== item);
                else this.removed.add(this.landmarkKey(item));
                this.renderLandmarks();
                if (item.manual) this.reloadFrame();
                this.writeFormFields();
                this.root.dispatchEvent(new CustomEvent("lookapt:map-change", { bubbles: true, detail: this.snapshot() }));
            } : null));

            const panel = this.results.closest(".lk-landmarks-panel");
            const subtitle = panel && panel.querySelector(".lk-landmarks-subtitle");
            if (subtitle) subtitle.textContent = `Estimated ${MODE_WORDS[this.state.mode]} time from your property (within ${this.state.radius} km)`;
        }

        static landmarkRows(landmarks, mode, onRemove) {
            if (!landmarks.length) {
                return [el("li", "lk-landmarks-empty", "No landmarks found in this radius. Try a bigger radius.")];
            }
            return landmarks.map(item => {
                const row = el("li", "lk-landmark");

                const icon = el("span", "lk-landmark-icon");
                icon.style.color = item.color;
                icon.style.background = item.bg;
                icon.innerHTML = `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${item.icon}</svg>`;

                const body = el("div", "lk-landmark-body");
                const meta = el("span", "lk-landmark-meta");
                const time = el("span", "lk-landmark-time");
                const minutes = item.minutes_by_mode ? item.minutes_by_mode[mode] : item.minutes;
                time.innerHTML = MODE_ICONS[mode] || "";
                time.append(` ${minutes} min${minutes === 1 ? "" : "s"}`);
                meta.append(el("span", "", item.distance_label || `${item.distance_km} km`), time);
                body.append(el("strong", "", item.name), meta);

                if (item.manual) {
                    const badge = el("em", "lk-landmark-manual", "Added");
                    badge.title = "Added by you";
                    meta.append(badge);
                }
                row.append(icon, body, el("span", "lk-landmark-tag", item.label));

                if (onRemove) {
                    const remove = el("button", "lk-landmark-remove", "×");
                    remove.type = "button";
                    remove.title = "Remove this landmark";
                    remove.setAttribute("aria-label", `Remove ${item.name}`);
                    remove.addEventListener("click", () => onRemove(item));
                    row.append(remove);
                }
                return row;
            });
        }

        renderComplexes(complexes) {
            if (this.summary) {
                const where = this.state.label ? ` of ${this.state.label}` : "";
                this.summary.textContent = `${complexes.length} apartment${complexes.length === 1 ? "" : "s"} within ${this.state.radius} km${where}`;
            }
            if (!this.results) return;

            if (!complexes.length) {
                this.results.replaceChildren(el("li", "lk-landmarks-empty", "No listed apartments in this radius yet. Try a bigger radius or another mode."));
                return;
            }

            this.results.replaceChildren(...complexes.map(item => {
                const card = el("li", "lk-complex");

                const media = el("div", "lk-complex-media");
                if (item.image) {
                    const img = el("img");
                    img.src = item.image;
                    img.alt = item.name;
                    img.loading = "lazy";
                    media.append(img);
                } else {
                    media.innerHTML = BUILDING_ICON;
                }

                const body = el("div", "lk-complex-body");
                // The name links to the listing page and covers the whole card
                const name = el(item.url ? "a" : "strong", "lk-complex-name", item.name);
                if (item.url) {
                    name.href = item.url;
                    card.classList.add("lk-complex--link");
                }

                body.append(
                    name,
                    el("span", "lk-complex-address", item.address || item.area),
                    el("span", "lk-complex-price", `₱${peso.format(item.min_price)} – ₱${peso.format(item.max_price)} / month`),
                );

                const meta = el("span", "lk-landmark-meta");
                const time = el("span", "lk-landmark-time");
                time.innerHTML = MODE_ICONS[this.state.mode] || "";
                const minutes = item.minutes_by_mode ? item.minutes_by_mode[this.state.mode] : item.minutes;
                time.append(` ${minutes} min${minutes === 1 ? "" : "s"}`);
                meta.append(el("span", "", item.distance_label || `${item.distance_km} km`), time);

                const tags = el("span", "lk-complex-tags");
                tags.append(el("span", "lk-landmark-tag", item.sex_restriction));
                if (item.pet_friendly) tags.append(el("span", "lk-landmark-tag", "Pet friendly"));

                body.append(meta, tags);
                card.append(media, body);
                return card;
            }));
        }


        // ---------------------------------------------------------
        // Read-only copy (e.g. wizard "Review" step) of another map
        // ---------------------------------------------------------

        mirror(detail) {
            this.state.lat = detail.lat;
            this.state.lng = detail.lng;
            this.state.radius = detail.radius;
            this.state.mode = detail.mode;
            this.state.label = detail.label;
            this.landmarks = detail.landmarks;
            this.renderLandmarks();
            this.reloadFrame();
        }
    }


    // ---------------------------------------------------------
    // Init
    // ---------------------------------------------------------

    const registry = [];

    function init(scope) {
        (scope || document).querySelectorAll("[data-lk-map]").forEach(root => {
            if (root.lookAptMap) return;
            root.lookAptMap = new LookAptMap(root);
            registry.push(root.lookAptMap);
        });
    }

    // Read-only maps with data-mirror="wizard" follow the editable landlord map
    document.addEventListener("lookapt:map-change", event => {
        const source = event.target.lookAptMap;
        if (!source || !source.editable) return;
        registry
            .filter(map => map !== source && map.root.dataset.mirror === "wizard")
            .forEach(map => map.mirror(event.detail));
    });

    window.LookAptMaps = {
        init,
        all: () => registry.slice(),
        // Force a redraw, e.g. after a hidden wizard step becomes visible
        refreshAll(scope) {
            registry
                .filter(map => !scope || scope.contains(map.root))
                .forEach(map => map.reloadFrame(true));
        },
        find(selector) {
            const root = document.querySelector(selector);
            return root ? root.lookAptMap : null;
        },
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => init());
    } else {
        init();
    }

})();
