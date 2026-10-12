// =========================================================
// ACCOUNT POP-UP: profile menu > My Profile / Settings
// (core_accounts/partials/account_dialog.html, account.py)
// - My Profile: upload / remove the profile photo (every avatar of yours on the page updates).
//   A chosen photo first opens "Adjust your photo" (move + zoom inside the circle); only
//   the cropped square is uploaded.
// - Settings: contact sharing (saved right away), change password
// =========================================================

(function () {

    const dialog = document.querySelector("[data-account]");
    if (!dialog) return;

    const csrf = dialog.dataset.csrf;

    async function post(url, body) {
        const response = await fetch(url, {
            method: "POST",
            body,
            credentials: "same-origin",
            headers: { "X-CSRFToken": csrf, Accept: "application/json" },
        });
        let data = {};
        try { data = await response.json(); } catch (error) { /* not JSON: treated as a failure below */ }
        return { ok: response.ok, data };
    }

    function say(slot, text, isError = false) {
        if (!slot) return;
        slot.textContent = text;
        slot.classList.toggle("is-error", isError);
    }


    // ---------------------------------------------------- opening + tabs

    const tabs = [...dialog.querySelectorAll("[data-account-tab]")];
    const panels = [...dialog.querySelectorAll("[data-account-panel]")];

    function showTab(name) {
        tabs.forEach(tab => tab.setAttribute("aria-selected", String(tab.dataset.accountTab === name)));
        panels.forEach(panel => { panel.hidden = panel.dataset.accountPanel !== name; });
    }

    tabs.forEach(tab => tab.addEventListener("click", () => showTab(tab.dataset.accountTab)));

    document.querySelectorAll("[data-account-open]").forEach(item => item.addEventListener("click", () => {
        // Close the profile menu it was opened from
        document.querySelectorAll(".topbar-menu").forEach(menu => { menu.hidden = true; });
        document.querySelectorAll("[data-topbar-toggle]").forEach(toggle => toggle.setAttribute("aria-expanded", "false"));
        showTab(item.dataset.accountOpen);
        dialog.showModal();
    }));

    dialog.querySelectorAll("[data-account-close]").forEach(button => button.addEventListener("click", () => dialog.close()));
    dialog.addEventListener("click", event => { if (event.target === dialog) dialog.close(); });   // click outside


    // ---------------------------------------------------- profile photo

    const photo = dialog.querySelector("[data-avatar-form]");
    const input = photo.querySelector("[data-avatar-input]");
    const removeButton = photo.querySelector("[data-avatar-remove]");
    const uploadLabel = photo.querySelector("[data-avatar-upload-label]");
    const photoStatus = photo.querySelector("[data-avatar-status]");

    // Every avatar of the signed-in user on this page: top bar + this pop-up
    function showAvatar(url, initials) {
        document.querySelectorAll(".topbar-right [data-avatar], [data-account] [data-avatar]").forEach(avatar => {
            avatar.replaceChildren();
            if (url) {
                const image = document.createElement("img");
                image.src = url;
                image.alt = "";
                avatar.append(image);
            } else {
                avatar.textContent = initials || avatar.dataset.initials;
            }
        });
        removeButton.hidden = !url;
        uploadLabel.textContent = url ? "Change photo" : "Upload photo";
    }

    async function upload(blob) {
        say(photoStatus, "Uploading…");
        const body = new FormData();
        body.append("avatar", blob, "avatar.jpg");
        const { ok, data } = await post(photo.dataset.url, body);
        if (!ok) return say(photoStatus, data.error || "Couldn't upload the photo. Please try again.", true);
        showAvatar(data.url, data.initials);
        say(photoStatus, "Photo updated.");
    }

    input.addEventListener("change", () => {
        const file = input.files[0];
        input.value = "";
        if (!file) return;
        if (!/^image\/(jpeg|png|webp)$/.test(file.type)) return say(photoStatus, "Use a JPG, PNG or WEBP photo.", true);
        if (file.size > MAX_PHOTO_MB * 1024 * 1024) return say(photoStatus, `That photo is too big. The limit is ${MAX_PHOTO_MB} MB.`, true);
        say(photoStatus, "");
        cropper.open(file);
    });


    // ---------------------------------------------------- "Adjust your photo"
    // The photo sits in a square stage; the circle (inset by MARGIN) is what gets saved.
    // x, y = the photo's top-left corner in the stage; scale = screen px per photo px.

    const MAX_PHOTO_MB = 15;         // the original can be big: only the cropped square is uploaded
    const OUTPUT = 640;              // saved size (the server stores it at 320x320)
    const MAX_ZOOM = 4;

    const cropper = (function () {
        const box = document.querySelector("[data-crop]");
        const stage = box.querySelector("[data-crop-stage]");
        const image = box.querySelector("[data-crop-image]");
        const zoomInput = box.querySelector("[data-crop-zoom]");
        const saveButton = box.querySelector("[data-crop-save]");
        let url = "", base = 1, zoom = 1, x = 0, y = 0;
        const pointers = new Map();
        let pinchStart = null;

        const size = () => stage.clientWidth;
        const margin = () => Math.round(size() * 0.07);
        const circle = () => size() - 2 * margin();
        const scale = () => base * zoom;

        // Keep the circle fully covered by the photo
        function clamp() {
            const m = margin(), c = circle();
            const w = image.naturalWidth * scale(), h = image.naturalHeight * scale();
            x = Math.min(m, Math.max(m + c - w, x));
            y = Math.min(m, Math.max(m + c - h, y));
        }

        function draw() {
            clamp();
            image.style.width = `${image.naturalWidth * scale()}px`;
            image.style.transform = `translate(${x}px, ${y}px)`;
            zoomInput.value = String(zoom);
        }

        // Zoom, keeping the point at (px, py) of the stage in place (default: the circle's centre)
        function zoomTo(next, px = size() / 2, py = size() / 2) {
            next = Math.min(MAX_ZOOM, Math.max(1, next));
            const before = scale();
            zoom = next;
            x = px - (px - x) * scale() / before;
            y = py - (py - y) * scale() / before;
            draw();
        }

        function reset() {
            base = circle() / Math.min(image.naturalWidth, image.naturalHeight);   // the short side fills the circle
            zoom = 1;
            x = margin() + (circle() - image.naturalWidth * base) / 2;
            y = margin() + (circle() - image.naturalHeight * base) / 2;
            draw();
        }

        function open(file) {
            if (url) URL.revokeObjectURL(url);
            url = URL.createObjectURL(file);
            image.onload = () => { box.showModal(); reset(); stage.focus(); };
            image.onerror = () => say(photoStatus, "That file isn't a photo we can read. Try a JPG, PNG or WEBP.", true);
            image.src = url;
        }

        function close() {
            box.close();
            if (url) URL.revokeObjectURL(url);
            url = "";
            image.removeAttribute("src");
        }

        // Drag with a mouse or one finger; pinch with two
        stage.addEventListener("pointerdown", event => {
            stage.setPointerCapture(event.pointerId);
            pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
            if (pointers.size === 2) {
                const [a, b] = [...pointers.values()];
                pinchStart = { distance: Math.hypot(a.x - b.x, a.y - b.y), zoom };
            }
        });
        stage.addEventListener("pointermove", event => {
            const last = pointers.get(event.pointerId);
            if (!last) return;
            const now = { x: event.clientX, y: event.clientY };
            pointers.set(event.pointerId, now);
            if (pointers.size === 2 && pinchStart) {
                const [a, b] = [...pointers.values()];
                zoomTo(pinchStart.zoom * Math.hypot(a.x - b.x, a.y - b.y) / pinchStart.distance);
            } else if (pointers.size === 1) {
                // Screen px -> stage px (the page may be zoomed, e.g. 90%)
                const ratio = size() / stage.getBoundingClientRect().width;
                x += (now.x - last.x) * ratio;
                y += (now.y - last.y) * ratio;
                draw();
            }
        });
        const release = event => {
            pointers.delete(event.pointerId);
            if (pointers.size < 2) pinchStart = null;
        };
        stage.addEventListener("pointerup", release);
        stage.addEventListener("pointercancel", release);

        stage.addEventListener("wheel", event => {
            event.preventDefault();
            const rect = stage.getBoundingClientRect();
            const ratio = size() / rect.width;
            zoomTo(zoom * (event.deltaY < 0 ? 1.08 : 1 / 1.08),
                   (event.clientX - rect.left) * ratio, (event.clientY - rect.top) * ratio);
        }, { passive: false });

        stage.addEventListener("keydown", event => {
            const moves = { ArrowLeft: [-10, 0], ArrowRight: [10, 0], ArrowUp: [0, -10], ArrowDown: [0, 10] };
            if (moves[event.key]) {
                x += moves[event.key][0];
                y += moves[event.key][1];
                draw();
            } else if (event.key === "+" || event.key === "=") {
                zoomTo(zoom + 0.1);
            } else if (event.key === "-") {
                zoomTo(zoom - 0.1);
            } else {
                return;
            }
            event.preventDefault();
        });

        zoomInput.addEventListener("input", () => zoomTo(Number(zoomInput.value)));
        box.querySelectorAll("[data-crop-step]").forEach(button => button.addEventListener("click", () =>
            zoomTo(zoom + Number(button.dataset.cropStep) * 0.25)));

        box.querySelector("[data-crop-cancel]").addEventListener("click", close);
        box.addEventListener("cancel", event => { event.preventDefault(); close(); });     // Esc

        // The part of the photo inside the circle -> a square JPG
        saveButton.addEventListener("click", () => {
            const canvas = document.createElement("canvas");
            canvas.width = canvas.height = OUTPUT;
            const context = canvas.getContext("2d");
            context.fillStyle = "#fff";                     // transparent PNGs get a white background
            context.fillRect(0, 0, OUTPUT, OUTPUT);
            context.imageSmoothingQuality = "high";
            const s = scale();
            context.drawImage(image, (margin() - x) / s, (margin() - y) / s, circle() / s, circle() / s, 0, 0, OUTPUT, OUTPUT);
            saveButton.disabled = true;
            canvas.toBlob(blob => {
                saveButton.disabled = false;
                close();
                if (blob) upload(blob);
                else say(photoStatus, "Couldn't prepare the photo. Please try another one.", true);
            }, "image/jpeg", 0.92);
        });

        return { open };
    })();

    removeButton.addEventListener("click", async () => {
        const body = new FormData();
        body.append("remove", "1");
        const { ok, data } = await post(photo.dataset.url, body);
        if (!ok) return say(photoStatus, "Couldn't remove the photo. Please try again.", true);
        showAvatar("", data.initials);
        say(photoStatus, "Photo removed. Your initials are shown instead.");
    });


    // ---------------------------------------------------- contact sharing (saved on every change)

    const contact = dialog.querySelector("[data-contact-form]");
    const contactStatus = contact.querySelector("[data-contact-status]");

    contact.addEventListener("change", async () => {
        const body = new FormData();
        body.append("share_email", contact.querySelector("[name=share_email]").checked ? "1" : "0");
        body.append("share_phone", contact.querySelector("[name=share_phone]").checked ? "1" : "0");
        const { ok, data } = await post(contact.dataset.url, body);
        if (!ok) return say(contactStatus, "Couldn't save. Please try again.", true);
        const shown = [data.share_email && "email", data.share_phone && "phone number"].filter(Boolean);
        say(contactStatus, shown.length ? `Saved. Your ${shown.join(" and ")} will be shown.` : "Saved. LookApt chat only.");
    });


    // ---------------------------------------------------- change password

    const passwordForm = dialog.querySelector("[data-password-form]");
    const passwordStatus = passwordForm.querySelector("[data-password-status]");

    function setFieldError(name, message) {
        const slot = passwordForm.querySelector(`[data-error-for="${name}"]`);
        slot.textContent = message || "";
        slot.closest(".ac-field").classList.toggle("has-error", Boolean(message));
    }

    passwordForm.addEventListener("submit", async event => {
        event.preventDefault();
        ["current_password", "password", "confirm_password"].forEach(name => setFieldError(name, ""));
        say(passwordStatus, "");
        const button = passwordForm.querySelector("[type=submit]");
        button.disabled = true;
        const { ok, data } = await post(passwordForm.action, new FormData(passwordForm));
        button.disabled = false;
        if (!ok) {
            Object.entries(data.errors || {}).forEach(([name, message]) => setFieldError(name, message));
            if (!data.errors) say(passwordStatus, "Couldn't change your password. Please try again.", true);
            return;
        }
        passwordForm.reset();
        say(passwordStatus, "Password changed.");
    });

})();