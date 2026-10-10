// =========================================================
// PENDING REQUESTS / WAITLIST / ARCHIVE (Inquiries tab, both dashboards)
// Pop-ups: Reject / Cancel (reason), simple confirmations (approve for
// waitlist, notify applicant, site visit), Approve as Tenant, and Message.
// "Approve as Tenant" posts to Manage Rentals' assign endpoint, so both pages
// share one backend. The server re-checks everything; after a change the
// page reloads on the same Inquiries sub-tab and shows a toast.
// =========================================================

(function () {

    const TOAST_KEY = "lookapt:inquiries:toast";
    const TAB_KEY = "lookapt:inquiries:tab";

    function csrfToken() {
        const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    async function postJSON(url, data) {
        const response = await fetch(url, {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json", "Accept": "application/json", "X-CSRFToken": csrfToken() },
            body: JSON.stringify(data),
        });
        const body = await response.json().catch(() => ({}));
        if (response.status === 403 && !body.errors) {
            body.errors = { __all__: "Your session changed (you may have logged out or switched accounts in another tab). Refresh the page and try again." };
        }
        if (response.status === 404 && !body.errors) {
            body.errors = { __all__: "This request no longer exists. Refresh the page." };
        }
        return { ok: response.ok, body };
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

    // After a change: reload, come back to the same sub-tab, then show the message
    function reloadWith(message) {
        const tab = document.querySelector(".inquiry-tab.active")?.dataset.tab || "requests";
        try {
            sessionStorage.setItem(TOAST_KEY, message);
            sessionStorage.setItem(TAB_KEY, tab);
        } catch (error) { /* ignore */ }
        location.reload();
    }

    function localISO(date) {
        const pad = n => String(n).padStart(2, "0");
        return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
    }

    function setupDialog(dialog) {
        const formError = dialog.querySelector("[data-form-error]");
        dialog.addEventListener("click", event => { if (event.target === dialog) dialog.close(); });
        dialog.querySelectorAll("[data-modal-close]").forEach(b => b.addEventListener("click", () => dialog.close()));
        return {
            clear() {
                if (formError) formError.hidden = true;
                dialog.querySelectorAll("[data-error-for]").forEach(p => { p.hidden = true; });
            },
            show(errors) {
                this.clear();
                for (const [field, message] of Object.entries(errors)) {
                    const target = dialog.querySelector(`[data-error-for="${field}"]`) || formError;
                    target.textContent = message;
                    target.hidden = false;
                }
            },
        };
    }

    async function submitWith(button, label, work) {
        button.disabled = true;
        const original = button.textContent;
        button.textContent = label;
        try {
            await work();
        } finally {
            button.disabled = false;
            button.textContent = original;
        }
    }

    // Send, then reload with the server's message (or show its errors)
    function sendAction(ui, button, url, data) {
        return submitWith(button, "Saving…", async () => {
            try {
                const result = await postJSON(url, data);
                if (!result.ok) return ui.show(result.body.errors || { __all__: "Something went wrong. Please try again." });
                reloadWith(result.body.message);
            } catch (error) {
                ui.show({ __all__: "Couldn't reach the server. Check your connection and try again." });
            }
        });
    }


    // =====================================================
    // REJECT / CANCEL (with a reason)
    // =====================================================

    function initReason() {
        const dialog = document.querySelector("[data-reason-modal]");
        if (!dialog) return;
        const ui = setupDialog(dialog);
        const form = dialog.querySelector("[data-reason-form]");
        const submit = dialog.querySelector("[data-submit]");
        const hint = dialog.querySelector("[data-note-hint]");
        // Landlords must give a reason; renters may skip it
        const landlord = document.querySelector("[data-inquiry-layout]").dataset.role === "landlord";
        let target = null;

        function syncHint() {
            const other = form.elements.reason.value === "other";
            hint.textContent = other ? "(required for “Other”)" : "(optional)";
        }

        document.addEventListener("click", event => {
            const button = event.target.closest("[data-open-reason]");
            if (!button) return;
            target = button.dataset;
            form.reset();
            ui.clear();
            syncHint();
            dialog.querySelector("[data-reason-title]").textContent = target.title;
            dialog.querySelector("[data-reason-text]").textContent = target.text;
            submit.textContent = target.confirmLabel || "Confirm";
            dialog.showModal();
        });

        form.addEventListener("change", event => { if (event.target.name === "reason") syncHint(); });

        form.addEventListener("submit", event => {
            event.preventDefault();
            const data = {
                reason: form.elements.reason.value || "",
                reason_note: form.elements.reason_note.value.trim(),
            };
            if (landlord && !data.reason) return ui.show({ reason: "Pick a reason." });
            if (data.reason === "other" && !data.reason_note) return ui.show({ reason_note: "Tell them the reason in a few words." });
            sendAction(ui, submit, target.url, data);
        });
    }


    // =====================================================
    // SIMPLE CONFIRMATIONS
    // =====================================================

    function initConfirm() {
        const dialog = document.querySelector("[data-confirm-modal]");
        if (!dialog) return;
        const ui = setupDialog(dialog);
        const form = dialog.querySelector("[data-confirm-form]");
        const submit = dialog.querySelector("[data-submit]");
        let target = null;

        document.addEventListener("click", event => {
            const button = event.target.closest("[data-open-confirm]");
            if (!button) return;
            target = button.dataset;
            const danger = "danger" in target;
            ui.clear();
            dialog.querySelector("[data-confirm-title]").textContent = target.title;
            dialog.querySelector("[data-confirm-text]").textContent = target.text;
            dialog.querySelector("[data-confirm-note]").textContent = target.note || "";
            dialog.querySelector("[data-confirm-icon]").classList.toggle("rt-icon-danger", danger);
            submit.classList.toggle("rt-btn--danger", danger);
            submit.classList.toggle("rt-btn--primary", !danger);
            submit.textContent = target.confirmLabel || "Confirm";
            dialog.showModal();
        });

        form.addEventListener("submit", event => {
            event.preventDefault();
            let payload = {};
            try { payload = JSON.parse(target.payload || "{}"); } catch (error) { payload = {}; }
            sendAction(ui, submit, target.url, payload);
        });
    }


    // =====================================================
    // APPROVE AS TENANT (= Manage Rentals → Assign a Renter)
    // =====================================================

    function initApprove() {
        const dialog = document.querySelector("[data-approve-modal]");
        if (!dialog) return;
        const ui = setupDialog(dialog);
        const form = dialog.querySelector("[data-approve-form]");
        const submit = dialog.querySelector("[data-submit]");
        let target = null;

        document.addEventListener("click", event => {
            const button = event.target.closest("[data-open-approve]");
            if (!button) return;
            target = button.dataset;
            form.reset();
            ui.clear();
            dialog.querySelector("[data-approve-renter]").textContent = target.renterName;
            dialog.querySelector("[data-approve-unit]").textContent = target.unitName;
            dialog.querySelector("[data-approve-complex]").textContent = target.complexName;
            dialog.querySelector("[data-approve-rent]").textContent = target.rent;
            dialog.querySelector("[data-approve-lease]").textContent = `${target.lease} lease`;
            const people = Number(target.occupants) || 1;
            dialog.querySelector("[data-approve-summary]").textContent =
                `${target.renterName} · ${people} tenant${people === 1 ? "" : "s"} · wants to move in ${target.moveInLabel}`;
            // Their preferred move-in date, editable
            form.elements.start_date.value = target.moveIn || localISO(new Date());
            dialog.showModal();
        });

        form.addEventListener("submit", event => {
            event.preventDefault();
            const start = form.elements.start_date.value;
            if (!start) return ui.show({ start_date: "Pick the date the rental starts." });
            sendAction(ui, submit, target.url, { application: target.application, start_date: start });
        });
    }


    // =====================================================
    // MESSAGE (uses chat.js; first message creates the thread)
    // =====================================================

    function initChat() {
        const dialog = document.querySelector("[data-request-chat]");
        const Chat = window.LookAptChat;
        if (!dialog || !Chat) return;

        const box = dialog.querySelector("[data-chat-messages]");
        const form = dialog.querySelector("[data-chat-form]");
        const textarea = form.elements.body;
        const error = dialog.querySelector("[data-chat-error]");
        const sendButton = form.querySelector(".lm-send");
        const emptyTemplate = dialog.querySelector("[data-chat-empty]");
        const thread = new Chat.Thread(box, { emptyNode: () => emptyTemplate.content.cloneNode(true) });
        let target = null;
        let params = {};
        let sent = false;

        function showError(message) {
            error.textContent = message;
            error.hidden = !message;
        }
        const picker = Chat.attachPicker(form, showError);

        document.addEventListener("click", async event => {
            const button = event.target.closest("[data-open-request-chat]");
            if (!button) return;
            target = button.dataset;
            try { params = JSON.parse(target.sendParams || "{}"); } catch (err) { params = {}; }
            sent = false;
            dialog.querySelector("[data-chat-name]").textContent = target.name;
            dialog.querySelector("[data-chat-initials]").textContent = target.initials;
            dialog.querySelector("[data-chat-subject]").textContent = target.subject;
            showError("");
            picker.clear();
            textarea.value = "";
            dialog.showModal();
            textarea.focus();

            if (target.detailUrl) {
                box.replaceChildren(Object.assign(document.createElement("p"), { className: "lm-chat-loading", textContent: "Loading…" }));
                try {
                    const conversation = await thread.open(target.detailUrl);
                    if (!conversation) thread.showEmpty();
                } catch (err) {
                    thread.showEmpty();
                }
            } else {
                thread.stop();
                thread.showEmpty();
            }
        });

        dialog.addEventListener("close", () => {
            thread.stop();
            // The card's "latest message" is out of date after sending
            if (sent) reloadWith("Message sent.");
        });
        dialog.addEventListener("click", event => { if (event.target === dialog) dialog.close(); });
        dialog.querySelectorAll("[data-modal-close]").forEach(b => b.addEventListener("click", () => dialog.close()));

        textarea.addEventListener("keydown", event => {
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                form.requestSubmit();
            }
        });

        form.addEventListener("submit", async event => {
            event.preventDefault();
            const text = textarea.value.trim();
            const file = picker.file();
            if (!text && !file) return;
            sendButton.disabled = true;
            showError("");
            try {
                const result = await Chat.send(target.sendUrl, { ...params, body: text }, file);
                if (!result.ok) return showError(Chat.firstError(result.data, "Couldn't send. Please try again."));
                thread.add([result.data.message]);
                if (!thread.timer) thread.follow(result.data.detail_url);
                sent = true;
                textarea.value = "";
                picker.clear();
            } catch (err) {
                showError("Couldn't reach the server. Please try again.");
            } finally {
                sendButton.disabled = false;
                textarea.focus();
            }
        });
    }


    // =====================================================
    // WAITLIST: collapse a unit
    // =====================================================

    function initCollapse() {
        document.addEventListener("click", event => {
            const button = event.target.closest("[data-wl-toggle]");
            if (!button) return;
            const collapsed = button.closest("[data-wl-group]").classList.toggle("is-collapsed");
            button.setAttribute("aria-expanded", String(!collapsed));
        });
    }


    // Used by listing_modals.js ("Edit Application")
    window.LookAptRequests = { reloadWith, TAB_KEY, TOAST_KEY };

    document.addEventListener("DOMContentLoaded", () => {
        if (!document.querySelector("[data-inquiry-layout]")) return;
        initReason();
        initConfirm();
        initApprove();
        initChat();
        initCollapse();

        try {
            const message = sessionStorage.getItem(TOAST_KEY);
            if (message) {
                sessionStorage.removeItem(TOAST_KEY);
                toast(message);
            }
        } catch (error) { /* ignore */ }
    });

})();