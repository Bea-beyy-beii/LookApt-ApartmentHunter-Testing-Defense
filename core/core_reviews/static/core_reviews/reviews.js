// =========================================================
// RENTAL HISTORY — "Leave a Review" / "Edit Review" pop-up
// (core_reviews/review_modal.html). Stars for the complex, the unit and the
// landlord, optional feedback, up to 5 photos. The server re-checks everything.
// =========================================================

(function () {

    const TOAST_KEY = "lookapt:reviews:toast";

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

    function init() {
        const dialog = document.querySelector("[data-review-modal]");
        if (!dialog) return;

        const form = dialog.querySelector("[data-review-form]");
        const formError = dialog.querySelector("[data-form-error]");
        const submit = dialog.querySelector("[data-submit]");
        const photoBox = dialog.querySelector("[data-review-photos]");
        const upload = dialog.querySelector("[data-review-upload]");
        const input = dialog.querySelector("[data-review-input]");
        const maxPhotos = Number(form.dataset.maxPhotos) || 5;
        const maxBytes = (Number(form.dataset.maxMb) || 5) * 1048576;

        let url = "";
        let saved = [];        // photos already on the review: {id, url}
        let removed = [];      // ids of saved photos the renter took out
        let added = [];        // new File objects
        let previews = [];     // object URLs for the new files (freed on close)


        // ---------- errors ----------

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


        // ---------- photos ----------

        function thumb(src, label, onRemove) {
            const item = document.createElement("div");
            item.className = "rv-thumb";
            const img = document.createElement("img");
            img.src = src;
            img.alt = "";
            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "rv-thumb-remove";
            remove.setAttribute("aria-label", `Remove ${label}`);
            remove.textContent = "×";
            remove.addEventListener("click", onRemove);
            item.append(img, remove);
            return item;
        }

        function renderPhotos() {
            previews.forEach(URL.revokeObjectURL);
            previews = added.map(file => URL.createObjectURL(file));

            const kept = saved.filter(photo => !removed.includes(photo.id));
            const items = [
                ...kept.map(photo => thumb(photo.url, "photo", () => { removed.push(photo.id); renderPhotos(); })),
                ...added.map((file, i) => thumb(previews[i], file.name, () => { added.splice(i, 1); renderPhotos(); })),
            ];
            // Empty "+" slots up to the limit (they open the file picker too)
            while (items.length < maxPhotos) {
                const slot = document.createElement("button");
                slot.type = "button";
                slot.className = "rv-slot";
                slot.setAttribute("aria-label", "Add a photo");
                slot.textContent = "+";
                slot.addEventListener("click", () => input.click());
                items.push(slot);
            }
            photoBox.replaceChildren(upload, ...items);
            upload.classList.toggle("is-full", kept.length + added.length >= maxPhotos);
        }

        function addPhotos(list) {
            const errors = [];
            for (const file of list) {
                const count = saved.filter(p => !removed.includes(p.id)).length + added.length;
                if (count >= maxPhotos) { errors.push(`You can add up to ${maxPhotos} photos.`); break; }
                if (!["image/png", "image/jpeg"].includes(file.type)) { errors.push(`${file.name} isn't a PNG or JPG photo.`); continue; }
                if (file.size > maxBytes) { errors.push(`${file.name} is larger than ${form.dataset.maxMb} MB.`); continue; }
                added.push(file);
            }
            renderPhotos();
            if (errors.length) showErrors({ photos: errors.join(" ") });
        }

        input.addEventListener("change", () => { addPhotos(input.files); input.value = ""; });


        // ---------- counters ----------

        function updateCounter(textarea) {
            const counter = dialog.querySelector(`[data-counter-for="${textarea.name}"]`);
            if (counter) counter.textContent = `${textarea.value.length}/${textarea.maxLength}`;
        }

        form.querySelectorAll("textarea").forEach(textarea => {
            textarea.addEventListener("input", () => updateCounter(textarea));
        });

        form.addEventListener("change", event => {
            const fieldError = dialog.querySelector(`[data-error-for="${event.target.name}"]`);
            if (fieldError) fieldError.hidden = true;
        });


        // ---------- open ----------

        function open(button) {
            form.reset();
            clearErrors();
            url = button.dataset.url;
            removed = [];
            added = [];

            dialog.querySelector("[data-review-complex]").textContent = button.dataset.complex;
            dialog.querySelector("[data-review-address]").textContent = button.dataset.address;
            dialog.querySelector("[data-review-unit]").textContent = button.dataset.unit;
            const cover = dialog.querySelector("[data-review-cover]");
            cover.querySelector("img")?.remove();
            if (button.dataset.cover) {
                const img = document.createElement("img");
                img.src = button.dataset.cover;
                img.alt = "";
                cover.append(img);
            }

            // Editing: start from the saved review
            let review = null;
            try { review = button.dataset.review ? JSON.parse(button.dataset.review) : null; } catch (error) { review = null; }
            saved = review?.photos || [];
            if (review) {
                for (const [name, value] of Object.entries(review)) {
                    const field = form.elements[name];
                    if (!field || name === "photos") continue;
                    if (field instanceof RadioNodeList) {
                        [...field].forEach(radio => { radio.checked = radio.value === String(value); });
                    } else {
                        field.value = value;
                    }
                }
            }
            form.querySelectorAll("textarea").forEach(updateCounter);
            dialog.querySelector("[data-review-title]").textContent = review ? "Edit Your Review" : "Write a Review";
            submit.textContent = review ? "Save Review" : "Submit Review";
            submit.dataset.label = submit.textContent;

            renderPhotos();
            dialog.showModal();
            dialog.querySelector(".lm-body").scrollTop = 0;
        }

        document.addEventListener("click", event => {
            const button = event.target.closest("[data-open-review]");
            if (button) open(button);
        });
        dialog.addEventListener("click", event => { if (event.target === dialog) dialog.close(); });
        dialog.querySelectorAll("[data-modal-close]").forEach(b => b.addEventListener("click", () => dialog.close()));
        dialog.addEventListener("close", () => { previews.forEach(URL.revokeObjectURL); previews = []; });


        // ---------- submit ----------

        form.addEventListener("submit", async event => {
            event.preventDefault();
            const errors = {};
            ["complex", "unit", "landlord"].forEach(part => {
                if (!form.querySelector(`input[name=${part}_rating]:checked`)) errors[`${part}_rating`] = "Pick 1 to 5 stars.";
            });
            if (Object.keys(errors).length) return showErrors(errors);

            const data = new FormData();
            ["complex", "unit", "landlord"].forEach(part => {
                data.append(`${part}_rating`, form.querySelector(`input[name=${part}_rating]:checked`).value);
                data.append(`${part}_feedback`, form.elements[`${part}_feedback`].value.trim());
            });
            added.forEach(file => data.append("photos", file));
            removed.forEach(id => data.append("remove_photos", id));

            submit.disabled = true;
            submit.textContent = "Submitting…";
            try {
                const response = await fetch(url, {
                    method: "POST", body: data, credentials: "same-origin",
                    headers: { "X-CSRFToken": csrfToken(), "Accept": "application/json" },
                });
                const body = await response.json().catch(() => ({}));
                if (!response.ok) {
                    return showErrors(body.errors || { __all__: "Something went wrong. Please try again." });
                }
                // Reload so the button shows your stars (the toast follows)
                try { sessionStorage.setItem(TOAST_KEY, body.message); } catch (error) { /* ignore */ }
                location.reload();
            } catch (error) {
                showErrors({ __all__: "Couldn't reach the server. Check your connection and try again." });
            } finally {
                submit.disabled = false;
                submit.textContent = submit.dataset.label;
            }
        });

        try {
            const message = sessionStorage.getItem(TOAST_KEY);
            if (message) {
                sessionStorage.removeItem(TOAST_KEY);
                toast(message);
            }
        } catch (error) { /* ignore */ }
    }

    document.addEventListener("DOMContentLoaded", init);

})();
