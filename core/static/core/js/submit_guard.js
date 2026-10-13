// =========================================================
// One submit per click (all pages)
// Forms that reload the page (log in, sign up, the property / unit forms,
// admin actions ...): after the first submit, their submit buttons show the
// "not allowed" cursor and a second submit is ignored. Forms that are sent
// with fetch() (pop-ups) call preventDefault() and disable their own button,
// so they are left alone here (forms.css gives those buttons the same cursor).
// =========================================================

(function () {

    const UNLOCK_AFTER_MS = 20000;   // in case the page never changes (e.g. the server is down)

    function lock(form, locked) {
        form.classList.toggle("is-submitting", locked);
        form.querySelectorAll("button[type=submit], button:not([type]), input[type=submit]").forEach(button => {
            if (locked) button.setAttribute("aria-disabled", "true");
            else button.removeAttribute("aria-disabled");
        });
        if (!locked) delete form.dataset.submitting;
    }

    // Bubble phase: runs after the page's own submit handlers, so a submit
    // they stopped (invalid form, fetch) is never locked
    document.addEventListener("submit", event => {
        const form = event.target;
        if (event.defaultPrevented || (form.method || "get").toLowerCase() !== "post") return;

        if (form.dataset.submitting) {
            event.preventDefault();      // already on its way
            return;
        }
        // Not "disabled": a disabled submit button would drop its name/value
        // (e.g. visibility="active") from what is sent
        form.dataset.submitting = "1";
        lock(form, true);
        setTimeout(() => lock(form, false), UNLOCK_AFTER_MS);
    });

    // Back button: the browser may show the page as it was, still locked
    window.addEventListener("pageshow", event => {
        if (event.persisted) document.querySelectorAll("form.is-submitting").forEach(form => lock(form, false));
    });

})();