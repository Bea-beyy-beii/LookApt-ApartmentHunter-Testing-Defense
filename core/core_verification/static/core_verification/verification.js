// Landlord verification (core_verification): the upload pop-up, the status
// banner (re-checks while the documents are being read) and the welcome pop-up.
(function () {
    const LATER_KEY = "lookapt.verifyLater";     // "Later" hides the pop-up until the next visit

    function csrfToken() {
        const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        if (match) return decodeURIComponent(match[1]);
        const input = document.querySelector("input[name=csrfmiddlewaretoken]");
        return input ? input.value : "";
    }

    function remember(key) {
        try { sessionStorage.setItem(key, "1"); } catch (e) { /* private mode */ }
    }

    function remembered(key) {
        try { return sessionStorage.getItem(key) === "1"; } catch (e) { return false; }
    }

    // ---------------------------------------------------------------- upload pop-up
    const dialog = document.querySelector("[data-verify-modal]");
    if (dialog) {
        const form = dialog.querySelector("[data-verify-form]");
        const formError = dialog.querySelector("[data-form-error]");
        const submit = dialog.querySelector("[data-submit]");
        const maxBytes = Number(form.dataset.maxMb) * 1024 * 1024;

        function clearErrors() {
            formError.hidden = true;
            dialog.querySelectorAll("[data-error-for]").forEach(el => { el.hidden = true; });
        }

        function showErrors(errors) {
            Object.entries(errors).forEach(([field, message]) => {
                const el = dialog.querySelector(`[data-error-for="${field}"]`) || formError;
                el.textContent = message;
                el.hidden = false;
            });
        }

        function open() {
            clearErrors();
            dialog.showModal();
            dialog.querySelector(".lm-body").scrollTop = 0;
        }

        function close() {
            remember(LATER_KEY);
            dialog.close();
        }

        dialog.querySelectorAll("[data-modal-close]").forEach(b => b.addEventListener("click", close));
        dialog.addEventListener("click", event => { if (event.target === dialog) close(); });
        dialog.addEventListener("cancel", () => remember(LATER_KEY));     // Esc
        document.addEventListener("click", event => {
            if (event.target.closest("[data-verify-open]")) open();
        });
        if (dialog.hasAttribute("data-auto-open") && !remembered(LATER_KEY)) open();

        // Show the chosen file's name in its box
        form.querySelectorAll("input[type=file]").forEach(input => {
            const label = input.closest(".vf-drop");
            const name = label.querySelector("[data-file-name]");
            const placeholder = name.textContent;
            input.addEventListener("change", () => {
                const file = input.files[0];
                const error = dialog.querySelector(`[data-error-for="${input.name}"]`);
                error.hidden = true;
                if (file && file.size > maxBytes) {
                    input.value = "";
                    error.textContent = `${file.name} is larger than ${form.dataset.maxMb} MB.`;
                    error.hidden = false;
                }
                name.textContent = input.files[0] ? input.files[0].name : placeholder;
                label.classList.toggle("has-file", Boolean(input.files[0]));
            });
        });
        form.addEventListener("change", event => {
            if (event.target.tagName !== "SELECT") return;
            const error = dialog.querySelector(`[data-error-for="${event.target.name}"]`);
            if (error) error.hidden = true;
        });

        form.addEventListener("submit", async event => {
            event.preventDefault();
            clearErrors();
            const errors = {};
            if (!form.elements.id_type.value) errors.id_type = "Choose the type of ID.";
            if (!form.elements.id_photo.files.length) errors.id_photo = "Upload a photo of your ID.";
            if (!form.elements.selfie.files.length) errors.selfie = "Upload a selfie holding your ID.";
            if (!form.elements.ownership_type.value) errors.ownership_type = "Choose the type of document.";
            if (!form.elements.ownership_document.files.length) {
                errors.ownership_document = "Upload your business permit or proof of ownership.";
            }
            if (Object.keys(errors).length) { showErrors(errors); return; }

            submit.disabled = true;
            submit.textContent = "Uploading…";
            try {
                const response = await fetch(form.dataset.url, {
                    method: "POST",
                    body: new FormData(form),
                    headers: { "X-CSRFToken": csrfToken(), "X-Requested-With": "XMLHttpRequest" },
                });
                const data = await response.json().catch(() => ({}));
                if (response.ok && data.ok) {
                    window.location.reload();       // the banner now says "checking"
                    return;
                }
                const fieldErrors = data.errors || { __all__: "Something went wrong. Please try again." };
                if (fieldErrors.__all__) { formError.textContent = fieldErrors.__all__; formError.hidden = false; delete fieldErrors.__all__; }
                showErrors(fieldErrors);
            } catch (e) {
                formError.textContent = "We couldn't upload your documents. Check your connection and try again.";
                formError.hidden = false;
            }
            submit.disabled = false;
            submit.textContent = "Submit for verification";
        });
    }

    // ---------------------------------------------------------------- banner
    const banner = document.querySelector("[data-verify-banner]");
    if (banner && banner.dataset.state === "checking") {
        const timer = setInterval(async () => {
            try {
                const response = await fetch(banner.dataset.statusUrl, { headers: { "X-Requested-With": "XMLHttpRequest" } });
                const data = await response.json();
                if (data.state !== "checking") {
                    clearInterval(timer);
                    window.location.reload();
                }
            } catch (e) { /* try again next tick */ }
        }, 4000);
    }

    // ---------------------------------------------------------------- welcome
    const welcome = document.querySelector("[data-verify-welcome]");
    if (welcome) {
        let sent = false;
        const markSeen = () => {
            if (sent) return;
            sent = true;
            fetch(welcome.dataset.url, {
                method: "POST", keepalive: true,
                headers: { "X-CSRFToken": csrfToken(), "X-Requested-With": "XMLHttpRequest" },
            });
        };
        welcome.addEventListener("close", markSeen);
        welcome.querySelectorAll("[data-modal-close]").forEach(el => el.addEventListener("click", () => {
            markSeen();
            if (el.tagName === "BUTTON") welcome.close();
        }));
        welcome.showModal();
    }
})();
