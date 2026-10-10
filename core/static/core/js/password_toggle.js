// Show / hide password: every [data-toggle-password] button next to a password input
// (login page; sign-up has the same code in signup.js)
document.querySelectorAll("[data-toggle-password]").forEach(toggle => {
    toggle.addEventListener("click", () => {
        const input = toggle.parentElement.querySelector("input");
        const showing = input.type === "password";

        input.type = showing ? "text" : "password";

        toggle.setAttribute("aria-pressed", String(showing));
        toggle.setAttribute("aria-label", showing ? "Hide password" : "Show password");
    });
});