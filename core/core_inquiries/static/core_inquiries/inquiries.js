// =========================================================
// INQUIRIES TAB (renter + landlord dashboards)
// - Messages / Pending Requests / Waitlist / Archive (+ Reviews for landlords) tabs
// - thread list refreshes every 8 s (newest conversation on top)
// - search the thread list by person or property name
// - an open thread refreshes every 4 s (chat.js), with ✓✓ seen
// - replies with text and/or a file
// =========================================================

document.addEventListener("DOMContentLoaded", () => {
  // Tab switching (Messages / Pending Requests / Waitlist / Archive / Reviews).
  const tabs = document.querySelectorAll(".inquiry-tab");
  const panels = document.querySelectorAll(".inquiry-tabpanel");

  function showTab(tab) {
    tabs.forEach((t) => t.classList.toggle("active", t === tab));
    panels.forEach((p) => {
      p.hidden = p.id !== `tab-${tab.dataset.tab}`;
    });
  }
  tabs.forEach((tab) => tab.addEventListener("click", () => showTab(tab)));

  // Back on the same sub-tab after a request action reloaded the page (requests.js)
  try {
    const saved = sessionStorage.getItem("lookapt:inquiries:tab");
    if (saved) {
      sessionStorage.removeItem("lookapt:inquiries:tab");
      const tab = document.querySelector(`.inquiry-tab[data-tab="${saved}"]`);
      if (tab) showTab(tab);
    }
  } catch (err) { /* ignore */ }

  // Reviews (landlords): show one complex's reviews
  const reviewFilter = document.querySelector("[data-review-filter]");
  reviewFilter?.addEventListener("change", () => {
    document.querySelectorAll("[data-review-complex]").forEach((item) => {
      item.hidden = Boolean(reviewFilter.value) && item.dataset.reviewComplex !== reviewFilter.value;
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

  // Search: matches the other person's name and the property / unit
  const search = document.querySelector("[data-thread-search]");
  const searchWrap = document.querySelector("[data-thread-search-wrap]");
  const searchEmpty = document.querySelector("[data-thread-search-empty]");

  function applySearch() {
    if (!search) return;
    const query = search.value.trim().toLowerCase();
    const buttons = [...threadList.querySelectorAll('[data-action="open-conversation"]')];
    let shown = 0;
    buttons.forEach((btn) => {
      const show = !query || (btn.dataset.search || btn.textContent).toLowerCase().includes(query);
      btn.hidden = !show;
      if (show) shown++;
    });
    searchEmpty.hidden = !(query && buttons.length && !shown);
  }
  search?.addEventListener("input", applySearch);

  function showList(show) {
    threadList.hidden = !show;
    convo.hidden = show;
    if (searchWrap) searchWrap.hidden = !show;
    if (searchEmpty && !show) searchEmpty.hidden = true;
    if (show) applySearch();
  }

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
    Chat.setAvatar(convo.querySelector("[data-conversation-avatar]"), btn.dataset.avatar, btn.dataset.initials, btn.dataset.role);
    convo.querySelector("[data-conversation-status]").textContent = btn.querySelector(".thread-subject")?.textContent.trim() || "";
    replyUrl = btn.dataset.replyUrl;
    showError("");
    picker.clear();
    showList(false);
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
    showList(true);
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
    btn.dataset.search = `${item.other_name} ${item.subject}`;
    btn.dataset.initials = item.other_initials || "U";
    btn.dataset.avatar = item.other_avatar || "";
    btn.dataset.role = item.other_role || "";

    const avatar = Chat.el("span", "thread-avatar");
    if (item.other_avatar) Chat.setAvatar(avatar, item.other_avatar, "", item.other_role);
    else {
        avatar.classList.add(`avatar--${item.other_role}`);
        avatar.append(Chat.el("span", "thread-avatar-fallback", item.other_initials || "U"));
    }

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
      applySearch();      // keep the search applied after a refresh
    } catch (err) {
      /* try again next time */
    }
  }

  setInterval(refreshInbox, INBOX_REFRESH_MS);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshInbox(); });
});