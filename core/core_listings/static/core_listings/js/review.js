// =========================================================
// STEP 4 — REVIEW
// Copies what the landlord typed in steps 1–3 into the review cards.
// =========================================================

(function () {

    const peso = new Intl.NumberFormat("en-PH", { maximumFractionDigits: 0 });

    function getForm() {
        return document.querySelector(".wizard-form");
    }

    function fieldText(form, name) {
        const field = form.elements[name];
        if (!field) return "";
        if (field.tagName === "SELECT") {
            return field.selectedOptions[0] ? field.selectedOptions[0].text : "";
        }
        return field.value.trim();
    }

    function renderPhotos(form) {
        const strip = form.querySelector("[data-review-photos]");
        const count = form.querySelector("[data-review-photo-count]");
        if (!strip) return;

        const uploader = form.querySelector("[data-photo-upload]");
        const api = uploader && uploader.photoUpload;

        // Saved photos (edit mode) first, then the newly added ones
        const saved = [...form.querySelectorAll(".photo-tile.is-saved img")]
            .map(img => ({ url: img.src, name: img.alt }));
        const added = api ? api.items() : [];
        const photos = [...saved, ...added];

        strip.replaceChildren(...photos.map((photo, index) => {
            const tile = document.createElement("figure");
            tile.className = "review-photo";

            const img = document.createElement("img");
            img.src = photo.url;
            img.alt = photo.name;
            if (api) img.addEventListener("click", () => api.open(photo.url, photo.name));
            tile.append(img);

            if (index === 0) {
                const badge = document.createElement("span");
                badge.className = "photo-cover-badge";
                badge.textContent = "Cover";
                tile.append(badge);
            }
            return tile;
        }));

        count.textContent = photos.length
            ? `${photos.length} photo${photos.length === 1 ? "" : "s"} uploaded.`
            : "No photos uploaded yet.";
    }

    function fillReview() {
        const form = getForm();
        if (!form) return;

                form.querySelectorAll("[data-review]").forEach(el => {
            const value = fieldText(form, el.dataset.review);
            el.textContent = value
                ? `${el.dataset.prefix || ""}${value}${el.dataset.suffix || ""}`
                : "—";
        });

        // Checked feature/amenity checkboxes → chips
        form.querySelectorAll("[data-review-features]").forEach(box => {
            const labels = [...form.querySelectorAll("[data-check-feature] input:checked")]
                .map(input => input.closest("[data-check-feature]").querySelector("span").textContent.trim());

            if (!labels.length) {
                box.textContent = "—";
                return;
            }
            box.replaceChildren(...labels.map(text => {
                const chip = document.createElement("span");
                chip.className = "review-chip";
                chip.textContent = `✓ ${text}`;
                return chip;
            }));
        });

        form.querySelectorAll("[data-review-bool]").forEach(el => {
            const field = form.elements[el.dataset.reviewBool];
            const on = Boolean(field && field.checked);
            el.classList.toggle("is-yes", on);
            el.textContent = on ? "Yes" : "No";
        });

        form.querySelectorAll("[data-review-price]").forEach(el => {
            const field = form.elements[el.dataset.reviewPrice];
            const value = field ? parseFloat(field.value) : NaN;
            el.textContent = isNaN(value) ? "₱ —" : `₱ ${peso.format(value)}`;
        });

        renderPhotos(form);
    }

    // Refresh when entering step 4, and when photos change while on it
    document.addEventListener("wizard:step", event => {
        if (event.detail.step === totalSteps()) fillReview();
    });

    document.addEventListener("photos:change", () => {
        if (typeof currentStep !== "undefined" && currentStep === totalSteps()) fillReview();
    });

})();