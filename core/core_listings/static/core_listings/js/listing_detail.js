// =========================================================
// RENTER LISTING PAGES (complex + unit)
// - tabs (remembered in the URL: #units, #location, ...)
// - photo gallery: arrows, thumbnails, full-size viewer
// - "All unit types" filter, "Show more" description
// - buttons whose feature isn't built yet show a short note
// =========================================================

(function () {

    // ---------------------------------------------------------
    // TABS
    // ---------------------------------------------------------

    function initTabs() {
        const tabs = [...document.querySelectorAll(".ld-tab[data-tab]")];
        const panels = [...document.querySelectorAll("[data-panel]")];
        if (!tabs.length) return;

        function show(name, scroll = false) {
            if (!panels.some(panel => panel.dataset.panel === name)) name = tabs[0].dataset.tab;

            tabs.forEach(tab => {
                const active = tab.dataset.tab === name;
                tab.classList.toggle("active", active);
                tab.setAttribute("aria-selected", String(active));
            });
            panels.forEach(panel => { panel.hidden = panel.dataset.panel !== name; });

            // A map inside a hidden tab needs a redraw once it is visible
            const panel = panels.find(p => p.dataset.panel === name);
            if (window.LookAptMaps && panel) window.LookAptMaps.refreshAll(panel);

            history.replaceState(null, "", "#" + name);
            if (scroll) tabs[0].parentElement.scrollIntoView({ behavior: "smooth", block: "start" });
        }

        tabs.forEach(tab => tab.addEventListener("click", () => show(tab.dataset.tab)));

        // Buttons elsewhere that jump to a tab ("View on map", "View Available Units")
        document.querySelectorAll("[data-show-tab]").forEach(button => {
            button.addEventListener("click", () => show(button.dataset.showTab, true));
        });

        show(location.hash.slice(1));
    }


    // ---------------------------------------------------------
    // GALLERY + FULL-SIZE VIEWER
    // ---------------------------------------------------------

    function initGallery(gallery) {
        const track = gallery.querySelector(".property-gallery-track");
        if (!track) return;

        const items = [...track.querySelectorAll("[data-gallery-item]")];
        const position = gallery.querySelector("[data-gallery-position]");
        const prev = gallery.querySelector("[data-gallery-prev]");
        const next = gallery.querySelector("[data-gallery-next]");
        const thumbs = [...gallery.querySelectorAll("[data-gallery-thumb]")];

        const lightbox = gallery.querySelector("[data-gallery-lightbox]");
        const bigImage = lightbox && lightbox.querySelector("[data-lightbox-image]");
        const bigVideo = lightbox && lightbox.querySelector("[data-lightbox-video]");

        let index = 0;

        function show(newIndex) {
            index = Math.max(0, Math.min(items.length - 1, newIndex));
            track.style.transform = `translateX(-${index * 100}%)`;

            if (position) position.textContent = index + 1;
            if (prev) prev.disabled = index === 0;
            if (next) next.disabled = index === items.length - 1;

            thumbs.forEach(thumb => thumb.classList.toggle("active", Number(thumb.dataset.galleryThumb) === index));

            // Only the video on screen plays (muted, like the listing cards)
            items.forEach((item, i) => {
                if (item.tagName !== "VIDEO") return;
                if (i === index) item.play().catch(() => {});
                else item.pause();
            });

            if (lightbox && lightbox.open) fillLightbox();
        }

        function fillLightbox() {
            const item = items[index];
            const isVideo = item.tagName === "VIDEO";
            bigImage.hidden = isVideo;
            bigVideo.hidden = !isVideo;
            if (isVideo) {
                bigVideo.src = item.currentSrc || item.src;
            } else {
                bigVideo.pause();
                bigImage.src = item.currentSrc || item.src;
            }
            lightbox.querySelectorAll("[data-lightbox-prev]").forEach(b => { b.disabled = index === 0; });
            lightbox.querySelectorAll("[data-lightbox-next]").forEach(b => { b.disabled = index === items.length - 1; });
        }

        function openLightbox() {
            if (!lightbox) return;
            items.forEach(item => item.tagName === "VIDEO" && item.pause());
            fillLightbox();
            lightbox.showModal();
        }

        prev && prev.addEventListener("click", () => show(index - 1));
        next && next.addEventListener("click", () => show(index + 1));
        thumbs.forEach(thumb => thumb.addEventListener("click", () => show(Number(thumb.dataset.galleryThumb))));

        gallery.querySelector("[data-gallery-open]")?.addEventListener("click", openLightbox);
        track.addEventListener("click", openLightbox);

        if (lightbox) {
            // Inside the page it could be clipped by the gallery; <body> is safer
            document.body.append(lightbox);
            lightbox.querySelector("[data-lightbox-close]").addEventListener("click", () => lightbox.close());
            lightbox.querySelector("[data-lightbox-prev]")?.addEventListener("click", () => show(index - 1));
            lightbox.querySelector("[data-lightbox-next]")?.addEventListener("click", () => show(index + 1));
            lightbox.addEventListener("click", event => { if (event.target === lightbox) lightbox.close(); });
            lightbox.addEventListener("close", () => bigVideo.pause());
            lightbox.addEventListener("keydown", event => {
                if (event.key === "ArrowLeft") show(index - 1);
                if (event.key === "ArrowRight") show(index + 1);
            });
        }

        show(0);
    }


    // ---------------------------------------------------------
    // UNITS TAB: filter by unit type
    // ---------------------------------------------------------

    function initUnitFilter() {
        const select = document.querySelector("[data-unit-filter]");
        if (!select) return;

        select.addEventListener("change", () => {
            document.querySelectorAll(".ld-unit-row[data-unit-type]").forEach(row => {
                row.hidden = Boolean(select.value) && row.dataset.unitType !== select.value;
            });
        });
    }


    // ---------------------------------------------------------
    // "Show more" for long descriptions
    // ---------------------------------------------------------

    function initClamp() {
        document.querySelectorAll("[data-clamp]").forEach(text => {
            const toggle = text.parentElement.querySelector("[data-clamp-toggle]");
            if (!toggle) return;

            // Only offer "Show more" when the text is actually cut off
            toggle.hidden = text.scrollHeight <= text.clientHeight + 2;

            toggle.addEventListener("click", () => {
                const expanded = text.classList.toggle("is-expanded");
                toggle.textContent = expanded ? "Show less" : "Show more";
            });
        });
    }


    // ---------------------------------------------------------
    // Sidebar: highlight the tab the renter came from
    // ---------------------------------------------------------

    function highlightSidebar() {
        const page = document.querySelector(".ld-page");
        const origin = page ? page.dataset.origin : "home";
        document.querySelectorAll(".sidebar-link[data-tab]").forEach(link => {
            link.classList.toggle("active", link.dataset.tab === origin);
        });
    }


    document.addEventListener("DOMContentLoaded", () => {
        initTabs();
        document.querySelectorAll("[data-detail-gallery]").forEach(initGallery);
        initUnitFilter();
        initClamp();
        highlightSidebar();
    });

})();