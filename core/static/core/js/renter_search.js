// =========================================================
// RENTER — search bar + "Filter by" (core_renters/partials/search_filter.html)
// Typing or picking a filter asks core_renters:search_listings for the
// Home and Saved Listings cards again, and swaps them in. The URL keeps the
// search, so a reload (or Back) shows the same results.
// =========================================================

(function () {

    const form = document.querySelector("[data-renter-search]");
    if (!form) return;

    const panel = form.querySelector("[data-filter-panel]");
    const toggle = form.querySelector("[data-filter-toggle]");
    const badge = form.querySelector("[data-filter-badge]");
    const homeGrid = document.querySelector("[data-home-grid]");
    const savedGrid = document.querySelector("[data-saved-grid]");
    const summary = document.querySelector("[data-search-summary]");

    let timer = null;
    let request = null;


    // ---------- Panel ----------

    function setPanel(open) {
        panel.hidden = !open;
        toggle.setAttribute("aria-expanded", String(open));
    }

    toggle.addEventListener("click", () => setPanel(panel.hidden));
    form.querySelector("[data-filter-done]").addEventListener("click", () => setPanel(false));

    document.addEventListener("click", event => {
        if (!panel.hidden && !event.target.closest(".filter-wrap")) setPanel(false);
    });
    document.addEventListener("keydown", event => {
        if (event.key === "Escape" && !panel.hidden) {
            setPanel(false);
            toggle.focus();
        }
    });


    // ---------- Query ----------

    // Only the filled-in fields (no "q=&sort=newest&..." noise in the URL)
    function params() {
        const data = new URLSearchParams();
        for (const [name, value] of new FormData(form)) {
            if (name === "tab" || !value.trim()) continue;
            if (name === "sort" && value === "newest") continue;
            data.append(name, value.trim());
        }
        return data;
    }

    function updateURL(query) {
        const url = new URL(window.location.href);
        const tab = url.searchParams.get("tab") || document.body.dataset.tab || "home";
        url.search = "";
        url.searchParams.set("tab", tab);
        query.forEach((value, name) => url.searchParams.append(name, value));
        window.history.replaceState(window.history.state, "", url);
    }

    function setEmpty(box, hasCards, searching) {
        if (!box) return;
        box.hidden = hasCards;
        box.querySelectorAll("[data-empty-search]").forEach(el => { el.hidden = !searching; });
        box.querySelectorAll("[data-empty-none]").forEach(el => { el.hidden = searching; });
    }

    function fillGrid(grid, html) {
        if (!grid) return;
        grid.innerHTML = html;
        grid.querySelectorAll("[data-gallery]").forEach(gallery => window.initGallery && initGallery(gallery));
    }

    async function search() {
        const query = params();
        updateURL(query);

        request?.abort();
        request = new AbortController();
        [homeGrid, savedGrid].forEach(grid => grid?.classList.add("is-loading"));

        try {
            const response = await fetch(`${form.dataset.url}?${query}`, {
                headers: { "Accept": "application/json" },
                credentials: "same-origin",
                signal: request.signal,
            });
            if (!response.ok) throw new Error(response.status);
            const data = await response.json();

            const searching = query.has("q") || data.filter_count > 0;
            fillGrid(homeGrid, data.home_html);
            fillGrid(savedGrid, data.saved_html);
            setEmpty(document.querySelector("[data-home-empty]"), data.home_count > 0, searching);
            setEmpty(document.querySelector("[data-saved-empty]"), data.saved_count > 0, searching);

            badge.hidden = !data.filter_count;
            badge.textContent = data.filter_count;

            if (summary) {
                summary.hidden = !searching;
                const n = data.home_count;
                summary.querySelector("[data-search-count]").textContent =
                    `${n} listing${n === 1 ? "" : "s"} match${n === 1 ? "es" : ""}`;
            }
        } catch (error) {
            if (error.name !== "AbortError") console.warn("Search failed", error);
        } finally {
            [homeGrid, savedGrid].forEach(grid => grid?.classList.remove("is-loading"));
        }
    }

    function searchSoon(delay = 300) {
        clearTimeout(timer);
        timer = setTimeout(search, delay);
    }


    // ---------- Events ----------

    form.addEventListener("input", event => {
        // Typing in a text/number box waits a moment; selects and checkboxes go right away
        const typing = event.target.matches("input[type=search], input[type=number]");
        searchSoon(typing ? 350 : 0);
    });

    // Enter in the search bar: search now (no page reload)
    form.addEventListener("submit", event => {
        event.preventDefault();
        clearTimeout(timer);
        search();
        setPanel(false);
    });

    function clearFilters(keepText) {
        const text = form.elements.q.value;
        form.querySelectorAll("select").forEach(select => { select.selectedIndex = 0; });
        form.querySelectorAll("input[type=number]").forEach(input => { input.value = ""; });
        form.querySelectorAll("input[type=checkbox]").forEach(input => { input.checked = false; });
        form.elements.q.value = keepText ? text : "";
        search();
    }

    form.querySelector("[data-filter-clear]").addEventListener("click", () => clearFilters(true));
    summary?.querySelector("[data-search-reset]").addEventListener("click", () => clearFilters(false));

})();
