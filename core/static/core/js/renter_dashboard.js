document.addEventListener("DOMContentLoaded", () => {

    const tabLinks = document.querySelectorAll(".tab-link");
    const tabSections = document.querySelectorAll(".dashboard-tab");

    // Not a dashboard page: leave the links alone
    if (tabSections.length === 0) return;

    function showTab(tabName, updateURL = true) {

        // Lets the CSS change the top bar per tab (breadcrumbs, search bar...)
        document.body.dataset.tab = tabName;

        tabSections.forEach(section => {
            section.hidden = section.dataset.section !== tabName;
        });

        tabLinks.forEach(link => {
            link.classList.toggle(
                "active",
                link.dataset.tab === tabName
            );
        });

        if (updateURL) {
            // The renter's search / filters (renter_search.js) stay in the URL across tabs
            const query = new URLSearchParams(document.querySelector("[data-renter-search]") ? window.location.search : "");
            query.set("tab", tabName);
            window.history.pushState(
                { tab: tabName },
                "",
                `?${query}`
            );
        }
    }

    function getCurrentTab() {
        const params = new URLSearchParams(window.location.search);
        return params.get("tab") || "home";
    }

    tabLinks.forEach(link => {
        link.addEventListener("click", event => {
            event.preventDefault();

            showTab(link.dataset.tab);
        });
    });

    window.addEventListener("popstate", () => {

        const tabName = getCurrentTab();

        showTab(tabName, false);

        const activeLink = document.querySelector(
            `.tab-link[data-tab="${tabName}"] .sidebar-label`
        );

        window.Breadcrumbs?.setTab(
            tabName,
            activeLink
                ? activeLink.textContent.trim()
                : "Home"
        );
    });

    showTab(getCurrentTab(), false);
});

// "Find a place near what matters." banner: the ✕ hides it in this browser
document.addEventListener("DOMContentLoaded", () => {
    const banner = document.querySelector("[data-near-banner]");
    if (!banner) return;
    const KEY = "lookapt:hide-near-banner";

    try {
        if (localStorage.getItem(KEY) === "1") banner.hidden = true;
    } catch (error) { /* storage blocked: just show it */ }

    banner.querySelector("[data-near-banner-close]")?.addEventListener("click", () => {
        banner.hidden = true;
        try { localStorage.setItem(KEY, "1"); } catch (error) { /* closes for this visit only */ }
    });
});
