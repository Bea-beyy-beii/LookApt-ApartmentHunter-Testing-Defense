// Landlord verification (core_verification): the upload pop-up (with previews
// you can open full size, like the complex / unit photos), the status banner
// (re-checks while the documents are being read), the documents already sent,
// the welcome pop-up, and the buttons unverified landlords can't use yet.
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

    // ---------------------------------------------------------------- full-size viewer
    const lightbox = document.querySelector("[data-verify-lightbox]");

    function openLightbox(src, alt) {
        if (!lightbox) return;
        const image = lightbox.querySelector("img");
        image.src = src;
        image.alt = alt || "";
        lightbox.showModal();
    }

    if (lightbox) {
        lightbox.querySelector(".photo-lightbox-close").addEventListener("click", () => lightbox.close());
        lightbox.addEventListener("click", event => { if (event.target === lightbox) lightbox.close(); });
    }

    // ---------------------------------------------------------------- upload pop-up
    const dialog = document.querySelector("[data-verify-modal]");
    let openUpload = null;
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
        openUpload = open;

        dialog.querySelectorAll("[data-modal-close]").forEach(b => b.addEventListener("click", close));
        dialog.addEventListener("click", event => { if (event.target === dialog) close(); });
        dialog.addEventListener("cancel", () => remember(LATER_KEY));     // Esc
        document.addEventListener("click", event => {
            if (event.target.closest("[data-verify-open]")) open();
        });
        if (dialog.hasAttribute("data-auto-open") && !remembered(LATER_KEY)) open();

        // A chosen file replaces its upload box with a preview: click the picture to see
        // it full size (a PDF opens in a new tab), "Change" picks another, × removes it
        function formatSize(bytes) {
            return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;
        }

        form.querySelectorAll("input[type=file]").forEach(input => {
            const label = input.closest(".vf-drop");
            const error = dialog.querySelector(`[data-error-for="${input.name}"]`);
            let preview = null;
            let url = null;

            function clearPreview() {
                if (preview) preview.remove();
                if (url) URL.revokeObjectURL(url);
                preview = url = null;
                label.hidden = false;
            }

            function showPreview(file) {
                clearPreview();
                url = URL.createObjectURL(file);
                const isPdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);

                preview = document.createElement("div");
                preview.className = "vf-preview";

                const thumb = document.createElement("button");
                thumb.type = "button";
                thumb.className = "vf-preview-thumb" + (isPdf ? " vf-preview-thumb--pdf" : "");
                thumb.setAttribute("aria-label", `View ${file.name}`);
                if (isPdf) {
                    thumb.textContent = "PDF";
                    thumb.addEventListener("click", () => window.open(url, "_blank", "noopener"));
                } else {
                    const image = document.createElement("img");
                    image.src = url;
                    image.alt = "";
                    thumb.append(image);
                    thumb.addEventListener("click", () => openLightbox(url, file.name));
                }

                const text = document.createElement("div");
                text.className = "vf-preview-text";
                const name = document.createElement("strong");
                name.textContent = file.name;
                const hint = document.createElement("small");
                hint.textContent = `${formatSize(file.size)} · ${isPdf ? "Click to open" : "Click the picture to view it"}`;
                text.append(name, hint);

                const change = document.createElement("button");
                change.type = "button";
                change.className = "vf-preview-change";
                change.textContent = "Change";
                change.addEventListener("click", () => input.click());

                const remove = document.createElement("button");
                remove.type = "button";
                remove.className = "vf-preview-remove";
                remove.textContent = "×";
                remove.setAttribute("aria-label", `Remove ${file.name}`);
                remove.addEventListener("click", () => { input.value = ""; clearPreview(); });

                preview.append(thumb, text, change, remove);
                label.after(preview);
                label.hidden = true;
            }

            input.addEventListener("change", () => {
                const file = input.files[0];
                error.hidden = true;
                if (file && file.size > maxBytes) {
                    input.value = "";
                    error.textContent = `${file.name} is larger than ${form.dataset.maxMb} MB.`;
                    error.hidden = false;
                }
                if (input.files[0]) showPreview(input.files[0]);
                else clearPreview();
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

    // ---------------------------------------------------------------- documents already sent
    const docs = document.querySelector("[data-verify-docs]");
    if (docs) {
        document.addEventListener("click", event => {
            if (event.target.closest("[data-verify-docs-open]")) docs.showModal();
        });
        docs.querySelectorAll("[data-modal-close]").forEach(b => b.addEventListener("click", () => docs.close()));
        docs.addEventListener("click", event => { if (event.target === docs) docs.close(); });
        docs.querySelectorAll("[data-lightbox-src]").forEach(thumb => thumb.addEventListener("click", () => {
            openLightbox(thumb.dataset.lightboxSrc, thumb.querySelector("img").alt);
        }));
    }

    // ---------------------------------------------------------------- not verified yet
    // "Post on Bulletin" / "File a Report" (data-verify-required): open the
    // verification pop-up instead, or point at the banner if documents were already sent.
    // Runs before the buttons' own handlers (capture), so their forms never open.
    // Any File a Report / Post on Bulletin button counts while the "not verified" banner
    // is on the page, even one that doesn't carry data-verify-required itself.
    const NEEDS_VERIFICATION = banner
        ? "[data-verify-required], [data-open-report], [data-open-bulletin]"
        : "[data-verify-required]";
    document.addEventListener("click", event => {
        const button = event.target.closest(NEEDS_VERIFICATION);
        if (!button) return;
        event.preventDefault();
        event.stopPropagation();

        if (openUpload && dialog.hasAttribute("data-can-submit")) {
            openUpload();
        } else if (banner) {
            banner.scrollIntoView({ behavior: "smooth", block: "center" });
            banner.classList.remove("is-flashing");
            void banner.offsetWidth;             // restart the animation
            banner.classList.add("is-flashing");
        }
    }, true);

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
