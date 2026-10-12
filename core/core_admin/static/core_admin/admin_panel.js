// Admin panel (core_admin): full-size viewer, confirmations, the verification
// decision form, and the Overview's activity chart.
(function () {

    // ---------------------------------------------------------------- full-size viewer
    const lightbox = document.querySelector("[data-ap-lightbox]");
    if (lightbox) {
        const image = lightbox.querySelector("img");
        const video = lightbox.querySelector("video");
        document.addEventListener("click", event => {
            const thumb = event.target.closest("[data-ap-view]");
            if (!thumb) return;
            const isVideo = thumb.dataset.apKind === "video";
            image.hidden = isVideo;
            video.hidden = !isVideo;
            if (isVideo) video.src = thumb.dataset.apView;
            else image.src = thumb.dataset.apView;
            lightbox.showModal();
        });
        lightbox.querySelector(".photo-lightbox-close").addEventListener("click", () => lightbox.close());
        lightbox.addEventListener("click", event => { if (event.target === lightbox) lightbox.close(); });
        lightbox.addEventListener("close", () => video.pause());
    }

    // ---------------------------------------------------------------- "Are you sure?"
    // Our own pop-up instead of window.confirm(), which shows the site's address ("lookapt.com says").
    const confirmForms = document.querySelectorAll("form[data-ap-confirm]");
    if (confirmForms.length) {
        const dialog = document.createElement("dialog");
        dialog.className = "ap-confirm";
        dialog.innerHTML = `<p class="ap-confirm-text"></p>
            <div class="ap-confirm-actions">
                <button type="button" class="ap-btn ap-btn--ghost" value="cancel">Cancel</button>
                <button type="button" class="ap-btn ap-btn--primary" value="ok">Confirm</button>
            </div>`;
        document.body.append(dialog);
        const text = dialog.querySelector(".ap-confirm-text");
        const ok = dialog.querySelector("[value=ok]");
        let pending = null;

        dialog.addEventListener("click", event => {
            const button = event.target.closest("button");
            if (button) dialog.close(button.value);
            else if (event.target === dialog) dialog.close("cancel");     // click outside
        });
        dialog.addEventListener("close", () => {
            const { form, submitter } = pending || {};
            pending = null;
            if (form && dialog.returnValue === "ok") {
                form.dataset.apConfirmed = "1";
                form.requestSubmit(submitter || undefined);
            }
        });

        confirmForms.forEach(form => {
            form.addEventListener("submit", event => {
                if (form.dataset.apConfirmed) { delete form.dataset.apConfirmed; return; }
                event.preventDefault();
                pending = { form, submitter: event.submitter };
                text.textContent = form.dataset.apConfirm;
                // Red for suspending / unpublishing, navy otherwise
                const danger = event.submitter?.classList.contains("ap-btn--danger")
                    || /^(suspend|unpublish)/i.test(form.dataset.apConfirm);
                ok.className = "ap-btn " + (danger ? "ap-btn--danger" : "ap-btn--primary");
                ok.textContent = event.submitter?.textContent.trim() || "Confirm";
                dialog.returnValue = "";
                dialog.showModal();
                ok.focus();
            });
        });
    }

    // ---------------------------------------------------------------- verification decision
    const decision = document.querySelector("[data-ap-decision]");
    if (decision) {
        const reasonBox = decision.querySelector("[data-ap-reason]");
        const pick = decision.querySelector("[data-ap-reason-pick]");
        const text = decision.querySelector("textarea[name=reason]");

        function sync() {
            const action = decision.querySelector("input[name=action]:checked")?.value;
            reasonBox.hidden = !action || action === "approve";
            text.required = !reasonBox.hidden;
            // Only the ready-made reasons that fit this decision
            pick.querySelectorAll("optgroup").forEach(group => { group.hidden = group.dataset.for !== action; });
            pick.value = "";
        }
        decision.addEventListener("change", event => { if (event.target.name === "action") sync(); });
        pick.addEventListener("change", () => { if (pick.value) text.value = pick.value; });
        sync();
    }

    // ---------------------------------------------------------------- report status: a note for final states
    const reportStatus = document.querySelector("[data-ap-report-status]");
    if (reportStatus) {
        const note = reportStatus.form.querySelector("textarea[name=note]");
        const sync = () => { note.required = ["resolved", "dismissed"].includes(reportStatus.value); };
        reportStatus.addEventListener("change", sync);
        sync();
    }

    // ---------------------------------------------------------------- tabs (Overview, Verification, Users, Reports)
    // All four are in the page already (dashboard.html), so switching is instant, like the
    // landlord / renter dashboards. The address bar follows (?tab= plus that tab's filters),
    // so refresh, back / forward and shared links open the same view.
    const sections = new Map([...document.querySelectorAll("[data-ap-section]")].map(s => [s.dataset.apSection, s]));
    const filtersOf = {};       // tab -> function giving its current filters (set up below)

    function tabUrl(name, params) {
        const query = new URLSearchParams(params || "");
        query.delete("page");
        query.set("tab", name);
        // ?tab= first, then the filters
        return `${location.pathname}?tab=${name}${[...query].filter(([k]) => k !== "tab").map(([k, v]) => `&${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("")}`;
    }

    function showTab(name, { push = true, params = null } = {}) {
        const section = sections.get(name);
        if (!section) return false;
        sections.forEach((s, key) => { s.hidden = key !== name; });
        document.querySelectorAll(".sidebar-link[data-ap-tab]").forEach(link => {
            link.classList.toggle("active", link.dataset.apTab === name);
        });
        document.title = section.dataset.title || document.title;
        // A link like "Suspended accounts" (?tab=users&status=suspended) also sets that tab's filters
        if (params && [...params.keys()].some(key => key !== "tab") && section.apSetFilters) section.apSetFilters(params);
        const url = tabUrl(name, filtersOf[name] ? filtersOf[name]() : "");
        if (push && url !== location.pathname + location.search) history.pushState({ tab: name }, "", url);
        window.scrollTo({ top: 0 });
        return true;
    }

    if (sections.size) {
        document.addEventListener("click", event => {
            const link = event.target.closest("a[data-ap-tab]");
            if (!link || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
            const params = new URL(link.href).searchParams;
            if (showTab(link.dataset.apTab, { params })) event.preventDefault();
        });
        window.addEventListener("popstate", () => {
            const name = new URLSearchParams(location.search).get("tab") || "overview";
            showTab(name, { push: false });
        });
    }

    // ---------------------------------------------------------------- live filters (Verification, Users, Reports)
    // Typing in a search box or changing a filter updates that tab's results right away:
    // only the results table is fetched again ([data-ap-results]).
    document.querySelectorAll("form[data-ap-live]").forEach(form => {
        const section = form.closest("[data-ap-section]");
        const name = section ? section.dataset.apSection : null;
        const results = (section || document).querySelector("[data-ap-results]");
        const range = form.querySelector("[data-ap-range]");
        const joined = form.querySelector("[data-ap-joined]");
        const clear = form.querySelector("[data-ap-clear]");
        const statusInput = form.querySelector("input[name=status][type=hidden]");
        const statusTabs = section ? section.querySelectorAll("a.ap-tab[data-status]") : [];
        let timer = null, controller = null;

        function params() {
            const query = new URLSearchParams();
            new FormData(form).forEach((value, key) => { if (String(value).trim()) query.set(key, value); });
            if (range && range.hidden) { query.delete("joined_from"); query.delete("joined_to"); }
            return query;
        }
        if (name) filtersOf[name] = params;

        function syncControls() {
            if (range && joined) range.hidden = joined.value !== "custom";
            if (statusInput) statusTabs.forEach(tab => tab.classList.toggle("active", tab.dataset.status === statusInput.value));
            if (clear) clear.hidden = [...params().keys()].every(key => statusInput && key === "status");
        }

        async function load(url, query) {
            controller?.abort();
            controller = new AbortController();
            results.classList.add("is-loading");
            try {
                const response = await fetch(url, { headers: { "X-Requested-With": "ap-live" }, signal: controller.signal });
                if (!response.ok) throw new Error(response.status);
                results.innerHTML = await response.text();
                if (name && !section.hidden) history.replaceState({ tab: name }, "", tabUrl(name, query));
            } catch (error) {
                if (error.name !== "AbortError") window.location.href = url;     // fall back to a normal page load
            } finally {
                results.classList.remove("is-loading");
            }
        }

        function apply(delay) {
            syncControls();
            clearTimeout(timer);
            timer = setTimeout(() => { const query = params(); load(`${form.dataset.url}?${query}`, query); }, delay);
        }

        // For links that open this tab with filters (see showTab)
        if (section) section.apSetFilters = query => {
            form.reset();
            [...form.elements].forEach(field => { if (field.name && field.type !== "hidden") field.value = ""; });
            query.forEach((value, key) => { if (form.elements[key]) form.elements[key].value = value; });
            apply(0);
        };

        form.addEventListener("input", event => { if (event.target.type === "search") apply(300); });
        form.addEventListener("change", event => { if (event.target.type !== "search") apply(0); });
        form.addEventListener("submit", event => { event.preventDefault(); apply(0); });
        clear?.addEventListener("click", () => {
            [...form.elements].forEach(field => { if (field.name && field.type !== "hidden") field.value = ""; });
            apply(0);
        });
        // Status tabs (Pending / Under review ...) filter in place too
        statusTabs.forEach(tab => tab.addEventListener("click", event => {
            if (!statusInput || event.metaKey || event.ctrlKey) return;
            event.preventDefault();
            statusInput.value = tab.dataset.status;
            apply(0);
        }));
        // Previous / Next pages without reloading
        results.addEventListener("click", event => {
            const link = event.target.closest(".ap-pagination a");
            if (!link) return;
            event.preventDefault();
            load(link.href, new URL(link.href).searchParams);
            results.scrollIntoView({ behavior: "smooth", block: "start" });
        });
        syncControls();
    });

    // ---------------------------------------------------------------- activity chart
    const card = document.querySelector("[data-ap-chart]");
    if (!card) return;

    const SVG_NS = "http://www.w3.org/2000/svg";
    const plot = card.querySelector("[data-ap-chart-plot]");
    const tip = card.querySelector("[data-ap-chart-tip]");
    const legend = card.querySelector("[data-ap-legend]");
    const tableBox = card.querySelector("[data-ap-chart-table]");
    const daysSelect = card.querySelector("[data-ap-chart-days]");
    // Series colours are CSS variables (light / dark values in admin_panel.css), in fixed order
    const SLOTS = ["users", "listings", "reports"];
    let data = null;

    const el = (tag, attrs) => {
        const node = document.createElementNS(SVG_NS, tag);
        Object.entries(attrs || {}).forEach(([k, v]) => node.setAttribute(k, v));
        return node;
    };
    const color = key => `var(--ap-series-${SLOTS.indexOf(key) + 1})`;
    const shortDate = iso => new Date(iso + "T00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" });

    function niceMax(value) {
        if (value <= 4) return 4;
        const step = Math.pow(10, Math.floor(Math.log10(value)));
        return Math.ceil(value / step) * step;
    }

    function render() {
        if (!data) return;
        const width = plot.clientWidth || 600, height = plot.clientHeight || 240;
        const pad = { top: 12, right: 16, bottom: 26, left: 34 };
        const n = data.dates.length;
        const max = niceMax(Math.max(1, ...data.series.flatMap(s => s.values)));
        const x = i => pad.left + (n === 1 ? 0 : i * (width - pad.left - pad.right) / (n - 1));
        const y = v => height - pad.bottom - v * (height - pad.top - pad.bottom) / max;

        const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, width, height, "aria-hidden": "true" });

        // Recessive grid + y labels
        for (let t = 0; t <= 4; t++) {
            const value = Math.round(max * t / 4), yy = y(value);
            svg.append(el("line", { x1: pad.left, x2: width - pad.right, y1: yy, y2: yy, class: "ap-grid" }));
            const label = el("text", { x: pad.left - 8, y: yy + 4, class: "ap-axis", "text-anchor": "end" });
            label.textContent = value;
            svg.append(label);
        }
        // A few x labels (first, middle, last)
        [0, Math.floor((n - 1) / 2), n - 1].forEach((i, k) => {
            const label = el("text", { x: x(i), y: height - 6, class: "ap-axis", "text-anchor": ["start", "middle", "end"][k] });
            label.textContent = shortDate(data.dates[i]);
            svg.append(label);
        });

        // Lines (each one's name is in the legend above and in the hover tooltip)
        data.series.forEach(s => {
            const points = s.values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
            svg.append(el("polyline", { points, fill: "none", stroke: color(s.key), "stroke-width": 2,
                                        "stroke-linejoin": "round", "stroke-linecap": "round" }));
        });

        // Hover: crosshair + dots + tooltip for the nearest day
        const cross = el("line", { y1: pad.top, y2: height - pad.bottom, class: "ap-crosshair", visibility: "hidden" });
        svg.append(cross);
        const dots = data.series.map(s => {
            const dot = el("circle", { r: 4.5, fill: color(s.key), class: "ap-dot", visibility: "hidden" });
            svg.append(dot);
            return dot;
        });
        const hit = el("rect", { x: pad.left, y: pad.top, width: width - pad.left - pad.right, height: height - pad.top - pad.bottom,
                                 fill: "transparent" });
        svg.append(hit);

        function show(clientX) {
            const box = svg.getBoundingClientRect();
            const px = (clientX - box.left) * width / box.width;
            const i = Math.max(0, Math.min(n - 1, Math.round((px - pad.left) / ((width - pad.left - pad.right) / Math.max(1, n - 1)))));
            cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
            data.series.forEach((s, k) => {
                dots[k].setAttribute("cx", x(i)); dots[k].setAttribute("cy", y(s.values[i]));
                dots[k].setAttribute("visibility", "visible");
            });
            tip.innerHTML = `<strong>${shortDate(data.dates[i])}</strong>` + data.series.map(s =>
                `<span><i style="background:${color(s.key)}"></i>${s.label}<b>${s.values[i]}</b></span>`).join("");
            tip.hidden = false;
            // CSS pixels (the page is zoomed); flip to the left of the line near the right edge
            let left = x(i) + 14;
            if (left + tip.offsetWidth > plot.clientWidth) left = x(i) - tip.offsetWidth - 14;
            tip.style.left = `${plot.offsetLeft + Math.max(0, left)}px`;
            tip.style.top = `${plot.offsetTop + 8}px`;
        }
        function hide() {
            cross.setAttribute("visibility", "hidden");
            dots.forEach(d => d.setAttribute("visibility", "hidden"));
            tip.hidden = true;
        }
        hit.addEventListener("pointermove", e => show(e.clientX));
        hit.addEventListener("pointerleave", hide);

        plot.replaceChildren(svg);
    }

    function fill() {
        // Legend with totals for the period
        legend.replaceChildren(...data.series.map(s => {
            const li = document.createElement("li");
            const total = s.values.reduce((a, b) => a + b, 0);
            li.innerHTML = `<i style="background:${color(s.key)}"></i>${s.label} <b>${total}</b>`;
            return li;
        }));
        // Same numbers as a table (accessibility / exact values)
        const rows = data.dates.map((d, i) => `<tr><th scope="row">${shortDate(d)}</th>${data.series.map(s => `<td>${s.values[i]}</td>`).join("")}</tr>`);
        tableBox.innerHTML = `<table class="ap-table"><thead><tr><th>Day</th>${data.series.map(s => `<th>${s.label}</th>`).join("")}</tr></thead>`
            + `<tbody>${rows.reverse().join("")}</tbody></table>`;
        plot.setAttribute("aria-label", "Activity chart: " + data.series.map(s =>
            `${s.label} ${s.values.reduce((a, b) => a + b, 0)}`).join(", ") + ` in the last ${data.dates.length} days`);
        render();
    }

    async function load() {
        try {
            const response = await fetch(`${card.dataset.url}?days=${daysSelect.value}`, { headers: { Accept: "application/json" } });
            data = await response.json();
            fill();
        } catch (e) {
            plot.textContent = "Couldn't load the chart.";
        }
    }

    daysSelect.addEventListener("change", load);
    new ResizeObserver(() => render()).observe(plot);
    // The last 30 days come with the page; other periods are fetched
    const initial = document.getElementById("ap-chart-data");
    if (initial) { data = JSON.parse(initial.textContent); fill(); } else load();
})();
