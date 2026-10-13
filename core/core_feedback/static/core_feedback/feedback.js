// =========================================================
// LOOKAPT GUIDE + FEEDBACK FORM pop-ups (profile menu)
// core_feedback/guide_dialog.html, feedback_dialog.html
// =========================================================

(function () {

    class HelpDialogs {
        /** Opens the right pop-up for every [data-help-open="guide" | "feedback"] button. */

        constructor() {
            this.dialogs = Object.fromEntries(
                [...document.querySelectorAll("[data-help-dialog]")].map(d => [d.dataset.helpDialog, d]));
            document.addEventListener("click", event => {
                const opener = event.target.closest("[data-help-open]");
                if (opener) this.open(opener.dataset.helpOpen);
            });
            Object.values(this.dialogs).forEach(dialog => {
                dialog.querySelectorAll("[data-help-close]").forEach(b => b.addEventListener("click", () => dialog.close()));
                dialog.addEventListener("click", event => { if (event.target === dialog) dialog.close(); });   // click outside
            });
        }

        open(name) {
            const dialog = this.dialogs[name];
            if (!dialog) return;
            // Close the profile menu (and the other pop-up) first
            document.querySelectorAll(".topbar-menu").forEach(menu => { menu.hidden = true; });
            document.querySelectorAll("[data-topbar-toggle]").forEach(t => t.setAttribute("aria-expanded", "false"));
            Object.values(this.dialogs).forEach(d => { if (d.open) d.close(); });
            dialog.showModal();
            dialog.querySelector(".ac-panel").scrollTop = 0;
        }
    }


    class FeedbackForm {
        /** Sends the answers; shows each problem under its question (field_errors.css look). */

        constructor(form) {
            this.form = form;
            this.sent = form.parentElement.querySelector("[data-feedback-sent]");
            this.button = form.querySelector("[data-feedback-send]");
            form.addEventListener("submit", event => {
                event.preventDefault();
                if (form.checkValidity()) this.send();      // checkValidity() shows the empty ones (field_errors.js)
            });
        }

        async send() {
            this.button.disabled = true;
            this.button.textContent = "Sending…";
            this.showErrors({});
            try {
                const response = await fetch(this.form.dataset.url, {
                    method: "POST",
                    body: new FormData(this.form),
                    credentials: "same-origin",
                    headers: { "X-CSRFToken": this.form.dataset.csrf, Accept: "application/json" },
                });
                const data = await response.json().catch(() => ({}));
                if (response.ok) return this.done();
                this.showErrors(data.errors || { __all__: "Something went wrong. Please try again." });
            } catch (error) {
                this.showErrors({ __all__: "Couldn't reach LookApt. Check your connection and try again." });
            }
            this.button.disabled = false;
            this.button.textContent = "Send Feedback";
        }

        showErrors(errors) {
            this.form.querySelectorAll("[data-error-for]").forEach(line => {
                const text = errors[line.dataset.errorFor] || "";
                line.textContent = text;
                line.closest(".ac-field")?.classList.toggle("has-error", Boolean(text));
            });
        }

        done() {
            this.form.reset();
            this.form.hidden = true;
            this.sent.hidden = false;
            this.form.closest(".ac-panel").scrollTop = 0;
            // Ready for another round the next time it's opened
            this.form.closest("dialog").addEventListener("close", () => {
                this.form.hidden = false;
                this.sent.hidden = true;
                this.button.disabled = false;
                this.button.textContent = "Send Feedback";
            }, { once: true });
        }
    }


    document.addEventListener("DOMContentLoaded", () => {
        new HelpDialogs();
        document.querySelectorAll("[data-feedback-form]").forEach(form => new FeedbackForm(form));
    });

})();
