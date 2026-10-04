// =========================================================
// STEP 3 — PHOTO UPLOAD
// Left: drop zone (click or drag & drop). Right: previews.
// - Drag a preview onto another to swap them (slot 1 = cover)
// - Photos survive a page refresh (stored in IndexedDB)
// =========================================================

(function () {

    const ALLOWED_TYPES = ["image/png", "image/jpeg"];
    const ALLOWED_EXTENSIONS = /\.(png|jpe?g)$/i;
    const MAX_SIZE = 5 * 1024 * 1024; // 5 MB


    // ---------------------------------------------------------
    // IndexedDB: the only browser storage that can hold real File objects
    // ---------------------------------------------------------

    const DB_NAME = "lookapt-drafts";
    const STORE = "photos";

    function withStore(mode, action) {
        return new Promise((resolve, reject) => {
            const open = indexedDB.open(DB_NAME, 1);
            open.onupgradeneeded = () => open.result.createObjectStore(STORE);
            open.onerror = () => reject(open.error);
            open.onsuccess = () => {
                const db = open.result;
                const tx = db.transaction(STORE, mode);
                const request = action(tx.objectStore(STORE));
                tx.oncomplete = () => { db.close(); resolve(request ? request.result : undefined); };
                tx.onerror = () => { db.close(); reject(tx.error); };
            };
        });
    }

    const savePhotos = (key, fileList) => withStore("readwrite", store => store.put(fileList, key));
    const loadPhotos = key => withStore("readonly", store => store.get(key));
    const clearPhotos = key => withStore("readwrite", store => store.delete(key));


    function initPhotoUpload(root) {
        const max = Number(root.dataset.max) || 5;
        const existing = Number(root.dataset.existing) || 0;

        const form = root.closest("form");
        const draftKey = "lookapt:wizard:" + (form ? form.getAttribute("action") : location.pathname);

        const input = root.querySelector('input[type="file"]');
        const zone = root.querySelector(".photo-dropzone");
        const grid = root.querySelector(".photo-preview-grid");
        const counter = root.querySelector(".photo-count");
        const errorBox = root.querySelector(".photo-upload-error");
        const lightbox = root.querySelector(".photo-lightbox");
        const lightboxImg = lightbox.querySelector("img");

        let files = [];        // [{ file, url }]
        let dragFrom = null;   // index of the tile being dragged

        const total = () => existing + files.length;


        // ---------- helpers ----------

        function showError(message) {
            errorBox.textContent = message;
            errorBox.hidden = !message;
        }

        function syncInput() {
            const transfer = new DataTransfer();
            files.forEach(item => transfer.items.add(item.file));
            input.files = transfer.files;
        }

        function openLightbox(src, alt) {
            lightboxImg.src = src;
            lightboxImg.alt = alt || "";
            lightbox.showModal();
        }

        // Called after every change: save for refresh + tell the review step
        function changed() {
            savePhotos(draftKey, files.map(item => item.file)).catch(() => {});
            root.dispatchEvent(new CustomEvent("photos:change", { bubbles: true }));
        }


        // ---------- add / remove / swap ----------

        function addFiles(fileList) {
            const errors = [];

            for (const file of fileList) {
                if (total() >= max) {
                    errors.push(`You can only upload ${max} photos.`);
                    break;
                }
                if (!ALLOWED_TYPES.includes(file.type) || !ALLOWED_EXTENSIONS.test(file.name)) {
                    errors.push(`${file.name}: only PNG or JPG files are allowed.`);
                    continue;
                }
                if (file.size > MAX_SIZE) {
                    errors.push(`${file.name} is larger than 5 MB.`);
                    continue;
                }
                const duplicate = files.some(item => item.file.name === file.name && item.file.size === file.size);
                if (duplicate) continue;

                files.push({ file, url: URL.createObjectURL(file) });
            }

            showError(errors.join(" "));
            syncInput();
            render();
            changed();
        }

        function removeFile(index) {
            URL.revokeObjectURL(files[index].url);
            files.splice(index, 1);
            showError("");
            syncInput();
            render();
            changed();
        }

        function swapFiles(a, b) {
            if (a === b) return;
            [files[a], files[b]] = [files[b], files[a]];
            syncInput();   // the input order is the order the server saves (first = cover)
            render();
            changed();
        }


        // ---------- render previews ----------

        function makeDraggable(tile, index) {
            tile.draggable = true;

            tile.addEventListener("dragstart", event => {
                dragFrom = index;
                tile.classList.add("is-dragging");
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", String(index));   // required by Firefox
            });

            tile.addEventListener("dragend", () => {
                dragFrom = null;
                grid.querySelectorAll(".is-dragging, .is-drop-target")
                    .forEach(el => el.classList.remove("is-dragging", "is-drop-target"));
            });

            tile.addEventListener("dragover", event => {
                if (dragFrom === null) return;   // ignore files dragged in from outside
                event.preventDefault();
                tile.classList.add("is-drop-target");
            });

            tile.addEventListener("dragleave", () => tile.classList.remove("is-drop-target"));

            tile.addEventListener("drop", event => {
                if (dragFrom === null) return;
                event.preventDefault();
                event.stopPropagation();
                swapFiles(dragFrom, index);
            });
        }

        function render() {
            grid.querySelectorAll(".is-new, .is-empty").forEach(tile => tile.remove());

            files.forEach((item, index) => {
                const tile = document.createElement("div");
                tile.className = "photo-tile is-new";

                const img = document.createElement("img");
                img.src = item.url;
                img.alt = item.file.name;
                img.draggable = false;   // drag the tile, not the image itself
                img.addEventListener("click", () => openLightbox(item.url, item.file.name));

                const remove = document.createElement("button");
                remove.type = "button";
                remove.className = "photo-remove";
                remove.textContent = "×";
                remove.setAttribute("aria-label", `Remove ${item.file.name}`);
                remove.addEventListener("click", () => removeFile(index));

                tile.append(img, remove);

                if (existing === 0 && index === 0) {
                    const badge = document.createElement("span");
                    badge.className = "photo-cover-badge";
                    badge.textContent = "Cover";
                    tile.append(badge);
                }

                makeDraggable(tile, index);
                grid.append(tile);
            });

            for (let i = total(); i < max; i++) {
                const empty = document.createElement("div");
                empty.className = "photo-tile is-empty";
                grid.append(empty);
            }

            counter.textContent = `(${total()}/${max})`;
            zone.classList.toggle("is-full", total() >= max);
        }


        // ---------- events ----------

        input.addEventListener("change", () => {
            const picked = [...input.files];
            addFiles(picked);
        });

        zone.addEventListener("click", event => {
            if (total() >= max) {
                event.preventDefault();
                showError(`You can only upload ${max} photos. Remove one to add another.`);
            }
        });

        zone.addEventListener("keydown", event => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                event.stopPropagation();
                zone.click();
            }
        });

        ["dragenter", "dragover"].forEach(type => {
            zone.addEventListener(type, event => {
                event.preventDefault();
                zone.classList.add("is-dragging");
            });
        });

        ["dragleave", "drop"].forEach(type => {
            zone.addEventListener(type, event => {
                event.preventDefault();
                zone.classList.remove("is-dragging");
            });
        });

        zone.addEventListener("drop", event => {
            if (event.dataTransfer.files.length) addFiles(event.dataTransfer.files);
        });

        grid.querySelectorAll(".is-saved img").forEach(img => {
            img.addEventListener("click", () => openLightbox(img.src, img.alt));
        });

        lightbox.querySelector(".photo-lightbox-close").addEventListener("click", () => lightbox.close());
        lightbox.addEventListener("click", event => {
            if (event.target === lightbox) lightbox.close();
        });

        // Clear stored photos once the form is really submitted
        document.addEventListener("wizard:clear", () => clearPhotos(draftKey).catch(() => {}));


        // ---------- public API (used by review.js) ----------

        root.photoUpload = {
            items: () => files.map(item => ({ url: item.url, name: item.file.name })),
            open: openLightbox,
        };


        // ---------- restore after refresh ----------

        render();

        if (sessionStorage.getItem(draftKey)) {
            loadPhotos(draftKey)
                .then(saved => { if (saved && saved.length) addFiles(saved); })
                .catch(() => {});
        } else {
            // New visit (no draft in this tab): don't bring back old photos
            clearPhotos(draftKey).catch(() => {});
        }
    }


    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("[data-photo-upload]").forEach(initPhotoUpload);
    });

})();