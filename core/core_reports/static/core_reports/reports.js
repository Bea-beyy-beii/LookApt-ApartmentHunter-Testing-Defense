// =========================================================
// REPORTS FILED (renter + landlord dashboards)
// - Report Guidelines: ✕ / "Hide Report Guidelines" (remembered in this browser)
// - status tabs, search, newest/oldest, click a report to see its details
// - "File a Report" pop-up: pick who, reason ("Others" -> text field),
//   details, evidence (drag & drop). The server re-checks everything.
// =========================================================

(function () {

    const GUIDE_KEY = "lookapt:reports:hide-guidelines";
    const TOAST_KEY = "lookapt:reports:toast";

    function csrfToken() {
        const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
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

    const sizeLabel = bytes => (bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`);


    // =====================================================
    // GUIDELINES
    // =====================================================

    function initGuidelines(page) {
        const box = page.querySelector("[data-guidelines]");
        const link = page.querySelector("[data-guide-toggle]");

        function set(hidden) {
            box.hidden = hidden;
            link.textContent = hidden ? "See Report Guidelines" : "Hide Report Guidelines";
            link.setAttribute("aria-expanded", String(!hidden));
            try { localStorage.setItem(GUIDE_KEY, hidden ? "1" : "0"); } catch (error) { /* ignore */ }
        }

        let hidden = false;
        try { hidden = localStorage.getItem(GUIDE_KEY) === "1"; } catch (error) { /* ignore */ }
        set(hidden);
        link.addEventListener("click", () => set(!box.hidden));
        page.querySelector("[data-guide-close]").addEventListener("click", () => set(true));
    }


    // =====================================================
    // LIST: status tabs, search, sort, expand
    // =====================================================

    function initList(page) {
        const list = page.querySelector("[data-report-list]");
        const tabs = [...page.querySelectorAll("[data-report-tab]")];
        const search = page.querySelector("[data-report-search]");
        const sort = page.querySelector("[data-report-sort]");
        const none = page.querySelector("[data-report-none]");
        let status = "all";

        function apply() {
            if (!list) return;
            const query = search.value.trim().toLowerCase();
            const items = [...list.querySelectorAll("[data-report]")];
            items.sort((a, b) => (sort.value === "oldest" ? 1 : -1) * (Number(a.dataset.date) - Number(b.dataset.date)));
            list.append(...items);
            let shown = 0;
            items.forEach(item => {
                const show = (status === "all" || item.dataset.status === status) &&
                    (!query || item.dataset.search.toLowerCase().includes(query));
                item.hidden = !show;
                if (show) shown++;
            });
            none.hidden = shown > 0;
        }

        tabs.forEach(tab => tab.addEventListener("click", () => {
            status = tab.dataset.reportTab;
            tabs.forEach(t => t.classList.toggle("active", t === tab));
            apply();
        }));
        search.addEventListener("input", apply);
        sort.addEventListener("change", apply);

        list?.addEventListener("click", event => {
            const head = event.target.closest("[data-report-toggle]");
            if (!head) return;
            const body = head.nextElementSibling;
            body.hidden = !body.hidden;
            head.setAttribute("aria-expanded", String(!body.hidden));
            head.closest("[data-report]").classList.toggle("is-open", !body.hidden);
        });
    }


    // =====================================================
    // FILE A REPORT
    // =====================================================

    function initModal() {
        const dialog = document.querySelector("[data-report-modal]");
        if (!dialog) return;
        const form = dialog.querySelector("[data-report-form]");
        const formError = dialog.querySelector("[data-form-error]");
        const submit = dialog.querySelector("[data-submit]");
        const people = [...dialog.querySelectorAll("[data-person]")];
        const personSearch = dialog.querySelector("[data-person-search]");
        const personNone = dialog.querySelector("[data-person-none]");
        const other = dialog.querySelector("[data-other]");
        const counter = dialog.querySelector("[data-desc-count]");
        const drop = dialog.querySelector("[data-drop]");
        const input = dialog.querySelector("[data-evidence-input]");
        const fileList = dialog.querySelector("[data-file-list]");
        const maxFiles = Number(form.dataset.maxFiles) || 5;
        const maxBytes = (Number(form.dataset.maxMb) || 10) * 1048576;
        let files = [];

        function clearErrors() {
            formError.hidden = true;
            dialog.querySelectorAll("[data-error-for]").forEach(p => { p.hidden = true; });
        }

        function showErrors(errors) {
            clearErrors();
            for (const [field, message] of Object.entries(errors)) {
                const target = dialog.querySelector(`[data-error-for="${field}"]`) || formError;
                target.textContent = message;
                target.hidden = false;
            }
            dialog.querySelector(".lm-alert:not([hidden]), .lm-field-error:not([hidden])")
                ?.scrollIntoView({ behavior: "smooth", block: "center" });
        }

        function renderFiles() {
            fileList.replaceChildren(...files.map((file, i) => {
                const li = document.createElement("li");
                li.className = "rp-file-row";
                const name = document.createElement("span");
                name.textContent = file.name;
                const size = document.createElement("small");
                size.textContent = sizeLabel(file.size);
                const remove = document.createElement("button");
                remove.type = "button";
                remove.className = "rp-file-remove";
                remove.setAttribute("aria-label", `Remove ${file.name}`);
                remove.textContent = "×";
                remove.addEventListener("click", () => { files.splice(i, 1); renderFiles(); });
                li.append(name, size, remove);
                return li;
            }));
        }

        function addFiles(list) {
            const errors = [];
            for (const file of list) {
                if (files.length >= maxFiles) { errors.push(`You can attach up to ${maxFiles} files.`); break; }
                if (file.size > maxBytes) { errors.push(`${file.name} is larger than ${form.dataset.maxMb} MB.`); continue; }
                files.push(file);
            }
            renderFiles();
            if (errors.length) showErrors({ evidence: errors.join(" ") });
        }

        function reset() {
            form.reset();
            files = [];
            renderFiles();
            clearErrors();
            other.hidden = true;
            counter.textContent = "0/500";
            people.forEach(p => { p.hidden = false; });
            personNone.hidden = true;
        }

        document.addEventListener("click", event => {
            if (!event.target.closest("[data-open-report]")) return;
            reset();
            dialog.showModal();
            dialog.querySelector(".lm-body").scrollTop = 0;
        });
        dialog.addEventListener("click", event => { if (event.target === dialog) dialog.close(); });
        dialog.querySelectorAll("[data-modal-close]").forEach(b => b.addEventListener("click", () => dialog.close()));

        personSearch.addEventListener("input", () => {
            const query = personSearch.value.trim().toLowerCase();
            let shown = 0;
            people.forEach(p => {
                const show = !query || p.dataset.search.includes(query) || p.querySelector(":checked");
                p.hidden = !show;
                if (show) shown++;
            });
            personNone.hidden = shown > 0 || !people.length;
        });

        form.addEventListener("change", event => {
            const fieldError = dialog.querySelector(`[data-error-for="${event.target.name}"]`);
            if (fieldError) fieldError.hidden = true;
            if (event.target.name === "category") {
                other.hidden = event.target.value !== "others";
                if (!other.hidden) form.elements.other_category_text.focus();
            }
        });
        form.elements.description.addEventListener("input", () => {
            counter.textContent = `${form.elements.description.value.length}/500`;
        });

        // Evidence: click or drag & drop
        input.addEventListener("change", () => { addFiles(input.files); input.value = ""; });
        ["dragenter", "dragover"].forEach(type => drop.addEventListener(type, event => {
            event.preventDefault();
            drop.classList.add("is-dragging");
        }));
        ["dragleave", "drop"].forEach(type => drop.addEventListener(type, event => {
            event.preventDefault();
            drop.classList.remove("is-dragging");
        }));
        drop.addEventListener("drop", event => addFiles(event.dataTransfer.files));

        form.addEventListener("submit", async event => {
            event.preventDefault();
            const who = form.querySelector("input[name=reported_user]:checked");
            const errors = {};
            if (!who) errors.reported_user = "Pick who you want to report.";
            if (!form.elements.category.value) errors.category = "Pick a reason for reporting.";
            if (form.elements.category.value === "others" && !form.elements.other_category_text.value.trim()) {
                errors.other_category_text = "Tell us the reason in a few words.";
            }
            if (!form.elements.description.value.trim()) errors.description = "Describe what happened.";
            if (Object.keys(errors).length) return showErrors(errors);

            const data = new FormData();
            data.append("reported_user", who.value);
            data.append("category", form.elements.category.value);
            data.append("other_category_text", form.elements.other_category_text.value.trim());
            data.append("description", form.elements.description.value.trim());
            files.forEach(file => data.append("evidence", file));

            submit.disabled = true;
            submit.textContent = "Submitting…";
            try {
                const response = await fetch(form.dataset.url, {
                    method: "POST", body: data, credentials: "same-origin",
                    headers: { "X-CSRFToken": csrfToken(), "Accept": "application/json" },
                });
                const body = await response.json().catch(() => ({}));
                if (!response.ok) {
                    return showErrors(body.errors || { __all__: "Something went wrong. Please try again." });
                }
                try { sessionStorage.setItem(TOAST_KEY, body.message); } catch (error) { /* ignore */ }
                location.reload();
            } catch (error) {
                showErrors({ __all__: "Couldn't reach the server. Check your connection and try again." });
            } finally {
                submit.disabled = false;
                submit.textContent = "Submit Report";
            }
        });
    }


    document.addEventListener("DOMContentLoaded", () => {
        const page = document.querySelector("[data-reports]");
        if (!page) return;
        initGuidelines(page);
        initList(page);
        initModal();
        try {
            const message = sessionStorage.getItem(TOAST_KEY);
            if (message) {
                sessionStorage.removeItem(TOAST_KEY);
                toast(message);
            }
        } catch (error) { /* ignore */ }
    });

})();