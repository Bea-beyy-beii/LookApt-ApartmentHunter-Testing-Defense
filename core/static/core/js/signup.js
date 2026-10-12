// =========================================================
// SIGN UP: 5 steps on one page (Name · Contact · Profile · Security · Terms)
// - Next: the server checks the open step (signup/check/), then moves on
// - Back: goes to the previous step (no checks)
// - Terms (step 5): the "I agree" box unlocks once the text is scrolled to the end
// - Create Account (step 5) submits the whole form; the server checks
//   everything again and opens the OTP page
// Without JavaScript every step shows as one long form.
// =========================================================

(function () {

    const form = document.querySelector("[data-signup]");
    if (!form) return;

    const steps = [...form.querySelectorAll(".signup-step")];
    const stepperItems = [...document.querySelectorAll("[data-stepper-item]")];
    const last = steps.length;
    let current = Math.min(Math.max(parseInt(form.dataset.startStep, 10) || 1, 1), last);

    form.classList.add("is-js");


    // ---------------------------------------------------- showing a step

    function show(step) {
        current = step;
        steps.forEach(fieldset => {
            const active = Number(fieldset.dataset.step) === step;
            fieldset.classList.toggle("is-active", active);
            fieldset.setAttribute("aria-hidden", String(!active));
        });
        stepperItems.forEach(item => {
            const n = Number(item.dataset.stepperItem);
            item.classList.toggle("is-done", n < step);
            item.classList.toggle("is-active", n === step);
            if (n === step) item.setAttribute("aria-current", "step");
            else item.removeAttribute("aria-current");
        });
        const active = steps[step - 1];
        const target = active.querySelector(".has-error input, .has-error select")
            || active.querySelector("[data-legal-box], input, select");
        target?.focus({ preventScroll: true });
        if (active.contains(legalBox)) updateLegal();      // the box only has a size once it's visible
    }


    // ---------------------------------------------------- step 5: read to the end before agreeing

    const legalBox = form.querySelector("[data-legal-box]");
    const agree = form.elements.agree_terms;
    const legalHint = form.querySelector("[data-legal-hint]");
    const legalProgress = form.querySelector("[data-legal-progress]");
    let readToEnd = Boolean(agree?.checked);            // coming back with it already ticked

    function updateLegal() {
        if (!legalBox || !agree) return;
        const scrollable = legalBox.scrollHeight - legalBox.clientHeight;
        if (!readToEnd && legalBox.clientHeight && legalBox.scrollTop >= scrollable - 8) {
            readToEnd = true;
            setError("agree_terms", "");          // drop "read to the end first"
        }
        const share = readToEnd || scrollable <= 0 ? 1 : legalBox.scrollTop / scrollable;
        legalProgress.style.width = `${Math.round(share * 100)}%`;
        legalProgress.classList.toggle("is-done", readToEnd);
        agree.disabled = !readToEnd;
        legalHint.hidden = readToEnd;
    }

    if (legalBox && agree) {
        legalBox.addEventListener("scroll", updateLegal, { passive: true });
        window.addEventListener("resize", updateLegal);
        // Terms / Privacy shortcuts scroll inside the box
        form.querySelectorAll("[data-legal-jump]").forEach(button => button.addEventListener("click", () => {
            const section = document.getElementById(button.dataset.legalJump);
            legalBox.scrollTo({ top: section.offsetTop - legalBox.offsetTop, behavior: "smooth" });
        }));
        // Clicking the locked box: point at the hint
        form.querySelector("[data-legal-agree]").addEventListener("click", () => {
            if (!agree.disabled) return;
            legalHint.classList.remove("is-flashing");
            void legalHint.offsetWidth;
            legalHint.classList.add("is-flashing");
        });
        agree.disabled = !readToEnd;
        legalHint.hidden = readToEnd;
    }


    // ---------------------------------------------------- errors under the fields

    function setError(field, message) {
        const slot = form.querySelector(`[data-error-for="${field}"]`);
        if (!slot) return;
        slot.textContent = message || "";
        slot.closest(".form-group")?.classList.toggle("has-error", Boolean(message));
        const input = form.elements[field];
        if (input) input.setAttribute("aria-invalid", message ? "true" : "false");
    }

    function clearStepErrors(step) {
        steps[step - 1].querySelectorAll("[data-error-for]").forEach(slot => setError(slot.dataset.errorFor, ""));
    }

    // Typing in a field clears its message
    form.addEventListener("input", event => {
        if (event.target.name) setError(event.target.name, "");
    });
    form.addEventListener("change", event => {
        if (event.target.name) setError(event.target.name, "");
    });


    // ---------------------------------------------------- quick checks before asking the server

    function quickErrors(step) {
        const value = name => (form.elements[name]?.value || "").trim();
        const errors = {};
        if (step === 1) {
            if (!value("first_name")) errors.first_name = "First name is required.";
            if (!value("last_name")) errors.last_name = "Last name is required.";
        } else if (step === 2) {
            if (!/^09\d{9}$/.test(value("phone_number").replace(/[\s-]/g, ""))) errors.phone_number = "Enter an 11-digit number starting with 09.";
            if (!value("email")) errors.email = "Email is required.";
        } else if (step === 3) {
            if (!value("sex")) errors.sex = "Select your sex.";
            if (!value("role")) errors.role = "Select whether you're a renter or a landlord.";
        } else if (step === 4) {
            if (!form.elements.password.value) errors.password = "Password is required.";
            else if (form.elements.password.value !== form.elements.confirm_password.value) errors.confirm_password = "Passwords do not match.";
        } else if (step === 5) {
            if (!agree?.checked) errors.agree_terms = readToEnd
                ? "Please agree to the Terms and Conditions and the Privacy Notice."
                : "Please read the Terms and Privacy Notice to the end first.";
        }
        return errors;
    }

    async function checkStep(step) {
        clearStepErrors(step);
        let errors = quickErrors(step);

        if (!Object.keys(errors).length) {
            const data = new FormData(form);
            data.set("step", String(step));
            try {
                const response = await fetch(form.dataset.checkUrl, {
                    method: "POST",
                    body: data,
                    credentials: "same-origin",
                    headers: { Accept: "application/json" },
                });
                errors = (await response.json()).errors || {};
            } catch (error) {
                // Offline / server hiccup: let them continue, Create Account checks everything again
                errors = {};
            }
        }

        Object.entries(errors).forEach(([field, message]) => setError(field, message));
        return !Object.keys(errors).length;
    }


    // ---------------------------------------------------- buttons

    async function next(button) {
        if (button.disabled) return;
        button.disabled = true;
        button.classList.add("is-loading");
        const ok = await checkStep(current);
        button.disabled = false;
        button.classList.remove("is-loading");
        if (ok) show(current + 1);
        else show(current);            // focus the first field with an error
    }

    form.querySelectorAll("[data-next]").forEach(button => button.addEventListener("click", () => next(button)));
    form.querySelectorAll("[data-back]").forEach(button => button.addEventListener("click", () => show(current - 1)));

    // Enter = Next on steps 1–4; on step 5 it checks the step, then submits
    form.addEventListener("submit", async event => {
        if (form.dataset.submitting) return;
        event.preventDefault();
        if (current < last) {
            next(steps[current - 1].querySelector("[data-next]"));
            return;
        }
        const createButton = form.querySelector("[data-create]");
        createButton.disabled = true;
        const ok = await checkStep(last);
        createButton.disabled = false;
        if (!ok) return show(last);
        form.dataset.submitting = "1";
        createButton.disabled = true;
        createButton.textContent = "Creating account…";
        form.submit();
    });


    // ---------------------------------------------------- show / hide password

    form.querySelectorAll("[data-toggle-password]").forEach(toggle => toggle.addEventListener("click", () => {
        const input = toggle.parentElement.querySelector("input");
        const showing = input.type === "password";
        input.type = showing ? "text" : "password";
        toggle.setAttribute("aria-pressed", String(showing));
        toggle.setAttribute("aria-label", showing ? "Hide password" : "Show password");
    }));


    show(current);

})();