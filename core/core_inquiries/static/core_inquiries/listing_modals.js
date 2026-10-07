// =========================================================
// LISTING PAGE POP-UPS (renter)
// - Apply as Renter / Join Waitlist  -> application form
// - Inquire with Landlord            -> message pop-up
// Both send JSON to core_inquiries; the server re-checks everything.
// =========================================================

(function () {

    function csrfToken() {
        const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    async function postJSON(url, data) {
        const response = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json", "Accept": "application/json", "X-CSRFToken": csrfToken() },
            credentials: "same-origin",
            body: JSON.stringify(data),
        });
        const body = await response.json().catch(() => ({}));
        if (response.status === 403 && !body.errors) {
            // Logged out, or logged in as someone else in another tab (same browser = same session)
            body.errors = { __all__: "Your session changed (you may have logged out or switched accounts in another tab). Refresh the page and try again." };
        }
        return { ok: response.ok, status: response.status, body };
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
        setTimeout(() => {
            item.classList.add("is-leaving");
            setTimeout(() => item.remove(), 300);
        }, 3500);
    }

    // Local "YYYY-MM-DD" (toISOString would use UTC and can be off by a day)
    function isoDate(date) {
        const pad = n => String(n).padStart(2, "0");
        return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
    }

    function addDays(iso, days) {
        const [y, m, d] = iso.split("-").map(Number);
        return isoDate(new Date(y, m - 1, d + days));
    }

    // Close a <dialog> by clicking the cream backdrop
    function closeOnBackdrop(dialog) {
        dialog.addEventListener("click", event => {
            if (event.target === dialog) dialog.close();
        });
        dialog.querySelectorAll("[data-modal-close]").forEach(button => {
            button.addEventListener("click", () => dialog.close());
        });
    }


    // =====================================================
    // APPLICATION FORM (apply / waitlist)
    // =====================================================

    function initApplicationModal() {
        const dialog = document.querySelector("[data-application-modal]");
        if (!dialog) return;

        const form = dialog.querySelector("[data-application-form]");
        const list = dialog.querySelector("[data-tenant-list]");
        const template = dialog.querySelector("[data-tenant-template]");
        const addButton = dialog.querySelector("[data-add-tenant]");
        const moveIn = form.elements.move_in_date;
        const visitDate = form.elements.site_visit_date;
        const visitFields = dialog.querySelector("[data-visit-fields]");
        const formError = dialog.querySelector("[data-form-error]");
        const submit = dialog.querySelector("[data-submit]");

        let unit = null;   // dataset of the button that opened the form

        const draftKey = () => `lookapt:application:${unit.unit}:${unit.kind}`;
        const extraRows = () => [...list.querySelectorAll("input[name=occupant]")];
        const maxOccupants = () => Number(unit.maxOccupants) || 1;
        const isWaitlist = () => unit.kind === "waitlist";

        function renumber() {
            list.querySelectorAll(".lm-tenant-number").forEach((badge, i) => { badge.textContent = i + 1; });
            const count = extraRows().length + 1;
            dialog.querySelector("[data-max-label]").textContent = maxOccupants();
            dialog.querySelector("[data-count-label]").textContent = `${count} of ${maxOccupants()} added`;
            addButton.hidden = count >= maxOccupants();
        }

        function addTenant(name = "") {
            if (extraRows().length + 1 >= maxOccupants()) return null;
            const row = template.content.firstElementChild.cloneNode(true);
            row.querySelector("input").value = name;
            list.append(row);
            renumber();
            return row.querySelector("input");
        }

        function clearErrors() {
            formError.hidden = true;
            dialog.querySelectorAll("[data-error-for]").forEach(p => { p.hidden = true; });
            dialog.querySelectorAll(".is-invalid").forEach(el => el.classList.remove("is-invalid"));
        }

        function showErrors(errors) {
            clearErrors();
            for (const [field, message] of Object.entries(errors)) {
                const target = dialog.querySelector(`[data-error-for="${field}"]`) || formError;
                target.textContent = message;
                target.hidden = false;
            }
            const first = dialog.querySelector(".lm-alert:not([hidden]), .lm-field-error:not([hidden])");
            if (first) first.scrollIntoView({ behavior: "smooth", block: "center" });
        }

        function setMode() {
            const waitlist = isWaitlist();
            const unitName = unit.unitName;
            const complexName = unit.complexName;

            dialog.querySelector("[data-mode-title]").textContent = waitlist ? "Waitlist Application Form" : "Renter Application Form";
            dialog.querySelector("[data-mode-intro]").innerHTML = "";
            const intro = dialog.querySelector("[data-mode-intro]");
            const strong = text => Object.assign(document.createElement("strong"), { textContent: text });
            if (waitlist) {
                intro.append(strong(unitName), " of ", strong(complexName),
                    " is currently occupied. Fill out this form to join the waitlist and get notified when this unit becomes available.");
            } else {
                intro.append("Please fill out the details below to apply as a tenant for ", strong(unitName), " at ", strong(complexName), ".");
            }

            dialog.querySelectorAll("[data-apply-only]").forEach(el => { el.hidden = waitlist; });
            dialog.querySelectorAll("[data-waitlist-only]").forEach(el => { el.hidden = !waitlist; });
            dialog.querySelector("[data-mode-icon]").classList.toggle("lm-header-icon--waitlist", waitlist);

            // Move-in: today (apply) or the end of the current lease + turnover (waitlist)
            const today = isoDate(new Date());
            moveIn.min = unit.earliest || today;
            moveIn.max = addDays(moveIn.min, 365);
            visitDate.min = today;

            if (waitlist) {
                dialog.querySelector("[data-earliest-label]").textContent = unit.earliestLabel;
                dialog.querySelector("[data-earliest-note]").textContent = unit.leaseKnown === "1"
                    ? `This is based on the current tenant's contract end date plus ${unit.turnoverDays} day(s) the landlord sets aside for preparation.`
                    : `The current tenant's contract dates aren't set yet, so this is an estimate (today plus ${unit.turnoverDays} day(s) of preparation). The landlord will confirm.`;
            }
        }

        function reset() {
            form.reset();
            extraRows().forEach(input => input.closest("li").remove());
            visitFields.hidden = true;
            clearErrors();
        }

        function restoreDraft() {
            let draft = null;
            try { draft = JSON.parse(localStorage.getItem(draftKey())); } catch (error) { draft = null; }
            if (!draft) return false;

            (draft.occupants || []).forEach(name => addTenant(name));
            if (draft.move_in_date) moveIn.value = draft.move_in_date;
            if (!isWaitlist() && draft.wants_visit) {
                form.querySelector('input[name=wants_visit][value="yes"]').checked = true;
                visitFields.hidden = false;
                visitDate.value = draft.site_visit_date || "";
            }
            return true;
        }

        function collect() {
            const wantsVisit = !isWaitlist() && form.querySelector("input[name=wants_visit]:checked").value === "yes";
            return {
                kind: unit.kind,
                // the server always puts the account holder first; we send a placeholder for row 1
                occupants: ["", ...extraRows().map(input => input.value.trim())],
                move_in_date: moveIn.value,
                site_visit_date: wantsVisit ? visitDate.value : "",
                wants_visit: wantsVisit,
            };
        }

        function validate(data) {
            const errors = {};
            const empty = extraRows().find(input => !input.value.trim());
            if (empty) {
                errors.occupants = "Fill in every name, or remove the empty row.";
                empty.closest(".lm-input").classList.add("is-invalid");
            }
            if (!data.move_in_date) errors.move_in_date = "Pick your preferred move-in date.";
            else if (data.move_in_date < moveIn.min) errors.move_in_date = `The earliest move-in date is ${unit.earliestLabel || moveIn.min}.`;
            if (data.wants_visit) {
                if (!data.site_visit_date) errors.site_visit_date = "Pick a date for the site visit, or choose No.";
                else if (data.site_visit_date < visitDate.min) errors.site_visit_date = "The site visit can't be in the past.";
                else if (data.move_in_date && data.site_visit_date > data.move_in_date) errors.site_visit_date = "Schedule the site visit on or before your move-in date.";
            }
            return errors;
        }

        // ---------- open ----------
        document.addEventListener("click", event => {
            const button = event.target.closest("[data-open-application]");
            if (!button) return;

            unit = { ...button.dataset };
            unit.button = button;
            reset();
            setMode();
            restoreDraft();
            renumber();
            dialog.showModal();
            dialog.querySelector(".lm-body").scrollTop = 0;
        });

        // ---------- tenants ----------
        addButton.addEventListener("click", () => addTenant()?.focus());
        list.addEventListener("click", event => {
            const remove = event.target.closest("[data-remove-tenant]");
            if (!remove) return;
            remove.closest("li").remove();
            renumber();
        });
        list.addEventListener("input", event => event.target.closest(".lm-input")?.classList.remove("is-invalid"));

        // ---------- site visit yes/no ----------
        form.addEventListener("change", event => {
            // Editing a field clears its old error
            const fieldError = dialog.querySelector(`[data-error-for="${event.target.name}"]`);
            if (fieldError) fieldError.hidden = true;

            if (event.target.name === "wants_visit") {
                visitFields.hidden = event.target.value !== "yes";
                if (!visitFields.hidden) visitDate.focus();
            }
            if (event.target === moveIn && moveIn.value) visitDate.max = moveIn.value;
        });

        // ---------- save draft (this browser only) ----------
        dialog.querySelector("[data-save-draft]").addEventListener("click", () => {
            const data = collect();
            try {
                localStorage.setItem(draftKey(), JSON.stringify({ ...data, occupants: data.occupants.slice(1) }));
                toast("Draft saved. You can finish it later.");
                dialog.close();
            } catch (error) {
                toast("Couldn't save the draft in this browser.", "error");
            }
        });

        // ---------- submit ----------
        form.addEventListener("submit", async event => {
            event.preventDefault();
            const data = collect();
            const errors = validate(data);
            if (Object.keys(errors).length) return showErrors(errors);

            submit.disabled = true;
            submit.textContent = "Submitting…";
            try {
                const result = await postJSON(unit.url, data);
                if (!result.ok) {
                    showErrors(result.body.errors || { __all__: "Something went wrong. Please try again." });
                    return;
                }
                try { localStorage.removeItem(draftKey()); } catch (error) { /* ignore */ }
                dialog.close();
                toast(result.body.message);
                markApplied(unit.unit, isWaitlist());
            } catch (error) {
                showErrors({ __all__: "Couldn't reach the server. Check your connection and try again." });
            } finally {
                submit.disabled = false;
                submit.textContent = "Submit Application";
            }
        });

        // Every Apply/Waitlist button for this unit becomes "Application Sent"
        function markApplied(unitId, waitlist) {
            document.querySelectorAll(`[data-open-application][data-unit="${unitId}"]`).forEach(button => {
                button.removeAttribute("data-open-application");
                button.disabled = true;
                button.className = "ld-btn ld-btn--done";
                button.textContent = waitlist ? "On the Waitlist" : "Application Sent";
            });
        }

        closeOnBackdrop(dialog);
    }


    // =====================================================
    // MESSAGE POP-UP
    // =====================================================

    function initMessageModal() {
        const dialog = document.querySelector("[data-message-modal]");
        if (!dialog || !window.LookAptChat) return;

        const Chat = window.LookAptChat;
        const body = dialog.querySelector("[data-chat-messages]");
        const form = dialog.querySelector("[data-chat-form]");
        const textarea = form.elements.body;
        const error = dialog.querySelector("[data-chat-error]");
        const emptyTemplate = dialog.querySelector("[data-chat-empty]");
        const sendButton = form.querySelector(".lm-send");

        // One thread per landlord: every Inquire button on the page opens the same one.
        // `target` only tells the server which unit/complex the message is about.
        let target = null;
        const thread = new Chat.Thread(body, { emptyNode: () => emptyTemplate.content.cloneNode(true) });

        function showError(message) {
            error.textContent = message;
            error.hidden = !message;
        }
        const picker = Chat.attachPicker(form, showError);

        function autosize() {
            textarea.style.height = "auto";
            textarea.style.height = Math.min(textarea.scrollHeight, 120) + "px";
        }

        document.addEventListener("click", async event => {
            const button = event.target.closest("[data-open-inquiry]");
            if (!button) return;

            target = button.dataset.unit ? { unit: button.dataset.unit } : { complex: button.dataset.complex };
            dialog.querySelector("[data-chat-subject]").textContent = button.dataset.subject;
            showError("");
            picker.clear();
            textarea.value = "";
            autosize();
            body.replaceChildren(Object.assign(document.createElement("p"), { className: "lm-chat-loading", textContent: "Loading…" }));
            dialog.showModal();
            textarea.focus();

            try {
                const response = await fetch(`${dialog.dataset.threadUrl}?${new URLSearchParams(target)}`, {
                    headers: { "Accept": "application/json" },
                    credentials: "same-origin",
                });
                const data = await response.json();
                if (data.conversation) {
                    await thread.open(data.conversation.detail_url);   // also starts the live refresh
                } else {
                    thread.stop();
                    thread.showEmpty();
                }
            } catch (err) {
                thread.showEmpty();
            }
        });

        dialog.addEventListener("close", () => thread.stop());
        textarea.addEventListener("input", autosize);

        // Enter sends, Shift+Enter makes a new line
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
                const result = await Chat.send(dialog.dataset.sendUrl, { ...target, body: text }, file);
                if (!result.ok) return showError(Chat.firstError(result.data, "Couldn't send. Please try again."));

                thread.add([result.data.message]);
                if (!thread.timer) thread.follow(result.data.detail_url);   // first message created the thread
                textarea.value = "";
                picker.clear();
                autosize();
            } catch (err) {
                showError("Couldn't reach the server. Check your connection and try again.");
            } finally {
                sendButton.disabled = false;
                textarea.focus();
            }
        });

        closeOnBackdrop(dialog);
    }


    document.addEventListener("DOMContentLoaded", () => {
        initApplicationModal();
        initMessageModal();
    });

})();