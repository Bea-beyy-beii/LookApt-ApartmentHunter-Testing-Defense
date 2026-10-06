// =========================================================
// LookApt map picker (core_maps)
//
// The map itself is a Folium map rendered by Django inside an <iframe>.
// When the user clicks it, the iframe posts {type: "lookapt:map-click"}
// to this page. We then:
//   1. call the JSON API (landmarks for landlords, complexes for renters)
//   2. render the side panel
//   3. reload the iframe so Folium redraws the pin, radius and markers
// =========================================================

(function () {

    const MODE_ICONS = {
        walking: '<svg class="lk-mode-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="13" cy="4" r="1.6"/><path d="M10 21l2-6 2.5 2.5V21M8 12l2.5-4.5 3 1 2 3.5 2.5 1M10.5 7.5 9 13"/></svg>',
        commute: '<svg class="lk-mode-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="6" width="18" height="10" rx="2"/><path d="M3 11h18M7 6V4h10v2"/><circle cx="7.5" cy="18" r="1.6"/><circle cx="16.5" cy="18" r="1.6"/></svg>',
        driving: '<svg class="lk-mode-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 16V11l2-5h10l2 5v5M3 16h18v2H3z"/><circle cx="7.5" cy="16.5" r="1.5"/><circle cx="16.5" cy="16.5" r="1.5"/><path d="M5 11h14"/></svg>',
    };

    const MODE_WORDS = { walking: "walk", commute: "commute", driving: "drive" };

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

            this.landmarks = [];
            this.removed = new Set();
            this.requestId = 0;
            this.frameDirty = true;

            this.frame = root.querySelector(".lk-map-frame");
            this.status = root.querySelector(".lk-map-status");
            this.results = root.dataset.results ? document.querySelector(root.dataset.results) : null;
            this.summary = root.dataset.results ? document.querySelector(root.dataset.results + "-summary") : null;
            this.form = root.closest("form");

            this.bindControls();
            this.bindFrameMessages();
            this.watchVisibility();
            this.updateRadiusHints();

            if (this.hasPoint() && this.editable) {
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
            this.refresh();
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
            const list = this.root.querySelector(".lk-map-search-results");

            const run = debounce(async () => {
                const q = input.value.trim();
                if (q.length < 3) { list.hidden = true; return; }

                list.replaceChildren(el("li", "lk-search-empty", "Searching…"));
                list.hidden = false;

                try {
                    const data = await this.getJSON(this.urls.search, { q });
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
                        const choose = () => {
                            input.value = place.name;
                            list.hidden = true;
                            this.setPoint(place.lat, place.lng, place.name);
                        };
                        item.addEventListener("click", choose);
                        item.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); choose(); } });
                        list.append(item);
                    });
                } catch (error) {
                    list.replaceChildren(el("li", "lk-search-empty", "Search is unavailable right now."));
                }
            }, 450);

            input.addEventListener("input", run);
            // Enter in the search box must not submit the property form
            input.addEventListener("keydown", e => {
                if (e.key === "Enter") {
                    e.preventDefault();
                    e.stopPropagation();
                    const first = list.querySelector(".lk-search-result");
                    if (first) first.click();
                }
            });
            document.addEventListener("click", e => {
                if (!this.root.querySelector(".lk-map-search").contains(e.target)) list.hidden = true;
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
                this.setPoint(event.data.lat, event.data.lng);
            });
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
            const params = { lat: this.state.lat, lng: this.state.lng, mode: this.state.mode };
            if (this.state.minutes) params.minutes = this.state.minutes;
            else params.radius_km = this.state.radius;

            this.setStatus(this.kind === "renter" ? "Finding apartments…" : "Finding nearby landmarks…");
            this.root.classList.add("is-loading");

            try {
                if (this.kind === "renter") {
                    const data = await this.getJSON(this.urls.complexes, params);
                    if (id !== this.requestId) return;
                    this.state.radius = data.radius_km;
                    this.renderComplexes(data.complexes);
                    this.setStatus("");
                } else {
                    const data = await this.getJSON(this.urls.landmarks, params);
                    if (id !== this.requestId) return;
                    this.state.radius = data.radius_km;
                    this.landmarks = data.landmarks;
                    this.renderLandmarks();
                    this.setStatus(data.source === "offline"
                        ? "OpenStreetMap is unreachable — showing saved landmarks only."
                        : "");
                }
            } catch (error) {
                if (id !== this.requestId) return;
                this.setStatus(error.message || "Something went wrong. Please try again.");
            } finally {
                if (id === this.requestId) this.root.classList.remove("is-loading");
            }

            this.reloadFrame();
            this.writeFormFields();
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

        setStatus(text) {
            if (this.status) this.status.textContent = text;
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
            return this.landmarks.filter(item => !this.removed.has(this.landmarkKey(item)));
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

        writeFormFields() {
            if (this.kind !== "landlord" || !this.hasPoint()) return;
            this.setField("latitude", this.state.lat);
            this.setField("longitude", this.state.lng);
            this.setField("travel_mode", this.state.mode);
            this.setField("landmarks_json", JSON.stringify(
                this.keptLandmarks().map(({ name, category, lat, lng }) => ({ name, category, lat, lng }))
            ));
        }


        // ---------------------------------------------------------
        // Rendering
        // ---------------------------------------------------------

        renderLandmarks() {
            if (!this.results) return;
            this.results.replaceChildren(...LookAptMap.landmarkRows(this.keptLandmarks(), this.state.mode, this.editable ? item => {
                this.removed.add(this.landmarkKey(item));
                this.renderLandmarks();
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
                time.append(` ${item.minutes} min${item.minutes === 1 ? "" : "s"}`);
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
