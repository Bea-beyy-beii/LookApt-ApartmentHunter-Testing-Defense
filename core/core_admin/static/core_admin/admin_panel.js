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
    document.querySelectorAll("form[data-ap-confirm]").forEach(form => {
        form.addEventListener("submit", event => {
            if (!window.confirm(form.dataset.apConfirm)) event.preventDefault();
        });
    });

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

    // ---------------------------------------------------------------- live filters (Users, Reports, Verification)
    // Typing in the search box or changing a filter updates the results right away:
    // only the results part is fetched again ([data-ap-results]) and the address bar
    // keeps the filters, so refresh / back / sharing the link still work.
    const live = document.querySelector("form[data-ap-live]");
    const results = document.querySelector("[data-ap-results]");
    if (live && results) {
        const range = live.querySelector("[data-ap-range]");
        const joined = live.querySelector("[data-ap-joined]");
        const clear = live.querySelector("[data-ap-clear]");
        let timer = null, controller = null;

        function queryFor(form) {
            const params = new URLSearchParams();
            new FormData(form).forEach((value, key) => { if (String(value).trim()) params.set(key, value); });
            if (range && range.hidden) { params.delete("joined_from"); params.delete("joined_to"); }
            return params;
        }

        async function update(url) {
            controller?.abort();
            controller = new AbortController();
            results.classList.add("is-loading");
            try {
                const response = await fetch(url, { headers: { "X-Requested-With": "ap-live" }, signal: controller.signal });
                if (!response.ok) throw new Error(response.status);
                results.innerHTML = await response.text();
                history.replaceState(null, "", url);
            } catch (error) {
                if (error.name !== "AbortError") window.location.href = url;     // fall back to a normal page load
                return;
            } finally {
                results.classList.remove("is-loading");
            }
            // Tabs keep the search / filters too
            const params = new URL(url, location.href).searchParams;
            document.querySelectorAll("a.ap-tab").forEach(tab => {
                const tabUrl = new URL(tab.href);
                ["q", "category"].forEach(key => {
                    if (params.get(key)) tabUrl.searchParams.set(key, params.get(key));
                    else tabUrl.searchParams.delete(key);
                });
                tab.href = tabUrl.toString();
            });
            if (clear) clear.hidden = [...params.keys()].every(key => key === "status" || key === "page");
        }

        function apply(delay) {
            clearTimeout(timer);
            timer = setTimeout(() => update(`${location.pathname}?${queryFor(live)}`), delay);
        }

        live.addEventListener("input", event => { if (event.target.type === "search") apply(300); });
        live.addEventListener("change", event => {
            if (event.target === joined && range) range.hidden = joined.value !== "custom";
            if (event.target.type !== "search") apply(0);
        });
        live.addEventListener("submit", event => { event.preventDefault(); apply(0); });
        // Previous / Next pages without reloading
        results.addEventListener("click", event => {
            const link = event.target.closest(".ap-pagination a");
            if (!link) return;
            event.preventDefault();
            update(link.href);
            results.scrollIntoView({ behavior: "smooth", block: "start" });
        });
    }

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
        const pad = { top: 12, right: 88, bottom: 26, left: 34 };
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

        // Lines, then a direct label at each line's end (identity is never colour alone)
        const ends = [];
        data.series.forEach(s => {
            const points = s.values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
            svg.append(el("polyline", { points, fill: "none", stroke: color(s.key), "stroke-width": 2,
                                        "stroke-linejoin": "round", "stroke-linecap": "round" }));
            ends.push({ s, y: y(s.values[n - 1]) });
        });
        ends.sort((a, b) => a.y - b.y);
        for (let i = 1; i < ends.length; i++) ends[i].y = Math.max(ends[i].y, ends[i - 1].y + 14);   // no overlap
        ends.forEach(({ s, y: yy }) => {
            const label = el("text", { x: width - pad.right + 8, y: yy + 4, class: "ap-direct-label" });
            label.textContent = s.label;
            svg.append(label);
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
