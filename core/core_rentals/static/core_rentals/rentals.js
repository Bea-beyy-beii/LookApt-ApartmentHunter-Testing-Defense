// =========================================================
// MANAGE RENTALS (landlord dashboard)
// Search + Filter dropdown + Archive, collapse a complex, ⋯ menu, and the pop-ups:
// Assign a Renter, Mark as Paid, Complete/Terminate, Renew, Message tenant.
// (Post on Bulletin lives on the Calendar tab: core_calendar/calendar.js.)
// The server re-checks everything; after a change the tab reloads.
// =========================================================

(function () {

    function csrfToken() {
        const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    async function postJSON(url, data) {
        const response = await fetch(url, {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json", "Accept": "application/json", "X-CSRFToken": csrfToken() },
            body: JSON.stringify(data),
        });
        const body = await response.json().catch(() => ({}));
        if (response.status === 403 && !body.errors) {
            body.errors = { __all__: "Your session changed (you may have logged out or switched accounts in another tab). Refresh the page and try again." };
        }
        return { ok: response.ok, body };
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

    // After a change: show the message after the reload, stay on this tab
    function reloadWith(message) {
        try { sessionStorage.setItem("lookapt:rentals:toast", message); } catch (error) { /* ignore */ }
        location.reload();
    }

    function localISO(date) {
        const pad = n => String(n).padStart(2, "0");
        return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
    }

    // Shared dialog helpers (errors, close on backdrop / ✕ / Cancel)
    function setupDialog(dialog) {
        const formError = dialog.querySelector("[data-form-error]");
        dialog.addEventListener("click", event => { if (event.target === dialog) dialog.close(); });
        dialog.querySelectorAll("[data-modal-close]").forEach(b => b.addEventListener("click", () => dialog.close()));

        return {
            clear() {
                if (formError) formError.hidden = true;
                dialog.querySelectorAll("[data-error-for]").forEach(p => { p.hidden = true; });
            },
            show(errors) {
                this.clear();
                for (const [field, message] of Object.entries(errors)) {
                    const target = dialog.querySelector(`[data-error-for="${field}"]`) || formError;
                    target.textContent = message;
                    target.hidden = false;
                }
            },
        };
    }

    async function submitWith(button, label, work) {
        button.disabled = true;
        const original = button.textContent;
        button.textContent = label;
        try {
            await work();
        } finally {
            button.disabled = false;
            button.textContent = original;
        }
    }


    // =====================================================
    // SEARCH + FILTER DROPDOWN + ARCHIVE
    // Within a group a unit needs to match one ticked option (Vacant OR
    // Occupied); across groups it must match every group (Vacant AND Overdue).
    // =====================================================

    function initFilters(page) {
        const search = page.querySelector("[data-rental-search]");
        const current = page.querySelector("[data-rental-current]");
        const archive = page.querySelector("[data-rental-archive]");
        const noResults = page.querySelector("[data-no-results]");
        const toggle = page.querySelector("[data-filter-toggle]");
        const panel = page.querySelector("[data-filter-panel]");
        const badge = page.querySelector("[data-filter-count]");
        const allComplexes = panel.querySelector('[data-filter-all="complex"]');
        const archiveButton = page.querySelector("[data-archive-toggle]");
        const boxes = [...panel.querySelectorAll("[data-filter]")];
        let showArchive = false;

        // {complex: Set, state: Set, pay: Set, ending: Set} of ticked values
        function chosen() {
            const groups = {};
            boxes.filter(b => b.checked).forEach(b => {
                (groups[b.dataset.filter] = groups[b.dataset.filter] || new Set()).add(b.value);
            });
            return groups;
        }

        function rowMatches(row, groups) {
            // An empty pay value (no tenancy) never matches a Payments filter
            return Object.entries(groups).every(([key, values]) => values.has(row.dataset[key] || ""));
        }

        function apply() {
            const query = search.value.trim().toLowerCase();
            const groups = showArchive ? {} : chosen();
            const filtering = Object.keys(groups).length > 0;
            current.hidden = showArchive;
            archive.hidden = !showArchive;

            let anyVisible = false;
            const sections = showArchive ? [archive] : [...current.querySelectorAll("[data-rental-complex]")];
            sections.forEach(section => {
                const rows = [...section.querySelectorAll("[data-rental-row]")];
                let visible = 0;
                rows.forEach(row => {
                    const show = rowMatches(row, groups) && (!query || row.dataset.search.toLowerCase().includes(query));
                    row.hidden = !show;
                    if (show) visible++;
                });
                if (!showArchive) {
                    const complexPicked = !groups.complex || groups.complex.has(section.dataset.complex);
                    // A complex with no matching units disappears while filtering / searching
                    section.hidden = !complexPicked || (visible === 0 && (filtering || query) && rows.length > 0);
                }
                const empty = section.querySelector("[data-filter-empty]");
                if (empty) empty.hidden = !(rows.length && visible === 0);
                if (!section.hidden) anyVisible = true;
            });
            noResults.hidden = anyVisible || showArchive || !current.querySelector("[data-rental-complex]");

            const count = boxes.filter(b => b.checked).length;
            badge.textContent = count;
            badge.hidden = !count;
            toggle.classList.toggle("is-filtering", count > 0);
        }

        // ---------- open / close ----------
        function setOpen(open) {
            panel.hidden = !open;
            toggle.setAttribute("aria-expanded", String(open));
        }
        toggle.addEventListener("click", () => setOpen(panel.hidden));
        document.addEventListener("click", event => {
            if (!panel.hidden && !event.target.closest(".rt-filter-wrap")) setOpen(false);
        });
        document.addEventListener("keydown", event => { if (event.key === "Escape") setOpen(false); });

        // ---------- checkboxes ----------
        panel.addEventListener("change", event => {
            const box = event.target;
            if (box === allComplexes) {
                // "All" clears the individual complexes
                boxes.filter(b => b.dataset.filter === "complex").forEach(b => { b.checked = false; });
                allComplexes.checked = true;
            } else if (box.dataset.filter === "complex") {
                allComplexes.checked = !boxes.some(b => b.dataset.filter === "complex" && b.checked);
            }
            apply();
        });

        panel.querySelector("[data-filter-clear]").addEventListener("click", () => {
            boxes.forEach(b => { b.checked = false; });
            allComplexes.checked = true;
            apply();
        });

        // ---------- archive ----------
        archiveButton.addEventListener("click", () => {
            showArchive = !showArchive;
            archiveButton.classList.toggle("active", showArchive);
            archiveButton.setAttribute("aria-pressed", String(showArchive));
            toggle.disabled = showArchive;          // archived contracts have no unit filters
            setOpen(false);
            apply();
        });

        search.addEventListener("input", apply);
        apply();
    }


    // =====================================================
    // COLLAPSE + ⋯ MENU
    // =====================================================

    function initCollapse(page) {
        page.querySelectorAll("[data-collapse]").forEach(button => {
            button.addEventListener("click", () => {
                const section = button.closest("[data-rental-complex]");
                const collapsed = section.classList.toggle("is-collapsed");
                button.setAttribute("aria-expanded", String(!collapsed));
            });
        });
    }

    function initMenus() {
        const closeAll = except => document.querySelectorAll(".rt-menu:not([hidden])").forEach(menu => {
            if (menu === except) return;
            menu.hidden = true;
            menu.previousElementSibling.setAttribute("aria-expanded", "false");
        });

        // The menu is position: fixed, so place it under the ⋯ button
        // (or above it when there isn't enough room below)
        function place(menu, toggle) {
            const gap = 6, edge = 8;
            const button = toggle.getBoundingClientRect();
            const { width, height } = menu.getBoundingClientRect();
            const below = window.innerHeight - button.bottom - gap - edge;
            let top = button.bottom + gap;
            if (height > below && button.top - gap - edge > below) top = button.top - gap - height;
            const left = Math.min(Math.max(edge, button.right - width), window.innerWidth - width - edge);
            // The page is drawn at --ui-zoom (90%): measurements come back in
            // screen pixels, but top/left are applied before the zoom
            const zoom = parseFloat(getComputedStyle(document.documentElement).zoom) || 1;
            menu.style.top = `${Math.max(edge, top) / zoom}px`;
            menu.style.left = `${left / zoom}px`;
        }

        document.addEventListener("click", event => {
            const toggle = event.target.closest("[data-menu-toggle]");
            if (toggle) {
                const menu = toggle.nextElementSibling;
                closeAll(menu);
                menu.hidden = !menu.hidden;
                toggle.setAttribute("aria-expanded", String(!menu.hidden));
                if (!menu.hidden) place(menu, toggle);
                return;
            }
            if (!event.target.closest(".rt-menu")) closeAll();
        });
        document.addEventListener("keydown", event => { if (event.key === "Escape") closeAll(); });
        // A fixed menu would stay put while the page moves, so close it instead
        window.addEventListener("scroll", () => closeAll(), true);
        window.addEventListener("resize", () => closeAll());
    }


    // =====================================================
    // ASSIGN A RENTER
    // =====================================================

    function initAssign() {
        const dialog = document.querySelector("[data-assign-modal]");
        if (!dialog) return;
        const ui = setupDialog(dialog);
        const form = dialog.querySelector("[data-assign-form]");
        const select = form.elements.application;
        const hint = dialog.querySelector("[data-applicant-hint]");
        const submit = dialog.querySelector("[data-submit]");
        let unit = null;
        let candidates = [];

        function showSource(source) {
            dialog.querySelectorAll("[data-source]").forEach(el => { el.hidden = el.dataset.source !== source; });
        }

        function syncApplicant() {
            const chosen = candidates.find(c => c.id === select.value);
            if (chosen) {
                hint.textContent = `${chosen.kind} · ${chosen.occupants} tenant${chosen.occupants === 1 ? "" : "s"} · wants to move in ${chosen.move_in_label}`;
                form.elements.start_date.value = chosen.move_in;    // their requested move-in, editable
            } else {
                hint.textContent = "";
            }
        }

        document.addEventListener("click", event => {
            const button = event.target.closest("[data-open-assign]");
            if (!button) return;
            unit = button.dataset;
            try { candidates = JSON.parse(unit.candidates || "[]"); } catch (error) { candidates = []; }

            form.reset();
            ui.clear();
            dialog.querySelector("[data-assign-unit]").textContent = unit.unitName;
            dialog.querySelector("[data-assign-complex]").textContent = unit.complexName;
            dialog.querySelector("[data-assign-rent]").textContent = unit.rent;
            dialog.querySelector("[data-assign-lease]").textContent = `${unit.lease} lease`;
            form.elements.occupant_count.max = unit.maxOccupants;

            select.replaceChildren();
            if (candidates.length) {
                candidates.forEach(c => select.append(new Option(`${c.name} — ${c.kind}`, c.id)));
                form.elements.source.value = "applicant";
                showSource("applicant");
            } else {
                select.append(new Option("No pending applications for this unit", ""));
                form.elements.source.value = "guest";
                showSource("guest");
            }
            select.disabled = !candidates.length;
            form.elements.start_date.value = localISO(new Date());
            syncApplicant();
            dialog.showModal();
        });

        form.addEventListener("change", event => {
            if (event.target.name === "source") showSource(event.target.value);
            if (event.target === select) syncApplicant();
        });

        form.addEventListener("submit", event => {
            event.preventDefault();
            const guest = form.elements.source.value === "guest";
            const data = { start_date: form.elements.start_date.value };
            if (guest) {
                data.tenant_name = form.elements.tenant_name.value.trim();
                data.occupant_count = form.elements.occupant_count.value;
                if (!data.tenant_name) return ui.show({ tenant_name: "Type the tenant's full name." });
            } else {
                data.application = select.value;
                if (!data.application) return ui.show({ application: "Pick an applicant, or choose \"Someone not on LookApt\"." });
            }
            if (!data.start_date) return ui.show({ start_date: "Pick the date the rental starts." });

            submitWith(submit, "Assigning…", async () => {
                const result = await postJSON(unit.url, data);
                if (!result.ok) return ui.show(result.body.errors || { __all__: "Something went wrong. Please try again." });
                reloadWith(result.body.message);
            });
        });
    }


    // =====================================================
    // MARK AS PAID
    // =====================================================

    function initPay() {
        const dialog = document.querySelector("[data-pay-modal]");
        if (!dialog) return;
        const ui = setupDialog(dialog);
        const form = dialog.querySelector("[data-pay-form]");
        const list = dialog.querySelector("[data-pay-months]");
        const submit = dialog.querySelector("[data-submit]");
        let url = null;

        document.addEventListener("click", event => {
            const button = event.target.closest("[data-open-pay]");
            if (!button) return;
            url = button.dataset.url;
            ui.clear();
            dialog.querySelector("[data-pay-unit]").textContent = button.dataset.unitName;
            dialog.querySelector("[data-pay-tenant]").textContent = button.dataset.tenant;
            dialog.querySelector("[data-pay-rent]").textContent = button.dataset.rent;

            let months = [];
            try { months = JSON.parse(button.dataset.months || "[]"); } catch (error) { months = []; }
            const anyOverdue = months.some(m => m.overdue);

            list.replaceChildren(...months.map((month, i) => {
                const li = document.createElement("li");
                const label = document.createElement("label");
                label.className = `rt-month${month.overdue ? " is-overdue" : ""}`;
                const box = document.createElement("input");
                box.type = "checkbox";
                box.name = "months";
                box.value = month.value;
                // Overdue months are ticked by default; otherwise the next one
                box.checked = anyOverdue ? month.overdue : i === 0;
                const text = document.createElement("span");
                text.className = "rt-stack";
                const strong = document.createElement("strong");
                strong.textContent = month.label;
                const small = document.createElement("small");
                small.textContent = month.overdue ? `${month.due} · overdue` : month.due;
                text.append(strong, small);
                label.append(box, text);
                li.append(label);
                return li;
            }));
            dialog.showModal();
        });

        form.addEventListener("submit", event => {
            event.preventDefault();
            const months = [...form.querySelectorAll("input[name=months]:checked")].map(b => b.value);
            if (!months.length) return ui.show({ __all__: "Pick at least one month." });
            submitWith(submit, "Saving…", async () => {
                const result = await postJSON(url, { months });
                if (!result.ok) return ui.show(result.body.errors || { __all__: "Something went wrong. Please try again." });
                reloadWith(result.body.message);
            });
        });
    }


    // =====================================================
    // COMPLETE / TERMINATE
    // =====================================================

    function initEnd() {
        const dialog = document.querySelector("[data-end-modal]");
        if (!dialog) return;
        const ui = setupDialog(dialog);
        const form = dialog.querySelector("[data-end-form]");
        const submit = dialog.querySelector("[data-submit]");
        let target = null;

        document.addEventListener("click", event => {
            const button = event.target.closest("[data-open-end]");
            if (!button) return;
            button.closest(".rt-menu").hidden = true;
            target = button.dataset;
            const terminate = target.status === "terminated";
            ui.clear();
            dialog.querySelector("[data-end-title]").textContent = terminate ? "Terminate Contract?" : "Mark Contract as Complete?";
            dialog.querySelector("[data-end-text]").textContent =
                `${target.unitName} (${target.tenant}) will be marked as ${terminate ? "terminated" : "completed"}.`;
            dialog.querySelector("[data-end-icon]").classList.toggle("rt-icon-danger", terminate);
            submit.classList.toggle("rt-btn--danger", terminate);
            submit.classList.toggle("rt-btn--primary", !terminate);
            submit.textContent = terminate ? "Terminate Contract" : "Mark as Complete";
            dialog.showModal();
        });

        form.addEventListener("submit", event => {
            event.preventDefault();
            submitWith(submit, "Saving…", async () => {
                const result = await postJSON(target.url, { status: target.status });
                if (!result.ok) return ui.show(result.body.errors || { __all__: "Something went wrong. Please try again." });
                reloadWith(result.body.message);
            });
        });
    }


    // =====================================================
    // RENEW LEASE CONTRACT
    // =====================================================

    function initRenew() {
        const dialog = document.querySelector("[data-renew-modal]");
        if (!dialog) return;
        const ui = setupDialog(dialog);
        const form = dialog.querySelector("[data-renew-form]");
        const submit = dialog.querySelector("[data-submit]");
        let target = null;

        document.addEventListener("click", event => {
            const button = event.target.closest("[data-open-renew]");
            if (!button) return;
            button.closest(".rt-menu").hidden = true;
            target = button.dataset;
            ui.clear();
            dialog.querySelector("[data-renew-unit]").textContent = target.unitName;
            dialog.querySelector("[data-renew-tenant]").textContent = target.tenant;
            dialog.querySelector("[data-renew-lease]").textContent = target.lease;
            dialog.querySelector("[data-renew-current]").textContent = target.currentEnd;
            dialog.querySelector("[data-renew-new]").textContent = target.newEnd;
            dialog.showModal();
        });

        form.addEventListener("submit", event => {
            event.preventDefault();
            submitWith(submit, "Renewing…", async () => {
                const result = await postJSON(target.url, {});
                if (!result.ok) return ui.show(result.body.errors || { __all__: "Something went wrong. Please try again." });
                reloadWith(result.body.message);
            });
        });
    }


    // =====================================================
    // MESSAGE A TENANT (uses chat.js)
    // =====================================================

    function initTenantChat() {
        const dialog = document.querySelector("[data-tenant-chat]");
        const Chat = window.LookAptChat;
        if (!dialog || !Chat) return;

        const box = dialog.querySelector("[data-chat-messages]");
        const form = dialog.querySelector("[data-chat-form]");
        const textarea = form.elements.body;
        const error = dialog.querySelector("[data-chat-error]");
        const sendButton = form.querySelector(".lm-send");
        const emptyTemplate = dialog.querySelector("[data-chat-empty]");
        const thread = new Chat.Thread(box, { emptyNode: () => emptyTemplate.content.cloneNode(true) });
        let renter = null;

        function showError(message) {
            error.textContent = message;
            error.hidden = !message;
        }
        const picker = Chat.attachPicker(form, showError);

        document.addEventListener("click", async event => {
            const button = event.target.closest("[data-open-tenant-chat]");
            if (!button) return;
            renter = button.dataset.renter;
            dialog.querySelector("[data-chat-name]").textContent = button.dataset.name;
            Chat.setAvatar(dialog.querySelector("[data-chat-initials]"), button.dataset.avatar, button.dataset.initials, button.dataset.role);
            dialog.querySelector("[data-chat-subject]").textContent = button.dataset.subject;
            showError("");
            picker.clear();
            textarea.value = "";
            box.replaceChildren(Object.assign(document.createElement("p"), { className: "lm-chat-loading", textContent: "Loading…" }));
            dialog.showModal();
            textarea.focus();

            try {
                const response = await fetch(`${dialog.dataset.threadUrl}?${new URLSearchParams({ renter })}`, {
                    headers: { Accept: "application/json" }, credentials: "same-origin",
                });
                const data = await response.json();
                if (data.conversation) {
                    await thread.open(data.conversation.detail_url);
                } else {
                    thread.stop();
                    thread.showEmpty();
                }
                if (!data.can_send) showError("You can only message renters who rent from you, applied to your units, or messaged you first.");
            } catch (err) {
                thread.showEmpty();
            }
        });

        dialog.addEventListener("close", () => thread.stop());
        dialog.addEventListener("click", event => { if (event.target === dialog) dialog.close(); });
        dialog.querySelectorAll("[data-modal-close]").forEach(b => b.addEventListener("click", () => dialog.close()));

        textarea.addEventListener("keydown", event => {
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                form.requestSubmit();
            }
        });

        form.addEventListener("submit", async event => {
            event.preventDefault();
            const text = textarea.value.trim();
            const file = picker.file();
            if (!text && !file) return;
            sendButton.disabled = true;
            showError("");
            try {
                const result = await Chat.send(dialog.dataset.sendUrl, { renter, body: text }, file);
                if (!result.ok) return showError(Chat.firstError(result.data, "Couldn't send. Please try again."));
                thread.add([result.data.message]);
                if (!thread.timer) thread.follow(result.data.detail_url);
                textarea.value = "";
                picker.clear();
            } catch (err) {
                showError("Couldn't reach the server. Please try again.");
            } finally {
                sendButton.disabled = false;
                textarea.focus();
            }
        });
    }


    document.addEventListener("DOMContentLoaded", () => {
        const page = document.querySelector("[data-rentals]");
        if (!page) return;

        initFilters(page);
        initCollapse(page);
        initMenus();
        initAssign();
        initPay();
        initEnd();
        initRenew();
        initTenantChat();

        // Message saved before the reload (assign / pay / end / renew)
        try {
            const message = sessionStorage.getItem("lookapt:rentals:toast");
            if (message) {
                sessionStorage.removeItem("lookapt:rentals:toast");
                toast(message);
            }
        } catch (error) { /* ignore */ }
    });

})();