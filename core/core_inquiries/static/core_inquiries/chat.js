// handles inquiries and chat logic for both renters and landlords. This is a separate file from inquiries.js because it is used in the pop-up modals as well as the Inquiries tab.

(function () {

    const MAX_FILE_MB = 5;
    const FILE_TYPES = {
        image: { mime: ["image/jpeg", "image/png"], ext: /\.(jpe?g|png)$/i },
        video: { mime: ["video/mp4", "video/webm", "video/quicktime"], ext: /\.(mp4|webm|mov)$/i },
        pdf:   { mime: ["application/pdf"], ext: /\.pdf$/i },
    };
    const THREAD_REFRESH_MS = 4000;

    const ICONS = {
        sent: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>',
        seen: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m2 12.5 4.5 4.5L16 7.5M10 16l1 1 9.5-9.5"/></svg>',
        pdf:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5M9 13h6M9 17h4"/></svg>',
        megaphone: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 11v2a1 1 0 0 0 1 1h2l5 4V6L6 10H4a1 1 0 0 0-1 1Z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 6a8.5 8.5 0 0 1 0 12"/></svg>',
        calendar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="5" width="16" height="16" rx="2"/><path d="M8 3v4M16 3v4M4 10h16"/></svg>',
    };

    function csrfToken() {
        const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    // Fill an avatar spot: the person's profile photo, or their initials.
    // role (landlord / renter) gives the blue / yellow colour, or the ring around a photo.
    function setAvatar(target, url, initials, role) {
        target.classList.remove("avatar--landlord", "avatar--renter");
        if (role === "landlord" || role === "renter") target.classList.add(`avatar--${role}`);
        target.replaceChildren();
        if (url) target.append(Object.assign(el("img"), { src: url, alt: "" }));
        else target.textContent = initials || "";
    }


    // ---------------------------------------------------------
    // Rendering
    // ---------------------------------------------------------

    function renderAttachment(file) {
        if (file.kind === "image") {
            const link = el("a", "chat-attachment chat-attachment--image");
            link.href = file.url;
            link.target = "_blank";
            link.rel = "noopener";
            const img = el("img");
            img.src = file.url;
            img.alt = file.name;
            img.loading = "lazy";
            link.append(img);
            return link;
        }
        if (file.kind === "video") {
            const video = el("video", "chat-attachment chat-attachment--video");
            video.src = file.url;
            video.controls = true;
            video.preload = "metadata";
            return video;
        }
        const link = el("a", "chat-attachment chat-attachment--file");
        link.href = file.url;
        link.target = "_blank";
        link.rel = "noopener";
        link.innerHTML = ICONS.pdf;
        const text = el("span");
        text.append(el("strong", "", file.name), el("small", "", `PDF · ${file.size_label}`));
        link.append(text);
        return link;
    }

    // Post on Bulletin: a yellow announcement banner in the middle of the chat, not a bubble
    function renderBulletin(message) {
        const banner = el("div", "chat-bulletin");
        banner.dataset.messageId = message.id;

        const head = el("div", "chat-bulletin-head");
        head.innerHTML = ICONS.megaphone;
        head.append(el("span", "", "Bulletin Announcement"));
        banner.append(head);

        if (message.body) banner.append(el("p", "chat-bulletin-text", message.body));
        if (message.bulletin_event) {
            const event = el("div", "chat-bulletin-event");
            event.innerHTML = ICONS.calendar;
            event.append(el("span", "", message.bulletin_event));
            banner.append(event);
        }

        const time = el("time", "chat-bulletin-time", message.time_label);
        time.dateTime = message.created_at;
        banner.append(time);
        return banner;
    }

    function renderMessage(message) {
        if (message.kind === "bulletin") return renderBulletin(message);

        const fragment = document.createDocumentFragment();

        // "About Unit 401 · Sunrise Residences" when the renter changes topic
        if (message.topic) {
            const topic = el("div", "chat-topic");
            topic.append(el("span", "", `About ${message.topic}`));
            fragment.append(topic);
        }

        const item = el("div", `chat-message ${message.mine ? "sent" : "received"}`);
        item.dataset.messageId = message.id;

        const bubble = el("div", "chat-bubble");
        if (message.attachment) {
            bubble.classList.add("has-attachment");
            bubble.append(renderAttachment(message.attachment));
        }
        if (message.body) bubble.append(el("p", "chat-text", message.body));

        const meta = el("div", "chat-meta");
        const time = el("time", "chat-time", message.time_label);
        time.dateTime = message.created_at;
        meta.append(time);
        if (message.mine) {
            const tick = el("span", "chat-tick");
            meta.append(tick);
            setTick(tick, message.seen, message.seen_label);
        }

        item.append(bubble, meta);
        fragment.append(item);
        return fragment;
    }

    function setTick(tick, seen, label) {
        tick.classList.toggle("is-seen", Boolean(seen));
        tick.innerHTML = seen ? ICONS.seen : ICONS.sent;
        tick.title = seen ? `Seen ${label}` : "Sent";
        tick.setAttribute("aria-label", tick.title);
    }

    // ✓✓ on every seen message; "Seen 10:32 PM" under the latest one only
    function applySeen(box, seen) {
        const mine = [...box.querySelectorAll(".chat-message.sent")];
        let lastSeen = null;
        mine.forEach(item => {
            const label = seen[item.dataset.messageId];
            if (label) {
                setTick(item.querySelector(".chat-tick"), true, label);
                lastSeen = item;
            }
        });
        box.querySelectorAll(".chat-seen").forEach(node => node.remove());
        if (lastSeen) {
            lastSeen.querySelector(".chat-meta").append(el("span", "chat-seen", `Seen ${seen[lastSeen.dataset.messageId]}`));
        }
    }


    // ---------------------------------------------------------
    // Sending (JSON, or multipart when there's a file)
    // ---------------------------------------------------------

    async function send(url, fields, file) {
        let options;
        if (file) {
            const form = new FormData();
            Object.entries(fields).forEach(([key, value]) => form.append(key, value ?? ""));
            form.append("attachment", file);
            options = { body: form, headers: { "X-CSRFToken": csrfToken(), "Accept": "application/json" } };
        } else {
            options = {
                body: JSON.stringify(fields),
                headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken(), "Accept": "application/json" },
            };
        }

        const response = await fetch(url, { method: "POST", credentials: "same-origin", ...options });
        const data = await response.json().catch(() => ({}));
        if (response.status === 403 && !data.errors) {
            data.errors = { __all__: "Your session changed (you may have logged out or switched accounts in another tab). Refresh the page and try again." };
        }
        if (response.status === 413) {
            data.errors = { attachment: `Files can be up to ${MAX_FILE_MB} MB.` };
        }
        return { ok: response.ok, status: response.status, data };
    }

    function firstError(data, fallback) {
        return Object.values(data.errors || {})[0] || fallback;
    }


    // ---------------------------------------------------------
    // File picker (paperclip button + preview chip)
    // root must contain [data-attach-button], input[data-attach-input], [data-attach-preview]
    // ---------------------------------------------------------

    function fileKind(file) {
        return Object.keys(FILE_TYPES).find(kind =>
            FILE_TYPES[kind].mime.includes(file.type) || FILE_TYPES[kind].ext.test(file.name)) || null;
    }

    function sizeLabel(size) {
        return size >= 1024 * 1024 ? `${(size / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(size / 1024))} KB`;
    }

    function attachPicker(root, onError) {
        const button = root.querySelector("[data-attach-button]");
        const input = root.querySelector("[data-attach-input]");
        const preview = root.querySelector("[data-attach-preview]");
        let file = null;

        function clear() {
            file = null;
            input.value = "";
            preview.hidden = true;
            preview.replaceChildren();
        }

        button.addEventListener("click", () => input.click());
        input.addEventListener("change", () => {
            const picked = input.files[0];
            if (!picked) return;
            if (!fileKind(picked)) {
                clear();
                return onError("You can send photos (JPG, PNG), videos (MP4, WebM, MOV) or PDF files.");
            }
            if (picked.size > MAX_FILE_MB * 1024 * 1024) {
                clear();
                return onError(`Files can be up to ${MAX_FILE_MB} MB (${picked.name} is ${sizeLabel(picked.size)}).`);
            }
            file = picked;
            onError("");
            preview.replaceChildren(
                el("span", "chat-chip-name", picked.name),
                el("small", "", sizeLabel(picked.size)),
            );
            const remove = el("button", "chat-chip-remove", "×");
            remove.type = "button";
            remove.setAttribute("aria-label", "Remove file");
            remove.addEventListener("click", clear);
            preview.append(remove);
            preview.hidden = false;
        });

        return { file: () => file, clear };
    }


    // ---------------------------------------------------------
    // An open thread: first load + refresh every 4 seconds
    // ---------------------------------------------------------

    class Thread {
        constructor(box, { emptyNode, onLoad } = {}) {
            this.box = box;
            this.emptyNode = emptyNode;     // () => Node shown when there are no messages
            this.onLoad = onLoad;           // (conversation) => void
            this.url = null;
            this.lastId = 0;
            this.ids = new Set();
            this.timer = null;
        }

        showEmpty() {
            this.box.replaceChildren(this.emptyNode ? this.emptyNode() : el("div", "conversation-empty", "No messages yet."));
        }

        add(messages) {
            const fresh = messages.filter(m => !this.ids.has(m.id));
            if (!fresh.length) return;
            const atBottom = this.box.scrollHeight - this.box.scrollTop - this.box.clientHeight < 80;
            if (!this.ids.size) this.box.replaceChildren();   // drop the empty state

            fresh.forEach(message => {
                this.ids.add(message.id);
                this.lastId = Math.max(this.lastId, message.id);
                this.box.append(renderMessage(message));
            });
            // Follow new messages unless the user scrolled up to read older ones
            if (atBottom || fresh.some(m => m.mine)) this.box.scrollTop = this.box.scrollHeight;
        }

        async open(url) {
            this.stop();
            this.url = url;
            this.lastId = 0;
            this.ids.clear();
            const conversation = await this.fetch();
            if (!conversation) return null;
            if (!conversation.messages.length) this.showEmpty();
            this.add(conversation.messages);
            applySeen(this.box, conversation.seen);
            this.box.scrollTop = this.box.scrollHeight;
            this.onLoad?.(conversation);
            this.start();
            return conversation;
        }

        // A thread created by the first message (pop-up): start refreshing it
        follow(url) {
            this.url = url;
            this.start();
        }

        async fetch(after) {
            const params = new URLSearchParams();
            if (after) params.set("after", after);
            if (document.hidden) params.set("seen", "0");   // background tab: don't mark as seen
            const response = await fetch(`${this.url}?${params}`, { headers: { Accept: "application/json" }, credentials: "same-origin" });
            if (!response.ok) return null;
            return (await response.json()).conversation;
        }

        async refresh() {
            if (!this.url || document.hidden) return;
            try {
                const conversation = await this.fetch(this.lastId);
                if (!conversation) return;
                this.add(conversation.messages);
                applySeen(this.box, conversation.seen);
            } catch (error) {
                /* offline for a moment: try again next tick */
            }
        }

        start() {
            this.stop();
            this.timer = setInterval(() => this.refresh(), THREAD_REFRESH_MS);
        }

        stop() {
            clearInterval(this.timer);
            this.timer = null;
        }
    }

    // Coming back to the tab: refresh right away instead of waiting
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) window.LookAptChat.threads.forEach(thread => thread.timer && thread.refresh());
    });

    window.LookAptChat = {
        threads: [],
        Thread: class extends Thread {
            constructor(...args) {
                super(...args);
                window.LookAptChat.threads.push(this);
            }
        },
        renderMessage,
        applySeen,
        send,
        firstError,
        attachPicker,
        csrfToken,
        el,
        setAvatar,
    };

})();