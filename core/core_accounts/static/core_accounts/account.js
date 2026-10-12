// =========================================================
// ACCOUNT POP-UP: profile menu > My Profile / Settings
// (core_accounts/partials/account_dialog.html, account.py)
// - My Profile: upload / remove the profile photo (every avatar of yours on the page updates)
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

    input.addEventListener("change", async () => {
        const file = input.files[0];
        input.value = "";
        if (!file) return;
        say(photoStatus, "Uploading…");
        const body = new FormData();
        body.append("avatar", file);
        const { ok, data } = await post(photo.dataset.url, body);
        if (!ok) return say(photoStatus, data.error || "Couldn't upload the photo. Please try again.", true);
        showAvatar(data.url, data.initials);
        say(photoStatus, "Photo updated.");
    });

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
