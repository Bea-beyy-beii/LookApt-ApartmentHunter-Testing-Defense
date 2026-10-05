// =========================================================
// MY LISTINGS — complex cards
// Gallery arrows, expand units, ⋮ menu, confirmation pop-ups,
// delete / change visibility (POST to Django), filters.
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
            headers: {
                "X-CSRFToken": csrfToken(),
                "Accept": "application/json",
            },
            body: new URLSearchParams(data),
            credentials: "same-origin",
        });

        let payload = {};
        try {
            payload = await response.json();
        } catch (error) {
            // Not JSON: e.g. logged out → redirected to the login page
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
    // GALLERY (stops at the first / last photo)
    // ---------------------------------------------------------

    function initGallery(gallery) {
        const track = gallery.querySelector(".property-gallery-track");
        if (!track) return;

        const total = track.children.length;
        const position = gallery.querySelector("[data-gallery-position]");
        const prev = gallery.querySelector("[data-gallery-prev]");
        const next = gallery.querySelector("[data-gallery-next]");
        let index = 0;

        function show(newIndex) {
            index = Math.max(0, Math.min(total - 1, newIndex));
            track.style.transform = `translateX(-${index * 100}%)`;

            if (position) position.textContent = index + 1;
            if (prev) prev.disabled = index === 0;
            if (next) next.disabled = index === total - 1;
        }

        if (prev) prev.addEventListener("click", () => show(index - 1));
        if (next) next.addEventListener("click", () => show(index + 1));

        show(0);
    }


    // ---------------------------------------------------------
    // EXPAND UNITS
    // ---------------------------------------------------------

    function toggleUnits(card, button) {
        const units = card.querySelector(".property-units");
        const open = units.hidden;

        units.hidden = !open;
        card.classList.toggle("expanded", open);
        button.setAttribute("aria-expanded", String(open));
    }


    // ---------------------------------------------------------
    // ⋮ MENU
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
            const first = menu.querySelector(".property-menu-item:not([hidden])");
            if (first) first.focus();
        }
    }


    // ---------------------------------------------------------
    // CONFIRMATION POP-UP (one dialog, filled per action)
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

        // Message with the complex name in bold (textContent: names are user input)
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
    // ACTIONS
    // ---------------------------------------------------------

    function confirmDelete(card) {
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
                removeCard(card);
                showToast(`${card.dataset.propertyName} was deleted.`);
            },
        });
    }

    function confirmVisibility(card, visibility) {
        const makePublic = visibility === "active";

        openConfirm({
            title: makePublic ? "Make Complex Public" : "Unpublish Complex",
            before: makePublic ? "" : "",
            name: card.dataset.propertyName,
            after: makePublic
                ? " will be visible to renters once it's approved by an admin."
                : " will be hidden from renters. You can make it public again anytime.",
            confirmLabel: makePublic ? "Make Public" : "Set as Unpublished",
            variant: "primary",
            icon: makePublic ? "eye" : "eyeOff",
            onConfirm: async () => {
                const result = await postAction(card.dataset.visibilityUrl, { visibility });
                updateCardStatus(card, result.status, result.label);
                showToast(makePublic
                    ? `${card.dataset.propertyName} is now public.`
                    : `${card.dataset.propertyName} is now unpublished.`);
            },
        });
    }

    function handleMenuAction(item) {
        const card = item.closest("[data-property-card]");
        closeMenus();

        if (item.dataset.action === "delete") {
            confirmDelete(card);
        } else if (item.dataset.action === "set-visibility") {
            confirmVisibility(card, item.dataset.visibility);
        }
    }


    // ---------------------------------------------------------
    // UPDATE THE PAGE AFTER AN ACTION (no reload)
    // ---------------------------------------------------------

    function updateCounts() {
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

        // Re-apply the selected chip (e.g. an unpublished card leaves the "Active" view)
        const activeChip = document.querySelector("[data-status-filter].active");
        if (activeChip) filterProperties(activeChip);

        // Last card gone: reload to show the empty state
        if (counts.all === 0) window.location.reload();
    }

    function updateCardStatus(card, status, label) {
        card.dataset.status = status;

        const pill = card.querySelector(".status-pill");
        pill.className = `status-pill status-pill--${status}`;
        pill.textContent = label;

        // Show the menu item for the *other* state
        card.querySelectorAll('[data-action="set-visibility"]').forEach(item => {
            item.hidden = item.dataset.visibility === status;
        });

        updateCounts();
    }

    function removeCard(card) {
        card.classList.add("is-removing");
        setTimeout(() => {
            card.remove();
            updateCounts();
        }, 250);
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
        const search = section.querySelector("[data-unit-search]");
        const query = search ? search.value.trim().toLowerCase() : "";
        const active = section.querySelector(".unit-filter.active");
        const status = active ? active.dataset.unitFilter : "all";

        section.querySelectorAll(".units-list > *").forEach(unit => {
            const matchesText = !query || unit.textContent.toLowerCase().includes(query);
            const matchesStatus = status === "all" || unit.dataset.availability === status;
            unit.hidden = !(matchesText && matchesStatus);
        });
    }


    // ---------------------------------------------------------
    // EVENTS
    // ---------------------------------------------------------

    document.addEventListener("click", event => {
        const target = event.target;

        if (!target.closest(".property-menu-wrap")) closeMenus();

        const expand = target.closest("[data-property-expand]");
        if (expand) return toggleUnits(expand.closest("[data-property-card]"), expand);

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
        document.querySelectorAll("[data-gallery]").forEach(initGallery);

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