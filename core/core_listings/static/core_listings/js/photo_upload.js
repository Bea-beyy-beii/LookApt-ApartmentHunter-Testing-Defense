// =========================================================
// STEP 2/3 — PHOTO (+ VIDEO) UPLOAD
// Left: drop zone (click or drag & drop). Right: previews.
// - Photos and videos go into separate hidden inputs ("photos" / "videos")
// - Saved photos (editing) and new ones are one list: remove any of them, move
//   photos with ◀ ▶ (phones) or drag one onto another (mouse); photo 1 = cover
// - The order goes to the server in "photo_order" (s:<saved id> / n:<new upload>);
//   saved photos left out are deleted on Save. Removed saved videos: "remove_videos"
// - New files survive a page refresh (stored in IndexedDB)
// =========================================================

(function () {

    const KINDS = {
        image: { types: ["image/png", "image/jpeg"], ext: /\.(png|jpe?g)$/i, maxMb: 5 },
        video: { types: ["video/mp4", "video/webm", "video/quicktime"], ext: /\.(mp4|webm|mov)$/i, maxMb: 50 },
    };


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

    const saveDraftFiles = (key, fileList) => withStore("readwrite", store => store.put(fileList, key));
    const loadDraftFiles = key => withStore("readonly", store => store.get(key));
    const clearDraftFiles = key => withStore("readwrite", store => store.delete(key));


    function initPhotoUpload(root) {
        const maxPhotos = Number(root.dataset.max) || 5;
        const allowVideo = root.dataset.allowVideo === "1";
        const maxVideos = allowVideo ? Number(root.dataset.maxVideos) || 0 : 0;

        const form = root.closest("form");
        const draftKey = "lookapt:wizard:" + (form ? form.getAttribute("action") : location.pathname);

        const picker = root.querySelector("[data-media-picker]");
        const photoInput = root.querySelector('input[type="file"][name="photos"]');
        const videoInput = root.querySelector('input[type="file"][name="videos"]');
        const orderInput = root.querySelector("[data-photo-order]");
        const removedVideosInput = root.querySelector("[data-remove-videos]");
        const zone = root.querySelector(".photo-dropzone");
        const grid = root.querySelector(".photo-preview-grid");
        const counter = root.querySelector(".photo-count");
        const errorBox = root.querySelector(".photo-upload-error");
        const lightbox = root.querySelector(".photo-lightbox");
        const lightboxImg = lightbox.querySelector("img");
        const lightboxVideo = lightbox.querySelector("video");

        // Move the lightbox to <body>: inside a hidden wizard step it can't be seen,
        // but showModal() would still block the whole page.
        document.body.append(lightbox);

        // Saved: { savedId, url, name, kind }   New: { file, url, name, kind }
        let files = [...grid.querySelectorAll(".photo-tile.is-saved")].map(tile => {
            const media = tile.querySelector("img, video");
            return {
                savedId: tile.dataset.savedId,
                url: media.getAttribute("src"),
                name: media.getAttribute("alt") || "Saved video",
                kind: media.tagName === "VIDEO" ? "video" : "image",
            };
        });
        const removedVideos = new Set();
        let dragFrom = null;

        const ofKind = kind => files.filter(item => item.kind === kind);
        const newOfKind = kind => ofKind(kind).filter(item => item.file);
        const photoTotal = () => ofKind("image").length;
        const videoTotal = () => ofKind("video").length;
        const isFull = () => photoTotal() >= maxPhotos && (!allowVideo || videoTotal() >= maxVideos);


        // ---------- helpers ----------

        function showError(message) {
            errorBox.textContent = message;
            errorBox.hidden = !message;
        }

        function kindOf(file) {
            for (const [kind, rule] of Object.entries(KINDS)) {
                if (kind === "video" && !allowVideo) continue;
                if (rule.types.includes(file.type) && rule.ext.test(file.name)) return kind;
            }
            return null;
        }

        // Copy our list back into the real inputs so the form submits the new files (in order),
        // the photo order ("s:12,n:0,...": saved photo 12, then the first new upload ...)
        // and the saved videos to delete
        function syncInputs() {
            const fill = (input, kind) => {
                if (!input) return;
                const transfer = new DataTransfer();
                newOfKind(kind).forEach(item => transfer.items.add(item.file));
                input.files = transfer.files;
            };
            fill(photoInput, "image");
            fill(videoInput, "video");

            let next = 0;
            if (orderInput) {
                orderInput.value = ofKind("image")
                    .map(item => item.savedId ? `s:${item.savedId}` : `n:${next++}`)
                    .join(",");
            }
            if (removedVideosInput) removedVideosInput.value = [...removedVideos].join(",");
        }

        function openLightbox(src, alt, kind = "image") {
            const isVideo = kind === "video";
            lightboxImg.hidden = isVideo;
            if (lightboxVideo) lightboxVideo.hidden = !isVideo;

            if (isVideo && lightboxVideo) {
                lightboxVideo.src = src;
            } else {
                lightboxImg.src = src;
                lightboxImg.alt = alt || "";
            }
            lightbox.showModal();
        }

        function changed() {
            saveDraftFiles(draftKey, files.filter(item => item.file).map(item => item.file)).catch(() => {});
            root.dispatchEvent(new CustomEvent("photos:change", { bubbles: true }));
        }


        // ---------- add / remove / swap ----------

        function addFiles(fileList) {
            const errors = [];

            for (const file of fileList) {
                const kind = kindOf(file);

                if (!kind) {
                    errors.push(allowVideo
                        ? `${file.name}: only PNG/JPG photos or MP4/WebM/MOV videos are allowed.`
                        : `${file.name}: only PNG or JPG files are allowed.`);
                    continue;
                }
                if (file.size > KINDS[kind].maxMb * 1024 * 1024) {
                    errors.push(`${file.name} is larger than ${KINDS[kind].maxMb} MB.`);
                    continue;
                }
                if (kind === "image" && photoTotal() >= maxPhotos) {
                    errors.push(`You can only upload ${maxPhotos} photos.`);
                    continue;
                }
                if (kind === "video" && videoTotal() >= maxVideos) {
                    errors.push(`You can only upload ${maxVideos} video${maxVideos === 1 ? "" : "s"}.`);
                    continue;
                }
                const duplicate = files.some(item => item.file && item.file.name === file.name && item.file.size === file.size);
                if (duplicate) continue;

                files.push({ file, kind, name: file.name, url: URL.createObjectURL(file) });
            }

            showError([...new Set(errors)].join(" "));
            syncInputs();
            render();
            changed();
        }

        function removeFile(index) {
            const item = files[index];
            if (item.file) URL.revokeObjectURL(item.url);
            else if (item.kind === "video") removedVideos.add(item.savedId);
            // (a saved photo left out of photo_order is deleted when the form is saved)
            files.splice(index, 1);
            showError("");
            syncInputs();
            render();
            changed();
        }

        // Photos with photos; videos only among new ones (saved videos keep their order)
        function canSwap(a, b) {
            const one = files[a], other = files[b];
            return a !== b && one.kind === other.kind && (one.kind === "image" || (one.file && other.file));
        }

        function swapFiles(a, b) {
            if (!canSwap(a, b)) return;
            [files[a], files[b]] = [files[b], files[a]];
            syncInputs();
            render();
            changed();
        }

        // ◀ ▶ buttons: swap with the photo before / after this one
        function movePhoto(index, step) {
            const photos = [...files.keys()].filter(i => files[i].kind === "image");
            const neighbour = photos[photos.indexOf(index) + step];
            if (neighbour !== undefined) swapFiles(index, neighbour);
        }


        // ---------- render previews ----------

        function makeDraggable(tile, index) {
            tile.draggable = true;

            tile.addEventListener("dragstart", event => {
                dragFrom = index;
                tile.classList.add("is-dragging");
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", String(index));
            });

            tile.addEventListener("dragend", () => {
                dragFrom = null;
                grid.querySelectorAll(".is-dragging, .is-drop-target")
                    .forEach(el => el.classList.remove("is-dragging", "is-drop-target"));
            });

            tile.addEventListener("dragover", event => {
                if (dragFrom === null || !canSwap(dragFrom, index)) return;
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

        function moveButton(label, symbol, onClick, disabled) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "photo-move";
            button.textContent = symbol;
            button.setAttribute("aria-label", label);
            button.disabled = disabled;
            button.addEventListener("click", onClick);
            return button;
        }

        function buildTile(item, index, isCover, photoNumber, photoCount) {
            const tile = document.createElement("div");
            tile.className = "photo-tile is-new" + (item.savedId ? " is-kept" : "") + (item.kind === "video" ? " is-video" : "");

            let media;
            if (item.kind === "video") {
                media = document.createElement("video");
                media.src = item.url;
                media.muted = true;
                media.playsInline = true;
                media.preload = "metadata";
            } else {
                media = document.createElement("img");
                media.src = item.url;
                media.alt = item.name;
            }
            media.draggable = false;
            media.addEventListener("click", () => openLightbox(item.url, item.name, item.kind));

            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "photo-remove";
            remove.textContent = "×";
            remove.setAttribute("aria-label", `Remove ${item.name}`);
            remove.addEventListener("click", () => removeFile(index));

            tile.append(media, remove);

            if (item.kind === "image" && photoCount > 1) {
                const moves = document.createElement("div");
                moves.className = "photo-moves";
                moves.append(
                    moveButton("Move photo left", "◀", () => movePhoto(index, -1), photoNumber === 0),
                    moveButton("Move photo right", "▶", () => movePhoto(index, 1), photoNumber === photoCount - 1),
                );
                tile.append(moves);
            }

            if (item.kind === "video") {
                const badge = document.createElement("span");
                badge.className = "photo-video-badge";
                badge.textContent = "▶ Video";
                tile.append(badge);
            }

            if (isCover) {
                const badge = document.createElement("span");
                badge.className = "photo-cover-badge";
                badge.textContent = "Cover";
                tile.append(badge);
            }

            if (item.kind === "image" || item.file) makeDraggable(tile, index);
            return tile;
        }

        function render() {
            grid.querySelectorAll(".is-new, .is-saved, .is-empty").forEach(tile => tile.remove());

            // Photos first, then videos (keeps each group's own order)
            const order = [...files.keys()].sort(
                (a, b) => (files[a].kind === "video") - (files[b].kind === "video")
            );

            const photoCount = photoTotal();
            let photoNumber = 0;
            order.forEach(index => {
                const item = files[index];
                const isPhoto = item.kind === "image";
                grid.append(buildTile(item, index, isPhoto && photoNumber === 0, photoNumber, photoCount));
                if (isPhoto) photoNumber++;
            });

            for (let i = photoTotal(); i < maxPhotos; i++) {
                const empty = document.createElement("div");
                empty.className = "photo-tile is-empty";
                grid.append(empty);
            }

            counter.textContent = allowVideo
                ? `(${photoTotal()}/${maxPhotos} photos · ${videoTotal()}/${maxVideos} videos)`
                : `(${photoTotal()}/${maxPhotos})`;
            zone.classList.toggle("is-full", isFull());
            // Saved + new photos (videos don't count): the wizard needs at least data-min of them (listings.js)
            root.dataset.total = String(photoTotal());
            if (Number(root.dataset.total) >= Number(root.dataset.min || 0)) showError("");
        }


        // ---------- events ----------

        picker.addEventListener("change", () => {
            addFiles([...picker.files]);
            picker.value = "";   // allow picking the same file again after removing it
        });

        zone.addEventListener("click", event => {
            if (isFull()) {
                event.preventDefault();
                showError("You've reached the upload limit. Remove a file to add another.");
            }
        });

        zone.addEventListener("keydown", event => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                event.stopPropagation();   // don't trigger the wizard's Enter = Next
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

        lightbox.querySelector(".photo-lightbox-close").addEventListener("click", () => lightbox.close());
        lightbox.addEventListener("click", event => {
            if (event.target === lightbox) lightbox.close();
        });
        lightbox.addEventListener("close", () => { if (lightboxVideo) lightboxVideo.pause(); });

        document.addEventListener("wizard:clear", () => clearDraftFiles(draftKey).catch(() => {}));


        // ---------- public API (used by review.js) ----------

        root.photoUpload = {
            items: () => [...ofKind("image"), ...ofKind("video")]       // saved + new, in order
                .map(item => ({ url: item.url, name: item.name, kind: item.kind })),
            open: openLightbox,
        };


        // ---------- restore after refresh ----------

        syncInputs();
        render();

        if (sessionStorage.getItem(draftKey)) {
            loadDraftFiles(draftKey)
                .then(saved => { if (saved && saved.length) addFiles(saved); })
                .catch(() => {});
        } else {
            clearDraftFiles(draftKey).catch(() => {});
        }
    }


    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("[data-photo-upload]").forEach(initPhotoUpload);
    });

})();