// =========================================================
// MY LISTINGS — complex + unit cards
// Galleries, expand/collapse, ⋮ menus, confirmation pop-up,
// complex delete/visibility, unit delete/availability, filters.
// =========================================================

(function () {

    // ---------------------------------------------------------
    // HELPERS
    // ---------------------------------------------------------

    function getCookie(name) {
        const match = document.cookie.split("; ").find(row => row.startsWith(name + "="));
        return match ? decodeURIComponent(match.split("=")[1]) : null;
    }

    function csrfToken() {
        const input = document.querySelector("[name=csrfmiddlewaretoken]");
        return getCookie("csrftoken") || (input ? input.value : "");
    }

    async function postAction(url, data = {}) {
        const response = await fetch(url, {
            method: "POST",
            headers: { "X-CSRFToken": csrfToken(), "Accept": "application/json" },
            body: new URLSearchParams(data),
            credentials: "same-origin",
        });

        let payload = {};
        try {
            payload = await response.json();
        } catch (error) {
            /* not JSON: e.g. logged out → login page */
        }

        if (!response.ok || payload.error) {
            throw new Error(payload.error || "Something went wrong. Please try again.");
        }
        return payload;
    }

    function showToast(message) {
        const toast = document.querySelector(".listing-toast");
        if (!toast) return;
        toast.textContent = message;
        toast.hidden = false;
        clearTimeout(showToast.timer);
        showToast.timer = setTimeout(() => { toast.hidden = true; }, 3000);
    }
    


    // ---------------------------------------------------------
    // EXPAND / COLLAPSE UNITS
    // ---------------------------------------------------------

    function toggleUnits(card) {
        const units = card.querySelector(".property-units");
        const button = card.querySelector("[data-property-expand]");
        const open = units.hidden;

        units.hidden = !open;
        card.classList.toggle("expanded", open);
        if (button) button.setAttribute("aria-expanded", String(open));
    }


    // ---------------------------------------------------------
    // ⋮ MENUS
    // ---------------------------------------------------------

    function closeMenus() {
        document.querySelectorAll(".property-menu").forEach(menu => { menu.hidden = true; });
        document.querySelectorAll("[data-property-menu-toggle]")
            .forEach(button => button.setAttribute("aria-expanded", "false"));
    }

    function toggleMenu(button) {
        const menu = button.nextElementSibling;
        const willOpen = menu.hidden;

        closeMenus();
        menu.hidden = !willOpen;
        button.setAttribute("aria-expanded", String(willOpen));

        if (willOpen) {
            placeMenu(menu, button);
            const first = menu.querySelector(".property-menu-item:not([hidden])");
            if (first) first.focus({ preventScroll: true });
        }
    }

    // Open the ⋮ menu where it fits: above the button when there isn't room below
    // (e.g. the last unit card at the bottom of the page), never past the window's edges
    function placeMenu(menu, button) {
        const gap = 6, edge = 8;
        menu.classList.remove("is-up", "is-left");
        menu.style.maxHeight = "";
        const toggle = button.getBoundingClientRect();
        const below = window.innerHeight - toggle.bottom - gap - edge;
        const above = toggle.top - gap - edge;
        const height = menu.scrollHeight;
        if (height > below && above > below) menu.classList.add("is-up");
        const room = menu.classList.contains("is-up") ? above : below;
        // The page is drawn at --ui-zoom: measurements are screen pixels, max-height is applied before the zoom
        const zoom = parseFloat(getComputedStyle(document.documentElement).zoom) || 1;
        if (height > room) menu.style.maxHeight = `${Math.max(160, room) / zoom}px`;     // scroll inside instead of running off
        if (menu.getBoundingClientRect().left < edge) menu.classList.add("is-left");
    }


    // ---------------------------------------------------------
    // CONFIRMATION POP-UP
    // ---------------------------------------------------------

    const ICONS = {
        trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7h16M10 11v6M14 11v6M5 7l1 13h12l1-13M9 7V4h6v3"/></svg>',
        eye: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2.5 12S6 5 12 5s9.5 7 9.5 7-3.5 7-9.5 7-9.5-7-9.5-7Z"/><circle cx="12" cy="12" r="3"/></svg>',
        eyeOff: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3l18 18M10.6 5.1A9.8 9.8 0 0 1 12 5c6 0 9.5 7 9.5 7a17 17 0 0 1-3.2 4.1M6.6 6.6C3.9 8.4 2.5 12 2.5 12S6 19 12 19a9.4 9.4 0 0 0 5.4-1.6M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>',
    };

    let pendingAction = null;

    function openConfirm({ title, before, name, after, confirmLabel, variant, icon, onConfirm }) {
        const dialog = document.getElementById("listing-confirm-dialog");
        if (!dialog) return;

        dialog.querySelector("[data-confirm-title]").textContent = title;

        const message = dialog.querySelector("[data-confirm-message]");
        const strong = document.createElement("strong");
        strong.textContent = name;
        message.replaceChildren(before, strong, after);

        const iconBox = dialog.querySelector("[data-confirm-icon]");
        iconBox.innerHTML = ICONS[icon];
        iconBox.className = `confirm-dialog-icon confirm-dialog-icon--${variant}`;

        const ok = dialog.querySelector("[data-confirm-ok]");
        ok.textContent = confirmLabel;
        ok.dataset.label = confirmLabel;
        ok.className = `dialog-btn dialog-btn--${variant}`;
        ok.disabled = false;

        dialog.querySelector("[data-confirm-error]").hidden = true;

        pendingAction = onConfirm;
        dialog.showModal();
    }


    // ---------------------------------------------------------
    // COMPLEX ACTIONS
    // ---------------------------------------------------------

    function confirmComplexDelete(card) {
        openConfirm({
            title: "Delete Complex",
            before: "Are you sure you want to delete ",
            name: card.dataset.propertyName,
            after: "? All related units will also be deleted. This action is irreversible and cannot be undone.",
            confirmLabel: "Delete Complex",
            variant: "danger",
            icon: "trash",
            onConfirm: async () => {
                await postAction(card.dataset.deleteUrl);
                fadeOut(card, updatePropertyCounts);
                showToast(`${card.dataset.propertyName} was deleted.`);
            },
        });
    }

    function confirmVisibility(card, visibility) {
        const makePublic = visibility === "active";

        openConfirm({
            title: makePublic ? "Make Complex Public" : "Unpublish Complex",
            before: "",
            name: card.dataset.propertyName,
            after: makePublic
                ? " will be visible to renters once it's approved by an admin."
                : " will be hidden from renters. You can make it public again anytime.",
            confirmLabel: makePublic ? "Make Public" : "Set as Unpublished",
            variant: "primary",
            icon: makePublic ? "eye" : "eyeOff",
            onConfirm: async () => {
                const result = await postAction(card.dataset.visibilityUrl, { visibility });
                updateComplexStatus(card, result.status, result.label);
                showToast(`${card.dataset.propertyName} is now ${makePublic ? "public" : "unpublished"}.`);
            },
        });
    }

    function updateComplexStatus(card, status, label) {
        card.dataset.status = status;

        const pill = card.querySelector(".property-card-header .status-pill");
        pill.className = `status-pill status-pill--${status}`;
        pill.textContent = label;

        card.querySelectorAll('.property-card-header [data-action="set-visibility"]').forEach(item => {
            item.hidden = item.dataset.visibility === status;
        });

        // Units follow the complex: all unpublished while it is, their own status again once it's public
        card.querySelectorAll("[data-unit-card]").forEach(unitCard => showUnitStatus(unitCard, status === "unpublished"));
        updateUnitCounts(card);
        updatePropertyCounts();
    }


    // ---------------------------------------------------------
    // UNIT ACTIONS
    // ---------------------------------------------------------

    function confirmUnitDelete(unitCard) {
        const complexCard = unitCard.closest("[data-property-card]");

        openConfirm({
            title: "Delete Unit",
            before: "Are you sure you want to delete ",
            name: unitCard.dataset.unitName,
            after: "? Its photos and videos will also be deleted. This action cannot be undone.",
            confirmLabel: "Delete Unit",
            variant: "danger",
            icon: "trash",
            onConfirm: async () => {
                await postAction(unitCard.dataset.deleteUrl);
                fadeOut(unitCard, () => updateUnitCounts(complexCard));
                showToast(`${unitCard.dataset.unitName} was deleted.`);
            },
        });
    }

    const UNIT_LABELS = { available: "Available", occupied: "Occupied", unpublished: "Unpublished" };

    // The card shows "Unpublished" while the complex is unpublished; the unit's
    // own status (data-own-availability) is kept and shown again afterwards.
    function showUnitStatus(unitCard, complexUnpublished) {
        const own = unitCard.dataset.ownAvailability;
        const shown = complexUnpublished ? "unpublished" : own;
        unitCard.dataset.availability = shown;

        const pill = unitCard.querySelector("[data-unit-status]");
        pill.className = `unit-status unit-status--${shown}`;
        pill.textContent = UNIT_LABELS[shown];
        pill.title = complexUnpublished ? "Hidden because the complex is unpublished" : "";

        unitCard.querySelectorAll('[data-action="unit-availability"]').forEach(item => {
            item.hidden = complexUnpublished || item.dataset.availability === own;
        });
        const note = unitCard.querySelector("[data-unit-locked]");
        if (note) note.hidden = !complexUnpublished;
    }

    async function setUnitAvailability(unitCard, availability) {
        try {
            const result = await postAction(unitCard.dataset.availabilityUrl, { availability });

            unitCard.dataset.ownAvailability = result.availability;
            showUnitStatus(unitCard, false);

            updateUnitCounts(unitCard.closest("[data-property-card]"));
            showToast(`${unitCard.dataset.unitName} is now ${result.label.toLowerCase()}.`);
        } catch (error) {
            showToast(error.message);
        }
    }


    // ---------------------------------------------------------
    // MENU CLICKS
    // ---------------------------------------------------------

    function handleMenuAction(item) {
        const action = item.dataset.action;
        if (!action) return;   // plain links (e.g. Edit Unit) just navigate

        closeMenus();

        const unitCard = item.closest("[data-unit-card]");
        if (unitCard) {
            if (action === "unit-delete") confirmUnitDelete(unitCard);
            if (action === "unit-availability") setUnitAvailability(unitCard, item.dataset.availability);
            return;
        }

        const card = item.closest("[data-property-card]");
        if (action === "delete") confirmComplexDelete(card);
        if (action === "set-visibility") confirmVisibility(card, item.dataset.visibility);
    }


    // ---------------------------------------------------------
    // COUNTS (no page reload)
    // ---------------------------------------------------------

    function fadeOut(element, after) {
        element.classList.add("is-removing");
        setTimeout(() => {
            element.remove();
            after();
        }, 250);
    }

    function updatePropertyCounts() {
        const cards = [...document.querySelectorAll("[data-property-card]")];
        const counts = {
            all: cards.length,
            active: cards.filter(card => card.dataset.status === "active").length,
            unpublished: cards.filter(card => card.dataset.status === "unpublished").length,
        };

        Object.entries(counts).forEach(([status, count]) => {
            const badge = document.querySelector(`[data-status-filter="${status}"] .status-filter-count`);
            if (badge) badge.textContent = count;
        });

        const activeChip = document.querySelector("[data-status-filter].active");
        if (activeChip) filterProperties(activeChip);

        if (counts.all === 0) window.location.reload();   // show the empty state
    }

    function updateUnitCounts(card) {
        const units = [...card.querySelectorAll("[data-unit-card]")];
        if (!units.length) {
            window.location.reload();   // show "No units yet"
            return;
        }

        const counts = {
            total: units.length,
            available: units.filter(unit => unit.dataset.availability === "available").length,
            occupied: units.filter(unit => unit.dataset.availability === "occupied").length,
            unpublished: units.filter(unit => unit.dataset.availability === "unpublished").length,
        };

        Object.entries(counts).forEach(([key, value]) => {
            card.querySelectorAll(`[data-stat="${key}"]`).forEach(node => { node.textContent = value; });
        });

        filterUnits(card.querySelector(".property-units"));
    }


    // ---------------------------------------------------------
    // FILTERS
    // ---------------------------------------------------------

    function filterProperties(button) {
        const status = button.dataset.statusFilter;
        let visible = 0;

        document.querySelectorAll("[data-status-filter]")
            .forEach(chip => chip.classList.toggle("active", chip === button));

        document.querySelectorAll("[data-property-card]").forEach(card => {
            const show = status === "all" || card.dataset.status === status;
            card.hidden = !show;
            if (show) visible += 1;
        });

        const empty = document.querySelector(".properties-filter-empty");
        if (empty) empty.hidden = visible > 0;
    }

    function filterUnits(section) {
        if (!section) return;

        const search = section.querySelector("[data-unit-search]");
        const query = search ? search.value.trim().toLowerCase() : "";
        const active = section.querySelector(".unit-filter.active");
        const status = active ? active.dataset.unitFilter : "all";
        let visible = 0;

        section.querySelectorAll("[data-unit-card]").forEach(unit => {
            const matchesText = !query || unit.dataset.unitName.toLowerCase().includes(query);
            const matchesStatus = status === "all" || unit.dataset.availability === status;
            unit.hidden = !(matchesText && matchesStatus);
            if (!unit.hidden) visible += 1;
        });

        const empty = section.querySelector(".units-filter-empty");
        if (empty) empty.hidden = visible > 0;
    }


    // ---------------------------------------------------------
    // EVENTS
    // ---------------------------------------------------------

    // Clicks on these never collapse/expand the complex
    const INTERACTIVE = "a, button, input, select, textarea, label, video, .property-menu";

    document.addEventListener("click", event => {
        const target = event.target;

        if (!target.closest(".property-menu-wrap")) closeMenus();

        const expand = target.closest("[data-property-expand]");
        if (expand) return toggleUnits(expand.closest("[data-property-card]"));

        const menuToggle = target.closest("[data-property-menu-toggle]");
        if (menuToggle) return toggleMenu(menuToggle);

        const menuItem = target.closest(".property-menu-item");
        if (menuItem) return handleMenuAction(menuItem);

        const statusChip = target.closest("[data-status-filter]");
        if (statusChip) return filterProperties(statusChip);

        const unitChip = target.closest("[data-unit-filter]");
        if (unitChip) {
            const section = unitChip.closest(".property-units");
            section.querySelectorAll(".unit-filter").forEach(chip => chip.classList.toggle("active", chip === unitChip));
            return filterUnits(section);
        }

        // Click anywhere else on a complex header → collapse / expand its units
        const header = target.closest(".property-card-header");
        if (header && !target.closest(INTERACTIVE) && !window.getSelection().toString()) {
            toggleUnits(header.closest("[data-property-card]"));
        }
    });

    document.addEventListener("input", event => {
        if (event.target.matches("[data-unit-search]")) {
            filterUnits(event.target.closest(".property-units"));
        }
    });

    document.addEventListener("keydown", event => {
        if (event.key === "Escape") closeMenus();
    });

    document.addEventListener("DOMContentLoaded", () => {

        const dialog = document.getElementById("listing-confirm-dialog");
        if (!dialog) return;

        const ok = dialog.querySelector("[data-confirm-ok]");
        const errorBox = dialog.querySelector("[data-confirm-error]");

        dialog.querySelector("[data-dialog-close]").addEventListener("click", () => dialog.close());

        ok.addEventListener("click", async () => {
            if (!pendingAction) return;

            ok.disabled = true;
            ok.textContent = "Working…";
            errorBox.hidden = true;

            try {
                await pendingAction();
                dialog.close();
            } catch (error) {
                errorBox.textContent = error.message;
                errorBox.hidden = false;
                ok.disabled = false;
                ok.textContent = ok.dataset.label;
            }
        });

        dialog.addEventListener("click", event => {
            if (event.target === dialog) dialog.close();
        });

        dialog.addEventListener("close", () => { pendingAction = null; });
    });

})();