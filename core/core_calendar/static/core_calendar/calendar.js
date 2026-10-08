// =========================================================
// CALENDAR
// - Landlord Calendar tab ([data-cal-page]): Month / List, filters,
//   next 7 days, a day pop-up, and "Post on Bulletin".
// - "Your Schedule" widget ([data-cal-widget]) on the home pages:
//   Calendar View (small month + dots) and Events View (next 30 days).
// Items come from core_calendar.views.events_api.
// =========================================================

(function () {

    // ----- Helpers ----------------------------------------

    function csrfToken() {
        const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    function toast(message, kind = "success") {
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

    const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
                    "August", "September", "October", "November", "December"];
    const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

    const pad = n => String(n).padStart(2, "0");
    const iso = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    const parse = s => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
    const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
    const today = () => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), d.getDate()); };
    const shortDate = d => `${MONTHS[d.getMonth()].slice(0, 3)} ${d.getDate()}`;
    const longDate = d => `${DAYS[d.getDay()]}, ${MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;

    // First Sunday on/before the 1st; a month view is always 6 weeks
    function gridStart(month) {
        return addDays(month, -month.getDay());
    }

    // Same paths as core_listings/icons.py
    const ICONS = {
        megaphone: '<path d="M3 11v2a1 1 0 0 0 1 1h2l5 4V6L6 10H4a1 1 0 0 0-1 1Z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/>',
        wrench: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.5-.6-.6-2.5z"/>',
        coin: '<circle cx="12" cy="12" r="9"/><path d="M10 8h3a2 2 0 0 1 0 4h-3V8zm0 4v4M8.5 10h7M8.5 12h7"/>',
        calendar_check: '<rect x="4" y="5" width="16" height="16" rx="2"/><path d="M8 3v4M16 3v4M4 10h16"/><path d="m9 15 2 2 4-4"/>',
        document: '<path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5M9 12h7M9 16h5"/>',
    };
    const CATEGORIES = {
        announcement: { label: "Announcement", icon: "megaphone" },
        maintenance:  { label: "Maintenance / Inspection", icon: "wrench" },
        site_visit:   { label: "Site Visit", icon: "calendar_check" },
        rent:         { label: "Rental Due", icon: "coin" },
        contract:     { label: "Contract Event", icon: "document" },
    };

    function icon(category) {
        const name = (CATEGORIES[category] || CATEGORIES.announcement).icon;
        return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;
    }

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    // ----- Data -------------------------------------------

    const cache = new Map();

    async function fetchItems(url, start, end) {
        const key = `${url}|${iso(start)}|${iso(end)}`;
        if (!cache.has(key)) {
            const request = fetch(`${url}?start=${iso(start)}&end=${iso(end)}`, {
                credentials: "same-origin",
                headers: { "Accept": "application/json" },
            })
                .then(response => (response.ok ? response.json() : { items: [] }))
                .then(body => body.items || [])
                .catch(() => []);
            cache.set(key, request);
        }
        return cache.get(key);
    }

    // date (YYYY-MM-DD) -> items on that day; multi-day events land on every day
    function byDay(items, start, end) {
        const days = new Map();
        for (const item of items) {
            let day = parse(item.date);
            const last = parse(item.end_date || item.date);
            if (day < start) day = start;
            for (; day <= last && day <= end; day = addDays(day, 1)) {
                const key = iso(day);
                if (!days.has(key)) days.set(key, []);
                days.get(key).push(item);
            }
        }
        return days;
    }

    // One item as a list row
    function itemRow(item, { detailed = false, showDate = false } = {}) {
        const li = el("li", `cal-item cal-cat--${item.category}`);
        const badge = el("span", "cal-item-icon");
        badge.innerHTML = icon(item.category);
        li.append(badge);

        const body = el("div", "cal-item-body");
        body.append(el("strong", "", item.title));
        const meta = [];
        if (showDate) meta.push(shortDate(parse(item.date)) + (item.end_date !== item.date ? ` – ${shortDate(parse(item.end_date))}` : ""));
        if (item.time_label) meta.push(item.time_label);
        if (item.detail) meta.push(item.detail);
        if (meta.length) body.append(el("small", "", meta.join(" · ")));
        if (detailed) {
            body.append(el("span", "cal-item-type", item.type_label || CATEGORIES[item.category]?.label || ""));
            if (item.message) body.append(el("p", "cal-item-message", item.message));
        }
        li.append(body);
        return li;
    }

    function emptyRow(text) {
        return el("li", "cal-empty", text);
    }

    // Every calendar on the page listens for this (e.g. after a bulletin)
    const CHANGED = "lookapt:calendar-changed";


    // =====================================================
    // FULL CALENDAR (landlord Calendar tab)
    // =====================================================

    function initPage(page) {
        const url = page.dataset.eventsUrl;
        const title = page.querySelector("[data-cal-title]");
        const grid = page.querySelector("[data-cal-grid]");
        const monthView = page.querySelector("[data-cal-month]");
        const listView = page.querySelector("[data-cal-list]");
        const upcoming = page.querySelector("[data-cal-upcoming]");
        const viewButtons = [...page.querySelectorAll("[data-cal-view]")];
        const filters = [...page.querySelectorAll("[data-cal-filter]")];
        const dayModal = document.querySelector("[data-cal-day-modal]");

        let month = new Date(today().getFullYear(), today().getMonth(), 1);
        let view = "month";
        let days = new Map();

        const shown = () => new Set(filters.filter(f => f.checked).map(f => f.dataset.calFilter));
        const visible = items => { const on = shown(); return items.filter(i => on.has(i.category)); };

        async function render() {
            title.textContent = `${MONTHS[month.getMonth()]} ${month.getFullYear()}`;
            const start = gridStart(month), end = addDays(start, 41);
            const items = await fetchItems(url, start, end);
            days = byDay(items, start, end);
            renderMonth(start);
            renderList();
            renderUpcoming();
        }

        function renderMonth(start) {
            grid.replaceChildren();
            const now = iso(today());
            for (let i = 0; i < 42; i++) {
                const day = addDays(start, i);
                const key = iso(day);
                const items = visible(days.get(key) || []);

                const cell = el("div", "cal-cell");
                cell.dataset.date = key;
                cell.tabIndex = 0;
                cell.setAttribute("role", "button");
                cell.setAttribute("aria-label", `${longDate(day)}: ${items.length} item${items.length === 1 ? "" : "s"}`);
                if (day.getMonth() !== month.getMonth()) cell.classList.add("is-outside");
                if (key === now) cell.classList.add("is-today");
                cell.append(el("span", "cal-cell-day", String(day.getDate())));

                const limit = items.length > 3 ? 2 : 3;
                items.slice(0, limit).forEach(item => {
                    const chip = el("span", `cal-chip cal-cat--${item.category}`);
                    chip.innerHTML = icon(item.category);
                    chip.append(el("span", "", item.title));
                    chip.title = [item.title, item.time_label, item.detail].filter(Boolean).join(" · ");
                    cell.append(chip);
                });
                if (items.length > limit) cell.append(el("span", "cal-more", `+${items.length - limit} more`));
                grid.append(cell);
            }
        }

        function renderList() {
            listView.replaceChildren();
            const first = month, last = new Date(month.getFullYear(), month.getMonth() + 1, 0);
            let any = false;
            for (let day = first; day <= last; day = addDays(day, 1)) {
                const items = visible(days.get(iso(day)) || []);
                if (!items.length) continue;
                any = true;
                const group = el("section", "cal-list-day");
                if (iso(day) === iso(today())) group.classList.add("is-today");
                const head = el("header", "cal-list-date");
                head.append(el("strong", "", String(day.getDate())), el("span", "", `${DAYS[day.getDay()].slice(0, 3)}, ${MONTHS[day.getMonth()].slice(0, 3)}`));
                const list = el("ul", "cal-items cal-items--detailed");
                items.forEach(item => list.append(itemRow(item, { detailed: true })));
                group.append(head, list);
                listView.append(group);
            }
            if (!any) listView.append(el("p", "cal-empty cal-empty--big", "Nothing scheduled this month."));
        }

        async function renderUpcoming() {
            const start = today(), end = addDays(start, 6);
            const items = await fetchItems(url, start, end);
            const week = byDay(items, start, end);
            upcoming.replaceChildren();
            const seen = new Set();
            for (let day = start; day <= end; day = addDays(day, 1)) {
                for (const item of visible(week.get(iso(day)) || [])) {
                    if (seen.has(item)) continue;          // a whole-week event shows once
                    seen.add(item);
                    const li = el("li", `cal-up cal-cat--${item.category}`);
                    const date = el("span", "cal-up-date");
                    date.append(el("small", "", MONTHS[day.getMonth()].slice(0, 3).toUpperCase()), el("strong", "", String(day.getDate())));
                    const body = el("div", "cal-up-body");
                    const name = el("strong");
                    const badge = el("span", "cal-up-icon");
                    badge.innerHTML = icon(item.category);
                    name.append(badge, document.createTextNode(item.title));
                    body.append(name);
                    const meta = [item.time_label, item.detail].filter(Boolean).join(" · ");
                    if (meta) body.append(el("small", "", meta));
                    li.append(date, body);
                    upcoming.append(li);
                }
            }
            if (!upcoming.children.length) upcoming.append(emptyRow("Nothing in the next 7 days."));
        }

        function openDay(key) {
            if (!dayModal) return;
            const day = parse(key);
            const items = visible(days.get(key) || []);
            dayModal.querySelector("[data-day-modal-title]").textContent = longDate(day);
            dayModal.querySelector("[data-day-modal-sub]").textContent =
                items.length ? `${items.length} item${items.length === 1 ? "" : "s"}` : "Nothing scheduled.";
            const list = dayModal.querySelector("[data-day-modal-list]");
            list.replaceChildren(...items.map(item => itemRow(item, { detailed: true })));
            if (!items.length) list.append(emptyRow("Nothing scheduled on this day."));
            dayModal.showModal();
        }

        if (dayModal) {
            dayModal.addEventListener("click", event => { if (event.target === dayModal) dayModal.close(); });
            dayModal.querySelectorAll("[data-modal-close]").forEach(b => b.addEventListener("click", () => dayModal.close()));
        }
        grid.addEventListener("click", event => {
            const cell = event.target.closest(".cal-cell");
            if (cell) openDay(cell.dataset.date);
        });
        grid.addEventListener("keydown", event => {
            const cell = event.target.closest(".cal-cell");
            if (cell && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); openDay(cell.dataset.date); }
        });

        page.querySelector("[data-cal-prev]").addEventListener("click", () => { month = new Date(month.getFullYear(), month.getMonth() - 1, 1); render(); });
        page.querySelector("[data-cal-next]").addEventListener("click", () => { month = new Date(month.getFullYear(), month.getMonth() + 1, 1); render(); });
        page.querySelector("[data-cal-today]").addEventListener("click", () => { month = new Date(today().getFullYear(), today().getMonth(), 1); render(); });

        viewButtons.forEach(button => button.addEventListener("click", () => {
            view = button.dataset.calView;
            viewButtons.forEach(b => b.classList.toggle("active", b === button));
            monthView.hidden = view !== "month";
            listView.hidden = view !== "list";
        }));

        filters.forEach(filter => filter.addEventListener("change", () => {
            renderMonth(gridStart(month));
            renderList();
            renderUpcoming();
        }));

        document.addEventListener(CHANGED, render);
        render();
    }


    // =====================================================
    // "YOUR SCHEDULE" WIDGET (home pages)
    // =====================================================

    function initWidget(widget) {
        const url = widget.dataset.eventsUrl;
        const title = widget.querySelector("[data-cal-title]");
        const grid = widget.querySelector("[data-cal-grid]");
        const dayTitle = widget.querySelector("[data-day-title]");
        const dayList = widget.querySelector("[data-day-list]");
        const agenda = widget.querySelector("[data-agenda]");
        const tabs = [...widget.querySelectorAll("[data-widget-view]")];

        let month = new Date(today().getFullYear(), today().getMonth(), 1);
        let selected = iso(today());
        let days = new Map();

        async function render() {
            title.textContent = `${MONTHS[month.getMonth()]} ${month.getFullYear()}`;
            const start = gridStart(month), end = addDays(start, 41);
            days = byDay(await fetchItems(url, start, end), start, end);

            grid.replaceChildren();
            DAYS.forEach(name => grid.append(el("span", "cal-mini-weekday", name[0])));
            const now = iso(today());
            for (let i = 0; i < 42; i++) {
                const day = addDays(start, i);
                const key = iso(day);
                const items = days.get(key) || [];
                const cell = el("button", "cal-mini-cell");
                cell.type = "button";
                cell.dataset.date = key;
                cell.setAttribute("aria-label", `${longDate(day)}: ${items.length} item${items.length === 1 ? "" : "s"}`);
                if (day.getMonth() !== month.getMonth()) cell.classList.add("is-outside");
                if (key === now) cell.classList.add("is-today");
                if (key === selected) cell.classList.add("is-selected");
                cell.append(el("span", "", String(day.getDate())));
                const dots = el("span", "cal-dots");
                [...new Set(items.map(item => item.category))].slice(0, 3)
                    .forEach(category => dots.append(el("i", `cal-dot cal-cat--${category}`)));
                cell.append(dots);
                grid.append(cell);
            }
            renderDay();
        }

        function renderDay() {
            const day = parse(selected);
            dayTitle.textContent = selected === iso(today()) ? `Today · ${shortDate(day)}` : longDate(day);
            const items = days.get(selected) || [];
            dayList.replaceChildren(...items.map(item => itemRow(item)));
            if (!items.length) dayList.append(emptyRow("Nothing scheduled on this day."));
        }

        async function renderAgenda() {
            const start = today(), end = addDays(start, 30);
            const items = await fetchItems(url, start, end);
            agenda.replaceChildren(...items.map(item => itemRow(item, { showDate: true })));
            if (!agenda.children.length) agenda.append(emptyRow("Nothing scheduled in the next 30 days."));
        }

        grid.addEventListener("click", event => {
            const cell = event.target.closest(".cal-mini-cell");
            if (!cell) return;
            selected = cell.dataset.date;
            const day = parse(selected);
            if (day.getMonth() !== month.getMonth()) {
                month = new Date(day.getFullYear(), day.getMonth(), 1);
                render();
                return;
            }
            grid.querySelectorAll(".is-selected").forEach(c => c.classList.remove("is-selected"));
            cell.classList.add("is-selected");
            renderDay();
        });

        widget.querySelector("[data-cal-prev]").addEventListener("click", () => { month = new Date(month.getFullYear(), month.getMonth() - 1, 1); render(); });
        widget.querySelector("[data-cal-next]").addEventListener("click", () => { month = new Date(month.getFullYear(), month.getMonth() + 1, 1); render(); });

        tabs.forEach(tab => tab.addEventListener("click", () => {
            tabs.forEach(t => {
                t.classList.toggle("active", t === tab);
                t.setAttribute("aria-selected", String(t === tab));
            });
            widget.querySelectorAll("[data-widget-panel]").forEach(panel => {
                panel.hidden = panel.dataset.widgetPanel !== tab.dataset.widgetView;
            });
        }));

        document.addEventListener(CHANGED, () => { render(); renderAgenda(); });
        render();
        renderAgenda();
    }


    // =====================================================
    // POST ON BULLETIN (landlord Calendar tab)
    // =====================================================

    function initBulletin() {
        const dialog = document.querySelector("[data-bulletin-modal]");
        if (!dialog) return;
        const form = dialog.querySelector("[data-bulletin-form]");
        const picker = dialog.querySelector("[data-complex-picker]");
        const submit = dialog.querySelector("[data-submit]");
        const formError = dialog.querySelector("[data-form-error]");
        const timeFields = [...dialog.querySelectorAll("[data-time-field]")];

        function clearErrors() {
            formError.hidden = true;
            dialog.querySelectorAll("[data-error-for]").forEach(p => { p.hidden = true; });
        }

        function showErrors(errors) {
            clearErrors();
            for (const [field, message] of Object.entries(errors)) {
                const target = dialog.querySelector(`[data-error-for="${field}"]`) || formError;
                target.textContent = message;
                target.hidden = false;
            }
            (dialog.querySelector("[data-error-for]:not([hidden])") || formError).scrollIntoView({ block: "nearest" });
        }

        function updateCounts() {
            dialog.querySelectorAll("[data-count-target]").forEach(field => {
                const counter = dialog.querySelector(`[data-count-for="${field.dataset.countTarget}"]`);
                if (counter) counter.textContent = `${field.value.length}/${field.maxLength}`;
            });
        }

        function syncType() {
            const type = form.elements.event_type.value;
            dialog.querySelectorAll("[data-type-icon]").forEach(i => { i.hidden = i.dataset.typeIcon !== type; });
        }

        // Whole week: Sunday–Saturday, no times
        function syncWeek() {
            const week = form.elements.whole_week.checked;
            timeFields.forEach(field => {
                field.classList.toggle("is-disabled", week);
                const input = field.querySelector("input");
                input.disabled = week;
                if (week) input.value = "";
            });
        }

        dialog.addEventListener("click", event => { if (event.target === dialog) dialog.close(); });
        dialog.querySelectorAll("[data-modal-close]").forEach(b => b.addEventListener("click", () => dialog.close()));

        document.addEventListener("click", event => {
            if (!event.target.closest("[data-open-bulletin]")) return;
            form.reset();
            clearErrors();
            picker.hidden = true;
            form.elements.event_date.min = iso(today());
            updateCounts();
            syncType();
            syncWeek();
            dialog.showModal();
        });

        form.addEventListener("change", event => {
            if (event.target.name === "audience") picker.hidden = event.target.value !== "some";
            if (event.target.name === "event_type") syncType();
            if (event.target.name === "whole_week") syncWeek();
        });
        form.addEventListener("input", updateCounts);

        form.addEventListener("submit", async event => {
            event.preventDefault();
            const f = form.elements;
            const week = f.whole_week.checked;
            const errors = {};
            if (!f.message.value.trim()) errors.message = "Write your announcement first.";
            const complexes = [...form.querySelectorAll("input[name=complexes]:checked")].map(c => c.value);
            if (f.audience.value === "some" && !complexes.length) errors.complexes = "Pick at least one complex.";
            const start = week ? "" : f.start_time.value, end = week ? "" : f.end_time.value;
            if (!f.event_date.value && (start || end || week)) {
                errors.__all__ = "Pick a date for the event.";
            } else if (end && !start) {
                errors.__all__ = "Add a start time, or leave both times empty for an all-day event.";
            } else if (start && end && end <= start) {
                errors.__all__ = "The end time must be after the start time.";
            } else if (f.event_date.value && f.event_date.value < iso(today())) {
                errors.__all__ = "The event can't be in the past.";
            }
            if (Object.keys(errors).length) return showErrors(errors);

            submit.disabled = true;
            const label = submit.textContent;
            submit.textContent = "Publishing…";
            try {
                const response = await fetch(form.dataset.url, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: { "Content-Type": "application/json", "Accept": "application/json", "X-CSRFToken": csrfToken() },
                    body: JSON.stringify({
                        audience: f.audience.value,
                        complexes,
                        message: f.message.value,
                        event_date: f.event_date.value,
                        start_time: start,
                        end_time: end,
                        whole_week: week,
                        event_title: f.event_title.value,
                        event_type: f.event_type.value,
                    }),
                });
                const body = await response.json().catch(() => ({}));
                if (!response.ok) {
                    return showErrors(body.errors || (response.status === 403
                        ? { __all__: "Your session changed (you may have logged out or switched accounts in another tab). Refresh the page and try again." }
                        : { __all__: "Something went wrong. Please try again." }));
                }
                dialog.close();
                toast(body.message);
                cache.clear();
                document.dispatchEvent(new CustomEvent(CHANGED));
            } catch (error) {
                showErrors({ __all__: "Couldn't reach the server. Check your connection and try again." });
            } finally {
                submit.disabled = false;
                submit.textContent = label;
            }
        });
    }


    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("[data-cal-page]").forEach(initPage);
        document.querySelectorAll("[data-cal-widget]").forEach(initWidget);
        initBulletin();
    });
})();