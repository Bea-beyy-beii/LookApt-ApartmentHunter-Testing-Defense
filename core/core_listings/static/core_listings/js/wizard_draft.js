// =========================================================
// CREATE / EDIT PROPERTY — keep the wizard after a refresh
// Saves the current step + every input to sessionStorage
// (photos are saved separately by photo_upload.js).
// =========================================================

(function () {

    const SKIP = new Set(["csrfmiddlewaretoken", "photos"]);
    const PENDING = "lookapt:wizard:pending";   // draft key of the form that was just submitted

    // The server adds ?saved=1 after a successful save: only now is it safe to
    // forget the draft. (If the save failed, the draft is still there to restore.)
    // Runs before DOMContentLoaded so photo_upload.js doesn't restore the photos.
    const params = new URLSearchParams(location.search);
    if (params.has("saved")) {
        try {
            const pendingKey = sessionStorage.getItem(PENDING);
            if (pendingKey) sessionStorage.removeItem(pendingKey);
            sessionStorage.removeItem(PENDING);
        } catch (error) {
            /* storage blocked: there is no draft to clear */
        }

        // Drop ?saved=1 so a refresh doesn't count as another save
        params.delete("saved");
        history.replaceState(null, "", location.pathname + (params.toString() ? "?" + params : "") + location.hash);
    }

    document.addEventListener("DOMContentLoaded", () => {
        const form = document.querySelector(".wizard-form");
        if (!form) return;

        const key = "lookapt:wizard:" + form.getAttribute("action");

        
        // The server sent the form back with errors (listings.js already opened the step with the first error)
        const hasErrors = form.dataset.hasErrors === "1";

        // The editable map in step 2 (from core_maps)
        function mapPicker() {
            if (!window.LookAptMaps) return null;
            return window.LookAptMaps.all()
                .find(map => map.editable && map.kind === "landlord" && form.contains(map.root)) || null;
        }


        // ---------- save ----------

        function save() {
            const fields = {};
            for (const el of form.elements) {
                if (!el.name || SKIP.has(el.name)) continue;
                if (["file", "submit", "button"].includes(el.type)) continue;
                fields[el.name] = el.type === "checkbox" ? el.checked : el.value;
            }

            const formView = document.getElementById("listings-form-view");
            const map = mapPicker();

            const draft = {
                step: typeof currentStep !== "undefined" ? currentStep : 1,
                formOpen: formView ? !formView.hidden : true,
                fields,
                map: map ? { mode: map.state.mode, radius: map.state.radius, label: map.state.label } : null,
            };

            try {
                sessionStorage.setItem(key, JSON.stringify(draft));
            } catch (error) {
                /* storage full or blocked: the form still works, it just won't survive a refresh */
            }
        }


        // ---------- restore ----------

        function restoreMap(draft) {
            const lat = parseFloat(form.elements.latitude && form.elements.latitude.value);
            const lng = parseFloat(form.elements.longitude && form.elements.longitude.value);
            const map = mapPicker();
            if (!map || isNaN(lat) || isNaN(lng)) return;

            if (draft.map) {
                map.state.mode = draft.map.mode;
                map.state.radius = draft.map.radius;
                map.markActive(".lk-mode-chip", chip => chip.dataset.mode === map.state.mode);
                map.markActive(".lk-radius-chip", chip => parseFloat(chip.dataset.km) === map.state.radius);
                map.updateRadiusHints();
            }

            // Keep the address the landlord typed instead of re-filling it from the pin
            if (form.elements.address) form.elements.address.dataset.autofilled = "0";

            map.setPoint(lat, lng, draft.map ? draft.map.label : "");
        }

        function restore() {
            let draft = null;
            try {
                draft = JSON.parse(sessionStorage.getItem(key));
            } catch (error) {
                draft = null;
            }
            if (!draft) return;

            if (hasErrors) {
                // The inputs already hold what was submitted; only the map pin
                // (and the photos, via photo_upload.js) need restoring.
                restoreMap(draft);
                save();
                return;
            }

            for (const [name, value] of Object.entries(draft.fields || {})) {
                const el = form.elements[name];
                if (!el || !el.tagName) continue;   // skip missing fields / radio groups
                if (el.type === "checkbox") el.checked = value;
                else el.value = value;
            }

            // Re-open the wizard on the dashboard (the unit page has no list view), but only
            // after a reload or Back/Forward. Arriving from a link (e.g. the "My Listings"
            // breadcrumb on the unit form) shows the list; the draft waits for "Add Property".
            const navigation = performance.getEntriesByType?.("navigation")[0];
            const reopened = !navigation || navigation.type !== "navigate";
            if (reopened && draft.formOpen && document.getElementById("listings-form-view") && typeof showPropertyForm === "function") {
                showPropertyForm();
            }
            goToStep(draft.step || 1);   // after showPropertyForm(), which resets to step 1
            restoreMap(draft);
        }


        // ---------- wire up ----------

        restore();

        form.addEventListener("input", save);
        form.addEventListener("change", save);
        form.addEventListener("lookapt:map-change", save);   // map pin / radius / landmarks
        document.addEventListener("wizard:step", save);
        document.addEventListener("photos:change", save);

        // Remember that the landlord went back to the list
        if (typeof window.showListingsList === "function") {
            const original = window.showListingsList;
            window.showListingsList = function () {
                original();
                save();
            };
        }

        // Real submit: keep the draft until the server confirms the save
        // (?saved=1, handled at the top). If the server rejects the form or
        // the request fails, the landlord doesn't lose what they typed.
        // listings.js blocks invalid submits with preventDefault().
        form.addEventListener("submit", event => {
            if (event.defaultPrevented) return;
            save();
            try {
                sessionStorage.setItem(PENDING, key);
            } catch (error) {
                /* storage blocked: nothing was saved, so nothing to clear later */
            }
        });
    });

})();