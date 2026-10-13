// =========================================================
// LANDLORD HOME TAB
// - cards / "Needs Your Attention" rows jump to the right tab
//   (and Inquiries sub-tab, or a Manage Rentals filter)
// - quick actions: Add Property, Post on Bulletin (calendar.js), Export Financials (a PDF link)
// - Monthly Receivables drawer (slides in on the right; < > loads another month)
// - Listing Performance chart (SVG, month dropdown, toggle lines)
// =========================================================

(function () {

    function toast(message, kind = "info") {
        let stack = document.querySelector(".toast-stack");
        if (!stack) {
            stack = document.createElement("div");
            stack.className = "toast-stack";
            stack.setAttribute("aria-live", "polite");
            document.body.append(stack);
        }
        const item = document.createElement("div");
        item.className = `toast toast--${kind}`;
        item.setAttribute("role", "status");
        item.innerHTML = '<span class="toast-text"></span>';
        item.firstChild.textContent = message;
        stack.append(item);
        setTimeout(() => { item.classList.add("is-leaving"); setTimeout(() => item.remove(), 300); }, 3500);
    }

    async function getJSON(url) {
        const response = await fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } });
        if (!response.ok) throw new Error(response.status);
        return response.json();
    }


    // =====================================================
    // GO TO A TAB (+ sub-tab / filter)
    // =====================================================

    function goTo(tab, { subtab, filter, property } = {}) {
        document.querySelector(`.sidebar .tab-link[data-tab="${tab}"]`)?.click();
        if (subtab) document.querySelector(`.inquiry-tab[data-tab="${subtab}"]`)?.click();
        if (filter) {
            // e.g. "pay:overdue" -> tick that box in Manage Rentals' Filter dropdown
            const [group, value] = filter.split(":");
            document.querySelector("[data-filter-clear]")?.click();
            const box = document.querySelector(`[data-filter="${group}"][value="${value}"]`);
            if (box) {
                box.checked = true;
                box.dispatchEvent(new Event("change", { bubbles: true }));
            }
        }
        // My Listings: open that complex's units and bring it into view
        const card = property && document.querySelector(`[data-property-card][data-property-id="${property}"]`);
        if (card) {
            const expand = card.querySelector("[data-property-expand]");
            if (expand?.getAttribute("aria-expanded") !== "true") expand?.click();
            card.scrollIntoView({ block: "start" });
            return;
        }
        window.scrollTo({ top: 0 });
    }

    function initLinks(root) {
        root.addEventListener("click", event => {
            const link = event.target.closest("[data-lh-goto]");
            if (link) {
                event.preventDefault();      // some are links (Managed Properties)
                goTo(link.dataset.lhGoto, {
                    subtab: link.dataset.lhSubtab, filter: link.dataset.lhFilter, property: link.dataset.lhProperty,
                });
                return;
            }
            if (event.target.closest("[data-lh-add-property]")) {
                goTo("myListings");
                if (typeof window.showPropertyForm === "function") window.showPropertyForm();
                return;
            }
        });
    }


    // =====================================================
    // MONTHLY RECEIVABLES DRAWER
    // =====================================================

    function initDrawer(root) {
        const drawer = root.querySelector("[data-lh-drawer]");
        const body = drawer.querySelector("[data-lh-drawer-body]");
        const card = root.querySelector("[data-lh-receivables]");

        function setOpen(open) {
            drawer.hidden = !open;
            card.setAttribute("aria-expanded", String(open));
            card.classList.toggle("is-active", open);
        }

        card.addEventListener("click", () => setOpen(drawer.hidden));
        // Clicking anywhere else on the page closes it (Mark as Paid's pop-up doesn't count)
        document.addEventListener("click", event => {
            // composedPath: still right when the clicked element was just replaced (month arrows)
            if (drawer.hidden || event.composedPath().some(node => node === drawer || node === card)) return;
            if (event.target.closest("dialog")) return;
            setOpen(false);
        });
        document.addEventListener("keydown", event => { if (event.key === "Escape" && !drawer.hidden) setOpen(false); });

        drawer.addEventListener("click", async event => {
            if (event.target.closest("[data-lh-drawer-close]")) return setOpen(false);

            const tab = event.target.closest("[data-lr-tab]");
            if (tab) {
                drawer.querySelectorAll("[data-lr-tab]").forEach(t => t.classList.toggle("active", t === tab));
                drawer.querySelectorAll("[data-lr-list]").forEach(list => { list.hidden = list.dataset.lrList !== tab.dataset.lrTab; });
                return;
            }

            const nav = event.target.closest("[data-lh-month-nav]");
            if (nav) {
                nav.disabled = true;
                try {
                    const data = await getJSON(`${drawer.dataset.url}?month=${nav.dataset.lhMonthNav}`);
                    body.innerHTML = data.html;      // rendered by the server (escaped)
                } catch (error) {
                    nav.disabled = false;
                    toast("Couldn't load that month. Please try again.", "error");
                }
            }
        });
    }


    // =====================================================
    // LISTING PERFORMANCE CHART
    // =====================================================

    const COLORS = { views: "#203a68", saves: "#f5b94c", inquiries: "#3b82f6", rentals: "#2f8a52" };
    const SVG_NS = "http://www.w3.org/2000/svg";

    function svgEl(tag, attrs) {
        const node = document.createElementNS(SVG_NS, tag);
        Object.entries(attrs || {}).forEach(([k, v]) => node.setAttribute(k, v));
        return node;
    }

    // A "nice" top value for the y-axis: 4, 8, 20, 40, 100, 200...
    function niceMax(value) {
        if (value <= 4) return 4;
        const step = 10 ** Math.floor(Math.log10(value));
        for (const m of [1, 2, 2.5, 5, 10]) if (m * step >= value) return m * step;
        return 10 * step;
    }

    function initChart(section) {
        const chips = section.querySelector("[data-lh-chips]");
        const chart = section.querySelector("[data-lh-chart]");
        const select = section.querySelector("[data-lh-month]");
        const hidden = new Set();
        let data = JSON.parse(document.getElementById("lh-performance-data").textContent);

        function renderChips() {
            chips.replaceChildren(...data.series.map(s => {
                const chip = document.createElement("button");
                chip.type = "button";
                chip.className = `lh-chip${hidden.has(s.key) ? " is-off" : ""}`;
                chip.setAttribute("aria-pressed", String(!hidden.has(s.key)));
                chip.title = hidden.has(s.key) ? "Show on chart" : "Hide from chart";
                chip.innerHTML = '<i></i><span><small></small><strong></strong></span><em></em>';
                chip.querySelector("i").style.background = COLORS[s.key];
                chip.querySelector("small").textContent = s.label;
                chip.querySelector("strong").textContent = s.total.toLocaleString();
                const change = chip.querySelector("em");
                if (s.change === null) {
                    change.textContent = "—";
                } else {
                    change.textContent = `${s.change >= 0 ? "↑" : "↓"} ${Math.abs(s.change)}%`;
                    change.className = s.change >= 0 ? "is-up" : "is-down";
                }
                chip.addEventListener("click", () => {
                    hidden.has(s.key) ? hidden.delete(s.key) : hidden.add(s.key);
                    renderChips();
                    renderChart();
                });
                return chip;
            }));
        }

        function renderChart() {
            const width = chart.clientWidth || 600, height = chart.clientHeight || 200;
            const pad = { top: 10, right: 12, bottom: 22, left: 34 };
            const w = width - pad.left - pad.right, h = height - pad.top - pad.bottom;
            const visible = data.series.filter(s => !hidden.has(s.key));
            const n = data.days.length;
            const max = niceMax(Math.max(1, ...visible.flatMap(s => s.values)));
            const x = i => pad.left + (n > 1 ? (i * w) / (n - 1) : w / 2);
            const y = v => pad.top + h - (v / max) * h;

            const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, width, height, role: "img",
                "aria-label": `Listing performance for ${data.month_label}` });

            // grid + y labels
            for (let i = 0; i <= 4; i++) {
                const value = (max / 4) * i, yy = y(value);
                svg.append(svgEl("line", { x1: pad.left, x2: width - pad.right, y1: yy, y2: yy, class: "lh-grid-line" }));
                const label = svgEl("text", { x: pad.left - 8, y: yy + 4, class: "lh-axis", "text-anchor": "end" });
                label.textContent = Number.isInteger(value) ? value : value.toFixed(1);
                svg.append(label);
            }
            // x labels: about 6 dates
            const every = Math.max(1, Math.ceil(n / 6));
            data.days.forEach((day, i) => {
                if (i % every && i !== n - 1) return;
                const label = svgEl("text", { x: x(i), y: height - 4, class: "lh-axis", "text-anchor": i === 0 ? "start" : i === n - 1 ? "end" : "middle" });
                label.textContent = day;
                svg.append(label);
            });

            if (!n) {
                const empty = svgEl("text", { x: width / 2, y: height / 2, class: "lh-axis", "text-anchor": "middle" });
                empty.textContent = "No data for this month yet.";
                svg.append(empty);
            }

            // lines (views get a soft area underneath)
            visible.forEach(s => {
                const points = s.values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
                if (!n) return;
                if (s.key === "views") {
                    svg.append(svgEl("polygon", {
                        points: `${x(0)},${y(0)} ${points} ${x(n - 1)},${y(0)}`, fill: COLORS.views, opacity: 0.07,
                    }));
                }
                svg.append(svgEl("polyline", { points, fill: "none", stroke: COLORS[s.key], "stroke-width": 2.2,
                    "stroke-linejoin": "round", "stroke-linecap": "round" }));
                if (n === 1) svg.append(svgEl("circle", { cx: x(0), cy: y(s.values[0]), r: 3.5, fill: COLORS[s.key] }));
            });

            if (n && visible.length) addHover(svg, { width, height, pad, n, x, y, visible });
            chart.replaceChildren(svg);
        }

        // Hover: a line on the nearest day, a dot on each line, and the day's numbers
        // (same as the admin Overview chart)
        const tip = document.createElement("div");
        tip.className = "lh-chart-tip";
        tip.hidden = true;
        chart.after(tip);

        function addHover(svg, { width, height, pad, n, x, y, visible }) {
            const cross = svgEl("line", { y1: pad.top, y2: height - pad.bottom, class: "lh-crosshair", visibility: "hidden" });
            svg.append(cross);
            const dots = visible.map(s => {
                const dot = svgEl("circle", { r: 4.5, fill: COLORS[s.key], class: "lh-dot", visibility: "hidden" });
                svg.append(dot);
                return dot;
            });
            const hit = svgEl("rect", { x: pad.left, y: pad.top, width: width - pad.left - pad.right,
                                        height: height - pad.top - pad.bottom, fill: "transparent" });
            svg.append(hit);

            function show(clientX) {
                const box = svg.getBoundingClientRect();
                const px = (clientX - box.left) * width / box.width;
                const step = n > 1 ? (width - pad.left - pad.right) / (n - 1) : 1;
                const i = Math.max(0, Math.min(n - 1, Math.round((px - pad.left) / step)));
                cross.setAttribute("x1", x(i));
                cross.setAttribute("x2", x(i));
                cross.setAttribute("visibility", "visible");
                visible.forEach((s, k) => {
                    dots[k].setAttribute("cx", x(i));
                    dots[k].setAttribute("cy", y(s.values[i]));
                    dots[k].setAttribute("visibility", "visible");
                });
                tip.replaceChildren();
                const day = document.createElement("strong");
                day.textContent = data.days[i];
                tip.append(day);
                visible.forEach(s => {
                    const row = document.createElement("span");
                    const swatch = document.createElement("i");
                    swatch.style.background = COLORS[s.key];
                    const value = document.createElement("b");
                    value.textContent = s.values[i].toLocaleString();
                    row.append(swatch, s.label, value);
                    tip.append(row);
                });
                tip.hidden = false;
                // CSS pixels (the page is zoomed, so not the screen pixels getBoundingClientRect gives);
                // flip to the left of the line when it would run past the chart's edge
                let left = chart.offsetLeft + x(i) + 14;
                if (left + tip.offsetWidth > chart.offsetLeft + chart.clientWidth) left = chart.offsetLeft + x(i) - tip.offsetWidth - 14;
                tip.style.left = `${Math.max(chart.offsetLeft, left)}px`;
                tip.style.top = `${chart.offsetTop + 6}px`;
            }
            function hide() {
                cross.setAttribute("visibility", "hidden");
                dots.forEach(dot => dot.setAttribute("visibility", "hidden"));
                tip.hidden = true;
            }
            hit.addEventListener("pointermove", event => show(event.clientX));
            hit.addEventListener("pointerdown", event => show(event.clientX));     // touch: tap to see a day
            hit.addEventListener("pointerleave", hide);
        }

        select.addEventListener("change", async () => {
            select.disabled = true;
            try {
                data = await getJSON(`${section.dataset.url}?month=${select.value}`);
                renderChips();
                renderChart();
            } catch (error) {
                toast("Couldn't load that month. Please try again.", "error");
            } finally {
                select.disabled = false;
            }
        });

        // Redraw when the layout changes (window resize, drawer opening, tab shown)
        new ResizeObserver(() => renderChart()).observe(chart);
        renderChips();
        renderChart();
    }


    // Mark as Paid (Manage Rentals tab) and Post on Bulletin (Calendar tab) are
    // also opened from Home. A <dialog> inside a hidden tab can't be seen, so
    // these two move to <body>; their listeners come along.
    function liftDialogs() {
        document.querySelectorAll("[data-pay-modal], [data-bulletin-modal]").forEach(dialog => document.body.append(dialog));
    }

    document.addEventListener("DOMContentLoaded", () => {
        liftDialogs();
        const root = document.querySelector("[data-lh]");
        if (!root) return;
        initLinks(root);
        initDrawer(root);
        initChart(root.querySelector("[data-lh-performance]"));
    });

})();