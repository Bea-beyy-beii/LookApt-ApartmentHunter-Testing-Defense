// Topbar breadcrumbs.
// On the dashboard the last crumb follows the active tab, and the
// in-page property wizard can push one extra crumb on top of it.
window.Breadcrumbs = {

    setTab(tabName, label) {
        const tab = document.querySelector("[data-crumb-tab]");
        if (!tab) return;

        const link = tab.querySelector(".crumb-link");
        link.textContent = label;
        link.href = `?tab=${tabName}`;
        link.onclick = null;

        this.pop();
    },

    push(label, onBack) {
        this.pop();

        const list = document.querySelector("[data-crumbs]");
        const tab = document.querySelector("[data-crumb-tab]");
        if (!list || !tab) return;

        // The tab crumb becomes a link back
        tab.removeAttribute("aria-current");
        tab.querySelector(".crumb-link").onclick = event => {
            event.preventDefault();
            onBack?.();
        };

        const li = document.createElement("li");
        li.className = "crumb";
        li.setAttribute("aria-current", "page");
        li.dataset.crumbExtra = "";
        li.innerHTML = '<span class="crumb-link"></span>';
        li.firstChild.textContent = label;
        list.appendChild(li);
    },

    pop() {
        document.querySelectorAll("[data-crumb-extra]").forEach(li => li.remove());
        document.querySelector("[data-crumb-tab]")?.setAttribute("aria-current", "page");
    },
};