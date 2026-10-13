// =========================================================
// Styled dropdown lists for every <select> (core/css/components/custom_select.css)
//
// The <select> itself stays in the page as the closed box (same look, same
// form value, same "change" events), only its list is ours: clicking it or
// pressing Enter / Space / ↓ opens a styled list under it. Picking an option
// sets select.value and fires "input" + "change" like the browser would.
//
// Skipped: multi-selects, <select size>, data-native selects, and touch
// screens (their own pickers are easier to use there).
// =========================================================

(function () {

    if (window.matchMedia && window.matchMedia("(pointer: coarse)").matches) return;

    let open = null;            // { select, panel, items, active }

    function usable(select) {
        return select instanceof HTMLSelectElement && !select.multiple && select.size <= 1
            && !select.disabled && !select.hasAttribute("data-native");
    }

    // ---------------------------------------------------------
    // Build the list
    // ---------------------------------------------------------

    function buildPanel(select) {
        const panel = document.createElement("div");
        panel.className = "cs-panel";
        panel.setAttribute("role", "listbox");
        panel.id = "cs-panel";
        const items = [];

        const addOption = (option, parent) => {
            if (option.hidden) return;
            const item = document.createElement("div");
            item.className = "cs-option";
            item.setAttribute("role", "option");
            item.textContent = option.textContent;
            if (option.disabled) item.classList.add("is-disabled");
            if (option.selected) {
                item.classList.add("is-selected");
                item.setAttribute("aria-selected", "true");
            }
            item.option = option;
            parent.append(item);
            items.push(item);
        };

        [...select.children].forEach(child => {
            if (child instanceof HTMLOptGroupElement) {
                const label = document.createElement("div");
                label.className = "cs-group";
                label.textContent = child.label;
                panel.append(label);
                [...child.children].forEach(option => addOption(option, panel));
            } else if (child instanceof HTMLOptionElement) {
                addOption(child, panel);
            }
        });
        return { panel, items };
    }

    function place(select, panel) {
        // The page is zoomed (--ui-zoom on <html>): getBoundingClientRect() is in
        // screen pixels, the list's left/top/width are in zoomed CSS pixels
        const zoom = parseFloat(getComputedStyle(document.documentElement).zoom) || 1;
        const box = select.getBoundingClientRect();
        const gap = 6;

        panel.style.minWidth = `${box.width / zoom}px`;
        const width = panel.offsetWidth * zoom;
        const height = panel.offsetHeight * zoom;

        // Below the select; above it when there isn't room below
        let top = box.bottom + gap;
        if (top + height > window.innerHeight - 8 && box.top - gap - height > 8) top = box.top - gap - height;
        // Keep it on screen sideways
        const left = Math.max(8, Math.min(box.left, window.innerWidth - 8 - width));

        panel.style.left = `${left / zoom}px`;
        panel.style.top = `${top / zoom}px`;
    }


    // ---------------------------------------------------------
    // Open / close / pick
    // ---------------------------------------------------------

    function setActive(index) {
        if (!open) return;
        const enabled = open.items.filter(item => !item.option.disabled);
        if (!enabled.length) return;
        open.items.forEach(item => item.classList.remove("is-active"));
        const item = open.items[index];
        if (!item) return;
        item.classList.add("is-active");
        item.scrollIntoView({ block: "nearest" });
        open.active = index;
    }

    function openList(select) {
        if (open && open.select === select) return closeList();
        closeList();

        const { panel, items } = buildPanel(select);
        // Inside an open <dialog> the list must live in the dialog (top layer)
        (select.closest("dialog[open]") || document.body).append(panel);
        open = { select, panel, items, active: -1 };
        select.classList.add("cs-open");
        select.setAttribute("aria-expanded", "true");
        select.setAttribute("aria-controls", panel.id);
        place(select, panel);

        const selected = items.findIndex(item => item.option.selected);
        setActive(selected >= 0 ? selected : items.findIndex(item => !item.option.disabled));

        // Keep focus on the select, and don't let the page treat a click in the
        // list as an "outside click" (that would close e.g. the Filter by panel)
        ["mousedown", "pointerdown"].forEach(type => panel.addEventListener(type, event => {
            event.preventDefault();
            event.stopPropagation();
        }));
        panel.addEventListener("click", event => {
            event.stopPropagation();
            const item = event.target.closest(".cs-option");
            if (item && !item.option.disabled) pick(item);
        });
        panel.addEventListener("mousemove", event => {
            const item = event.target.closest(".cs-option");
            if (item && !item.option.disabled) setActive(open.items.indexOf(item));
        });
    }

    function closeList() {
        if (!open) return;
        open.panel.remove();
        open.select.classList.remove("cs-open");
        open.select.setAttribute("aria-expanded", "false");
        open = null;
    }

    function pick(item) {
        const select = open.select;
        closeList();
        if (select.value !== item.option.value || !item.option.selected) {
            item.option.selected = true;
            select.dispatchEvent(new Event("input", { bubbles: true }));
            select.dispatchEvent(new Event("change", { bubbles: true }));
        }
        select.focus();
    }

    function move(step) {
        const items = open.items;
        let index = open.active;
        for (let i = 0; i < items.length; i++) {
            index = Math.min(items.length - 1, Math.max(0, index + step));
            if (!items[index].option.disabled) break;
        }
        setActive(index);
    }


    // ---------------------------------------------------------
    // Events (delegated, so selects added later work too)
    // ---------------------------------------------------------

    // Stopping the native list on mousedown makes Chrome send the click that
    // follows to <body> (or the <dialog>), which pages read as an "outside
    // click" and close their dropdown panel / pop-up. Swallow that one click.
    let swallowClick = false;

    document.addEventListener("mousedown", event => {
        const select = event.target.closest && event.target.closest("select");
        if (select && usable(select) && event.button === 0) {
            event.preventDefault();          // no native list
            select.focus();
            openList(select);
            swallowClick = true;
            return;
        }
        if (open && !open.panel.contains(event.target)) closeList();
    });

    window.addEventListener("click", event => {
        if (!swallowClick) return;
        swallowClick = false;
        event.stopPropagation();
        event.preventDefault();
    }, true);
    window.addEventListener("mouseup", () => setTimeout(() => { swallowClick = false; }), true);

    let typed = "", typedTimer = null;

    document.addEventListener("keydown", event => {
        const select = event.target;
        if (!(select instanceof HTMLSelectElement) || !usable(select)) return;

        if (!open || open.select !== select) {
            if (["Enter", " ", "ArrowDown", "ArrowUp"].includes(event.key) || (event.altKey && event.key === "ArrowDown")) {
                event.preventDefault();
                openList(select);
            }
            return;
        }

        switch (event.key) {
            case "ArrowDown": event.preventDefault(); move(1); break;
            case "ArrowUp": event.preventDefault(); move(-1); break;
            case "Home": event.preventDefault(); setActive(open.items.findIndex(i => !i.option.disabled)); break;
            case "End": event.preventDefault(); setActive(open.items.length - 1); break;
            case "Enter":
            case " ":
                event.preventDefault();
                if (open.items[open.active]) pick(open.items[open.active]);
                break;
            case "Escape": event.preventDefault(); event.stopPropagation(); closeList(); break;
            case "Tab": closeList(); break;
            default:
                // Type to jump: "su" -> Suspended
                if (event.key.length === 1 && !event.ctrlKey && !event.metaKey) {
                    event.preventDefault();
                    clearTimeout(typedTimer);
                    typed += event.key.toLowerCase();
                    typedTimer = setTimeout(() => { typed = ""; }, 700);
                    const index = open.items.findIndex(i => !i.option.disabled && i.textContent.trim().toLowerCase().startsWith(typed));
                    if (index >= 0) setActive(index);
                }
        }
    }, true);

    // The list is placed for where the select was: close it when that changes
    window.addEventListener("resize", closeList);
    document.addEventListener("scroll", event => {
        if (open && !open.panel.contains(event.target)) closeList();
    }, true);
    document.addEventListener("focusin", event => {
        if (open && event.target !== open.select && !open.panel.contains(event.target)) closeList();
    });

})();
