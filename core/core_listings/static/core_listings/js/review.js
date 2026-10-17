// =========================================================
// REVIEW STEP (last step of the property / unit wizard)
// Copies what the landlord entered into the review cards.
// =========================================================

(function () {

    const peso = new Intl.NumberFormat("en-PH", { maximumFractionDigits: 0 });

    const getForm = () => document.querySelector(".wizard-form");

    function fieldText(form, name) {
        const field = form.elements[name];
        if (!field) return "";
        if (field.tagName === "SELECT") {
            return field.selectedOptions[0] ? field.selectedOptions[0].text : "";
        }
        return String(field.value || "").trim();
    }

    function featureLabel(input) {
        const holder = input.closest("[data-check-feature]");
        const label = holder.querySelector("[data-feature-label]") || holder.querySelector("span");
        return label ? label.textContent.trim() : input.name;
    }


    // ---------- checked amenities / features as removable chips ----------

    function renderFeatures(form) {
        form.querySelectorAll("[data-review-features]").forEach(box => {
            const checked = [...form.querySelectorAll("[data-check-feature] input:checked")];

            if (!checked.length) {
                box.textContent = "—";
                return;
            }

            box.replaceChildren(...checked.map(input => {
                const name = featureLabel(input);

                const chip = document.createElement("span");
                chip.className = "review-chip";

                const text = document.createElement("span");
                text.textContent = name;

                const remove = document.createElement("button");
                remove.type = "button";
                remove.className = "review-chip-remove";
                remove.textContent = "×";
                remove.setAttribute("aria-label", `Remove ${name}`);
                remove.addEventListener("click", () => {
                    input.checked = false;                                          // unticks it in step 1
                    input.dispatchEvent(new Event("change", { bubbles: true }));    // saves the draft
                    fillReview();
                });

                chip.append(text, remove);
                return chip;
            }));
        });
    }


    // ---------- photos + videos ----------

    function renderMedia(form) {
        const strip = form.querySelector("[data-review-photos]");
        const count = form.querySelector("[data-review-photo-count]");
        if (!strip) return;

        const uploader = form.querySelector("[data-photo-upload]");
        const api = uploader && uploader.photoUpload;

        // The uploader lists saved + new photos in the landlord's order
        const all = api ? api.items() : [];
        const photos = all.filter(item => item.kind === "image");
        const videos = all.filter(item => item.kind === "video");

        strip.replaceChildren(...[...photos, ...videos].map((item, index) => {
            const tile = document.createElement("figure");
            tile.className = "review-photo";

            let media;
            if (item.kind === "video") {
                media = document.createElement("video");
                media.src = item.url;
                media.muted = true;
                media.playsInline = true;
                media.preload = "metadata";

                const badge = document.createElement("span");
                badge.className = "photo-video-badge";
                badge.textContent = "▶ Video";
                tile.append(media, badge);
            } else {
                media = document.createElement("img");
                media.src = item.url;
                media.alt = item.name;
                tile.append(media);
            }
            if (api) media.addEventListener("click", () => api.open(item.url, item.name, item.kind));

            if (index === 0 && item.kind === "image") {
                const badge = document.createElement("span");
                badge.className = "photo-cover-badge";
                badge.textContent = "Cover";
                tile.append(badge);
            }
            return tile;
        }));

        const parts = [];
        if (photos.length) parts.push(`${photos.length} photo${photos.length === 1 ? "" : "s"}`);
        if (videos.length) parts.push(`${videos.length} video${videos.length === 1 ? "" : "s"}`);
        count.textContent = parts.length ? `${parts.join(" · ")} uploaded.` : "No photos uploaded yet.";
    }


    // ---------- fill everything ----------

    function fillReview() {
        const form = getForm();
        if (!form) return;

        form.querySelectorAll("[data-review]").forEach(el => {
            const value = fieldText(form, el.dataset.review);
            el.textContent = value
                ? `${el.dataset.prefix || ""}${value}${el.dataset.suffix || ""}`
                : "—";
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

        renderFeatures(form);
        renderMedia(form);
    }

    document.addEventListener("wizard:step", event => {
        if (event.detail.step === totalSteps()) fillReview();
    });

    document.addEventListener("photos:change", () => {
        if (typeof currentStep !== "undefined" && currentStep === totalSteps()) fillReview();
    });

})();