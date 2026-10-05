function initGallery(gallery) {
    const track = gallery.querySelector(".property-gallery-track");

    if (!track || gallery.dataset.galleryReady) return;

    gallery.dataset.galleryReady = "1";

    const total = track.children.length;
    const position = gallery.querySelector("[data-gallery-position]");
    const prev = gallery.querySelector("[data-gallery-prev]");
    const next = gallery.querySelector("[data-gallery-next]");

    let index = 0;
    let hovering = false;

    const videos = () => track.querySelectorAll("video");

    const currentVideo = () => {
        const slide = track.children[index];

        return slide
            ? (slide.tagName === "VIDEO"
                ? slide
                : slide.querySelector("video"))
            : null;
    };

    function playCurrent() {
        videos().forEach(video => video.pause());

        const video = currentVideo();

        if (video && hovering) {
            video.play().catch(() => {});
        }
    }

    function show(newIndex) {
        index = Math.max(0, Math.min(total - 1, newIndex));

        track.style.transform = `translateX(-${index * 100}%)`;

        if (position) {
            position.textContent = index + 1;
        }

        if (prev) {
            prev.disabled = index === 0;
        }

        if (next) {
            next.disabled = index === total - 1;
        }

        playCurrent();
    }

    if (prev) {
        prev.addEventListener("click", () => {
            show(index - 1);
        });
    }

    if (next) {
        next.addEventListener("click", () => {
            show(index + 1);
        });
    }

    gallery.addEventListener("mouseenter", () => {
        hovering = true;
        playCurrent();
    });

    gallery.addEventListener("mouseleave", () => {
        hovering = false;
        playCurrent();
    });

    show(0);
}


document.addEventListener("DOMContentLoaded", () => {
    document
        .querySelectorAll("[data-gallery]")
        .forEach(initGallery);
});