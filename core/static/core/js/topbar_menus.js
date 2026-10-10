// Top bar dropdowns (notification bell + profile menu).
// A [data-topbar-toggle] button opens the .topbar-menu right after it.
document.addEventListener("DOMContentLoaded", () => {
    const toggles = [...document.querySelectorAll("[data-topbar-toggle]")];
    if (!toggles.length) return;

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
    }));

    document.addEventListener("click", event => {
        if (!event.target.closest(".topbar-menu-wrap")) close();
    });
    document.addEventListener("keydown", event => { if (event.key === "Escape") close(); });
});