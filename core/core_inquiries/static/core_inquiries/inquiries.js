// =========================================================
// INQUIRIES TAB (renter + landlord dashboards)
// - Messages / Requests tabs
// - thread list refreshes every 8 s (newest conversation on top)
// - an open thread refreshes every 4 s (chat.js), with ✓✓ seen
// - replies with text and/or a file
// =========================================================

document.addEventListener("DOMContentLoaded", () => {
  // Tab switching (Messages / Requests)
  const tabs = document.querySelectorAll(".inquiry-tab");
  const panels = document.querySelectorAll(".inquiry-tabpanel");

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.toggle("active", t === tab));
      panels.forEach((p) => {
        p.hidden = p.id !== `tab-${tab.dataset.tab}`;
      });
    });
  });

  const threadList = document.getElementById("messages-view");
  const convo = document.getElementById("conversation-view");
  const Chat = window.LookAptChat;
  if (!threadList || !convo || !Chat) return;

  const INBOX_REFRESH_MS = 8000;
  const box = convo.querySelector("[data-conversation-messages]");
  const form = convo.querySelector("[data-message-form]");
  const input = convo.querySelector("[data-message-input]");
  const send = convo.querySelector("[data-message-send]");
  const attachButton = convo.querySelector("[data-attach-button]");
  const locked = convo.querySelector("[data-conversation-locked]");
  const error = convo.querySelector("[data-message-error]");
  let replyUrl = null;
  let openId = null;

  function showError(message) {
    error.textContent = message;
    error.hidden = !message;
  }

  const picker = Chat.attachPicker(form, showError);
  const thread = new Chat.Thread(box, {
    onLoad(conversation) {
      // What the renter asked about most recently
      convo.querySelector("[data-conversation-status]").textContent = conversation.subject;
      // Landlords can't write first (the server checks this too)
      locked.hidden = conversation.can_send;
      input.disabled = send.disabled = attachButton.disabled = !conversation.can_send;
      if (conversation.can_send) input.focus();
    },
  });


  // ---------------------------------------------------------
  // Open / close a thread
  // ---------------------------------------------------------

  async function openThread(btn) {
    openId = btn.dataset.conversationId;
    convo.querySelector("[data-conversation-name]").textContent = btn.querySelector(".thread-name").textContent.trim();
    convo.querySelector("[data-conversation-initials]").textContent = btn.querySelector(".thread-avatar-fallback").textContent.trim();
    convo.querySelector("[data-conversation-status]").textContent = btn.querySelector(".thread-subject")?.textContent.trim() || "";
    replyUrl = btn.dataset.replyUrl;
    showError("");
    picker.clear();
    threadList.hidden = true;
    convo.hidden = false;
    box.replaceChildren(Chat.el("div", "conversation-empty", "Loading…"));

    try {
      const conversation = await thread.open(btn.dataset.url);
      if (!conversation) box.replaceChildren(Chat.el("div", "conversation-empty", "Couldn't load this conversation."));
      // Opening a thread marks it as read
      btn.classList.remove("unread");
      btn.querySelector(".thread-unread")?.remove();
      refreshInbox();
    } catch (err) {
      box.replaceChildren(Chat.el("div", "conversation-empty", "Couldn't load this conversation. Please try again."));
    }
  }

  threadList.addEventListener("click", (event) => {
    const btn = event.target.closest('[data-action="open-conversation"]');
    if (btn) openThread(btn);
  });

  convo.querySelector('[data-action="back-to-threads"]').addEventListener("click", () => {
    thread.stop();
    openId = null;
    convo.hidden = true;
    threadList.hidden = false;
    refreshInbox();
  });


  // ---------------------------------------------------------
  // Reply (text and/or file)
  // ---------------------------------------------------------

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = input.value.trim();
    const file = picker.file();
    if ((!body && !file) || !replyUrl) return;

    send.disabled = true;
    showError("");
    try {
      const result = await Chat.send(replyUrl, { body }, file);
      if (!result.ok) return showError(Chat.firstError(result.data, "Couldn't send the message."));
      thread.add([result.data.message]);
      input.value = "";
      picker.clear();
    } catch (err) {
      showError("Couldn't reach the server. Please try again.");
    } finally {
      send.disabled = input.disabled;
      input.focus();
    }
  });


  // ---------------------------------------------------------
  // Thread list: live refresh, newest conversation on top
  // ---------------------------------------------------------

  function threadButton(item) {
    const btn = Chat.el("button", `message-thread${item.unread && item.id !== openId ? " unread" : ""}`);
    btn.type = "button";
    btn.dataset.action = "open-conversation";
    btn.dataset.conversationId = item.id;
    btn.dataset.url = item.url;
    btn.dataset.replyUrl = item.reply_url;

    const avatar = Chat.el("span", "thread-avatar");
    avatar.append(Chat.el("span", "thread-avatar-fallback", item.other_initials || "U"));

    const details = Chat.el("span", "thread-details");
    const header = Chat.el("span", "thread-header");
    header.append(Chat.el("strong", "thread-name", item.other_name), Chat.el("time", "thread-time", item.time_label));
    details.append(header, Chat.el("span", "thread-subject", item.subject), Chat.el("span", "thread-preview", item.preview));

    btn.append(avatar, details);
    if (item.unread && item.id !== openId) {
      const dot = Chat.el("span", "thread-unread");
      dot.setAttribute("aria-label", `${item.unread} unread`);
      btn.append(dot);
    }
    return btn;
  }

  function setBadge(count) {
    const tab = document.querySelector('.inquiry-tab[data-tab="messages"]');
    if (!tab) return;
    let badge = tab.querySelector(".badge");
    if (!count) return badge?.remove();
    if (!badge) {
      badge = Chat.el("span", "badge");
      tab.append(" ", badge);
    }
    badge.textContent = count;
  }

  let lastInbox = "";

  async function refreshInbox() {
    if (document.hidden) return;
    try {
      const response = await fetch(threadList.dataset.inboxUrl, { headers: { Accept: "application/json" }, credentials: "same-origin" });
      if (!response.ok) return;
      const data = await response.json();

      setBadge(data.unread_messages_count);
      const snapshot = JSON.stringify(data.threads);
      if (snapshot === lastInbox || !data.threads.length) return;   // nothing new: leave the list alone
      lastInbox = snapshot;

      let list = threadList.querySelector(".thread-list");
      if (!list) {
        list = Chat.el("div", "thread-list");
        list.id = "thread-list";
        threadList.replaceChildren(list);   // replaces the "No messages yet" state
      }
      list.replaceChildren(...data.threads.map(threadButton));
    } catch (err) {
      /* try again next time */
    }
  }

  setInterval(refreshInbox, INBOX_REFRESH_MS);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshInbox(); });
});