// =========================================================
// PREVIEW MODE (core_preview): /preview/renter/ and /preview/landlord/
// The real dashboard runs as usual; this file only decides what a visitor
// without an account may do. Allowed:
//   - the tabs in data-preview-tabs (renter: Home, Find Near; landlord: Home, My Listings)
//   - the map, filters, the listing cards' photos, the Add Property form's steps
// Anything else (another tab, opening a listing, Save, Publish, Post on Bulletin ...)
// opens the "Create a free account" prompt instead.
// =========================================================

(function () {

    const bar = document.querySelector("[data-preview]");
    const prompt = document.querySelector("[data-preview-prompt]");
    if (!bar || !prompt) return;

    const role = bar.dataset.preview;
    const allowedTabs = bar.dataset.previewTabs.split(",");
    const actionText = prompt.querySelector("[data-preview-action]");

    // What the prompt says for each locked tab: "Create a free account to …"
    const TAB_ACTIONS = {
        home: "continue",
        findNear: "find places near you",
        myListings: "manage your listings",
        saved: "save listings",
        rentals: role === "landlord" ? "manage your rentals" : "see your rentals",
        calendar: "use your calendar",
        inquiries: role === "landlord" ? "reply to renters" : "message landlords",
        reports: "file reports",
    };

    // Buttons that would save something or need an account
    const LOCKED_BUTTONS = [
        ["[data-save-listing]", "save listings"],
        ["[data-open-bulletin]", "post on the bulletin"],
        ["[data-open-report]", "file a report"],
        ["[data-export-financials]", "export your financials"],
        ["[data-lh-month-nav]", "see other months"],
        ["[data-lh-month]", "see other months"],
        ["button[type=submit], input[type=submit]",
            role === "landlord" ? "publish your property" : "continue"],
    ];

    document.body.classList.add("is-preview");

    function ask(action) {
        actionText.textContent = action || "continue";
        if (!prompt.open) prompt.showModal();
    }

    function block(event, action) {
        event.preventDefault();
        event.stopImmediatePropagation();
        ask(action);
    }

    // Why this click needs an account (null = it's allowed)
    function lockedAction(target) {
        if (!(target instanceof Element) || target.closest("[data-preview-prompt], .pv-topbar, .pv-bar")) return null;

        // (only real tab links: <body> carries data-tab too)
        const tab = target.closest(".tab-link[data-tab], [data-lh-goto]");
        if (tab) {
            const name = tab.dataset.tab || tab.dataset.lhGoto;
            return allowedTabs.includes(name) ? null : TAB_ACTIONS[name] || "open that page";
        }

        for (const [selector, action] of LOCKED_BUTTONS) {
            if (target.closest(selector)) return action;
        }

        const link = target.closest("a[href]");
        if (link) {
            const url = new URL(link.href, location.href);
            if (url.protocol === "mailto:" || url.protocol === "tel:") return null;
            if (url.origin === location.origin && url.pathname === location.pathname) return null;   // same page
            if (url.pathname.startsWith("/listing/")) return "view this listing";
            if (url.pathname.startsWith("/property/")) return "open your property";
            return "continue";
        }
        return null;
    }

    // Capture phase: runs before the dashboard's own click handlers
    document.addEventListener("click", event => {
        const action = lockedAction(event.target);
        if (action) block(event, action);
    }, true);

    // Pressing Enter in the Add Property form, or any other form
    document.addEventListener("submit", event => {
        block(event, role === "landlord" ? "publish your property" : "continue");
    }, true);

    // The month dropdown on the landlord chart would load real data
    document.querySelectorAll("[data-lh-month]").forEach(select => { select.disabled = true; });

    // Locked tabs in the sidebar get a small lock
    document.querySelectorAll(".sidebar .tab-link[data-tab]").forEach(link => {
        link.classList.toggle("pv-locked", !allowedTabs.includes(link.dataset.tab));
    });

    // Opened with ?tab=saved or similar: show Home instead
    const startTab = new URLSearchParams(location.search).get("tab");
    if (startTab && !allowedTabs.includes(startTab)) {
        document.querySelector(`.tab-link[data-tab="${allowedTabs[0]}"]`)?.click();
    }


    // ---------------------------------------------------- the map (an iframe on the same site)
    // Its "View listing →" pop-up links would leave the page: ask instead.

    function guardFrame(frame) {
        const attach = () => {
            let doc;
            try { doc = frame.contentDocument; } catch (error) { return; }
            if (!doc || doc.__previewGuarded) return;
            doc.__previewGuarded = true;
            doc.addEventListener("click", event => {
                const link = event.target.closest?.("a[href]");
                if (!link) return;
                event.preventDefault();
                event.stopImmediatePropagation();
                ask(new URL(link.href, location.href).pathname.startsWith("/listing/") ? "view this listing" : "continue");
            }, true);
        };
        frame.addEventListener("load", attach);
        if (frame.contentDocument?.readyState === "complete") attach();
    }

    document.querySelectorAll("iframe").forEach(guardFrame);
    new MutationObserver(changes => changes.forEach(change => change.addedNodes.forEach(node => {
        if (node.tagName === "IFRAME") guardFrame(node);
        else node.querySelectorAll?.("iframe").forEach(guardFrame);
    }))).observe(document.body, { childList: true, subtree: true });


    // ---------------------------------------------------- the prompt

    prompt.querySelectorAll("[data-preview-close]").forEach(button => button.addEventListener("click", () => prompt.close()));
    prompt.addEventListener("click", event => { if (event.target === prompt) prompt.close(); });   // click outside

})();