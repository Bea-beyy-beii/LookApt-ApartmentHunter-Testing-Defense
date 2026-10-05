// =========================================================
// RENTER — save / unsave a listing with the ribbon button.
// The same complex can appear twice (Home + Saved Listings),
// so every copy of its ribbon is updated together.
// =========================================================

(function () {

    function csrfToken() {
        const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    function setSaved(complexId, saved) {
        document.querySelectorAll(`[data-listing-card][data-complex-id="${complexId}"] [data-save-listing]`)
            .forEach(button => {
                button.classList.toggle("is-saved", saved);
                button.setAttribute("aria-pressed", String(saved));
                button.setAttribute("aria-label", saved ? "Remove from saved" : "Save listing");
            });
    }

    function updateSavedTab(card, complexId, saved) {
        const grid = document.querySelector("[data-saved-grid]");
        if (!grid) return;

        const existing = grid.querySelector(`[data-listing-card][data-complex-id="${complexId}"]`);

        if (saved && !existing) {
            // Copy the card into Saved Listings (newest first)
            const copy = card.cloneNode(true);
            copy.querySelector("[data-save-listing]").disabled = false;
            const gallery = copy.querySelector("[data-gallery]");
            if (gallery) {
                delete gallery.dataset.galleryReady;
                initGallery(gallery);
            }
            grid.prepend(copy);
        }

        if (!saved && existing) {
            existing.remove();
        }

        const empty = document.querySelector("[data-saved-empty]");
        if (empty) empty.hidden = grid.children.length > 0;
    }

    document.addEventListener("click", async event => {
        const button = event.target.closest("[data-save-listing]");
        if (!button || button.disabled) return;

        const card = button.closest("[data-listing-card]");
        const complexId = card.dataset.complexId;
        const wasSaved = button.classList.contains("is-saved");

        // Fill / empty the ribbon right away, undo if the server says no
        setSaved(complexId, !wasSaved);
        button.disabled = true;

        try {
            const response = await fetch(button.dataset.url, {
                method: "POST",
                headers: { "X-CSRFToken": csrfToken(), "Accept": "application/json" },
                credentials: "same-origin",
            });
            if (!response.ok) throw new Error(response.status);

            const data = await response.json();
            setSaved(complexId, data.saved);
            updateSavedTab(card, complexId, data.saved);
        } catch (error) {
            setSaved(complexId, wasSaved);
        } finally {
            button.disabled = false;
        }
    });

})();