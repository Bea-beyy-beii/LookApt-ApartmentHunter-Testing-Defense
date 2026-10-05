// Logging in (or out and back in) gives the browser a new CSRF cookie.
// A page that was already open still has the OLD token in its forms, so
// submitting it gave "403 Forbidden". Copy the current cookie value into
// the form right before it is sent.
document.addEventListener("submit", event => {
    const input = event.target.querySelector("input[name=csrfmiddlewaretoken]");
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (input && match) input.value = decodeURIComponent(match[1]);
}, true);