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

    if (bell) {
        loadNotifications();
        setInterval(() => { if (!document.hidden) loadNotifications(); }, 60000);
    }

    // ---------------------------------------------------- dark mode switch

    const themeSwitch = document.querySelector("[data-theme-switch]");
    themeSwitch?.addEventListener("click", async () => {
        const dark = themeSwitch.getAttribute("aria-checked") !== "true";
        const theme = dark ? "dark" : "light";
        document.documentElement.dataset.theme = theme;   // switch right away, save in the background
        themeSwitch.setAttribute("aria-checked", String(dark));
        try {
            const response = await post(themeSwitch.dataset.url, { theme });
            if (!response.ok) throw new Error();
        } catch (error) {
            toast("Couldn't save your theme. It will reset when you reload.", "error");
        }
    });
});