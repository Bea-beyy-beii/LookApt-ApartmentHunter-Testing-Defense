// Top bar (landlord + renter pages): dark mode switch, notification bell, profile menu.
// A [data-topbar-toggle] button opens the .topbar-menu right after it.
document.addEventListener("DOMContentLoaded", () => {
    const toggles = [...document.querySelectorAll("[data-topbar-toggle]")];

    function csrf() {
        const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : document.querySelector(".topbar-right")?.dataset.csrf || "";
    }

    function post(url, data = {}) {
        return fetch(url, {
            method: "POST",
            credentials: "same-origin",
            headers: { "X-CSRFToken": csrf(), Accept: "application/json" },
            body: new URLSearchParams(data),
        });
    }

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

    // ---------------------------------------------------- dropdowns

    function close(except) {
        toggles.forEach(toggle => {
            const menu = toggle.nextElementSibling;
            if (menu === except) return;
            menu.hidden = true;
            toggle.setAttribute("aria-expanded", "false");
        });
    }

    toggles.forEach(toggle => toggle.addEventListener("click", () => {
        const menu = toggle.nextElementSibling;
        close(menu);
        menu.hidden = !menu.hidden;
        toggle.setAttribute("aria-expanded", String(!menu.hidden));
        if (!menu.hidden && toggle.matches("[data-notif-bell]")) markSeen(toggle);
    }));

    document.addEventListener("click", event => {
        if (!event.target.closest(".topbar-menu-wrap")) close();
    });
    document.addEventListener("keydown", event => { if (event.key === "Escape") close(); });

    // My Profile / Settings / Verification pages aren't built yet
    document.querySelectorAll("[data-coming-soon]").forEach(item => item.addEventListener("click", () => {
        close();
        toast(`${item.dataset.comingSoon} is coming soon.`);
    }));

    // ---------------------------------------------------- notification bell

    const bell = document.querySelector("[data-notif-bell]");

    function showDot(count) {
        const dot = bell.querySelector(".notification-dot");
        dot.hidden = !count;
        bell.setAttribute("aria-label", count ? `Notifications (${count} new)` : "Notifications");
    }

    async function loadNotifications() {
        try {
            const response = await fetch(bell.dataset.url, { credentials: "same-origin", headers: { Accept: "application/json" } });
            if (!response.ok) return;
            const data = await response.json();
            bell.nextElementSibling.querySelector("[data-notif-list]").innerHTML = data.html;
            // Bell already open: what just arrived is being looked at
            if (bell.getAttribute("aria-expanded") === "true") markSeen(bell);
            else showDot(data.new_count);
        } catch (error) { /* offline: keep the last list */ }
    }

    function markSeen() {
        showDot(0);
        post(bell.dataset.seenUrl).catch(() => {});
    }

    // "Clear all" in the bell and in the Inquiries tab's Notifications panel
    document.addEventListener("click", async event => {
        const button = event.target.closest("[data-notif-clear]");
        if (!button) return;
        button.disabled = true;
        try {
            const response = await post(button.dataset.url);
            if (!response.ok) throw new Error();
            if (bell) {
                bell.nextElementSibling.querySelector("[data-notif-list]").innerHTML =
                    '<p class="topbar-menu-empty">You\'re all caught up.</p>';
                showDot(0);
            }
            document.querySelector("[data-notif-panel-list]")?.remove();
            document.querySelector("[data-notif-badge]")?.remove();
            document.querySelectorAll(".notifications-clear").forEach(clear => clear.remove());
            const empty = document.querySelector("[data-notif-empty]");
            if (empty) empty.hidden = false;
        } catch (error) {
            toast("Couldn't clear your notifications. Please try again.", "error");
        } finally {
            button.disabled = false;
        }
    });

    if (bell) {
        loadNotifications();
        setInterval(() => { if (!document.hidden) loadNotifications(); }, 60000);
    }

    // ---------------------------------------------------- dark mode switch

    const themeSwitch = document.querySelector("[data-theme-switch]");
    const THEME_KEY = "lookapt:theme";

    function applyTheme(theme) {
        document.documentElement.dataset.theme = theme;
        themeSwitch?.setAttribute("aria-checked", String(theme === "dark"));
    }

    themeSwitch?.addEventListener("click", async () => {
        const theme = themeSwitch.getAttribute("aria-checked") === "true" ? "light" : "dark";
        applyTheme(theme);   // switch right away, save in the background
        try {
            sessionStorage.setItem(THEME_KEY, theme);
        } catch (error) { /* storage blocked */ }
        try {
            const response = await post(themeSwitch.dataset.url, { theme });
            if (!response.ok) throw new Error();
        } catch (error) {
            toast("Couldn't save your theme. It will reset when you reload.", "error");
        }
    });

    // Back / Forward shows the browser's saved copy of a page, rendered with the
    // theme it had back then. Bring it up to date with the last switch in this tab.
    function syncTheme(event) {
        const navigation = performance.getEntriesByType?.("navigation")[0];
        if (!event?.persisted && navigation?.type !== "back_forward") return;
        try {
            const theme = sessionStorage.getItem(THEME_KEY);
            if (theme === "dark" || theme === "light") applyTheme(theme);
        } catch (error) { /* storage blocked */ }
    }

    syncTheme();
    window.addEventListener("pageshow", syncTheme);
});