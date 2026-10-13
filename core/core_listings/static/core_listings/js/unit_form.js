// =========================================================
// UNIT FORM — live area, payment upon rental, notes counter
// =========================================================

(function () {

    const peso = new Intl.NumberFormat("en-PH", {
        style: "currency", currency: "PHP", minimumFractionDigits: 2,
    });

    const months = n => `${n} month${n === 1 ? "" : "s"}`;

    document.addEventListener("DOMContentLoaded", () => {
        const form = document.querySelector(".unit-wizard-form");
        if (!form) return;

        const el = name => form.elements[name];
        const setText = (selector, text) =>
            form.querySelectorAll(selector).forEach(node => { node.textContent = text; });


        // ---------- Area ----------

        function updateArea() {
            const w = parseFloat(el("width_dimension").value);
            const l = parseFloat(el("length_dimension").value);
            el("area_display").value = w > 0 && l > 0
                ? `${Math.round(w * l * 100) / 100} sqm`
                : "— sqm";
        }


        // ---------- Payment upon rental ----------

        function updatePayment() {
            const rent = parseFloat(el("price").value) || 0;
            const advance = parseInt(el("advance_months").value, 10) || 0;
            const deposit = parseInt(el("deposit_months").value, 10) || 0;

            const advanceTotal = rent * advance;
            const depositTotal = rent * deposit;

            setText("[data-pay-advance]", peso.format(advanceTotal));
            setText("[data-pay-advance-months]", months(advance));
            setText("[data-pay-deposit]", peso.format(depositTotal));
            setText("[data-pay-deposit-months]", months(deposit));
            setText("[data-pay-total]", peso.format(advanceTotal + depositTotal));   // also fills the review step
        }


        // ---------- Notes counter ----------

        const notes = el("unit_description");
        const counter = form.querySelector("[data-char-count]");
        function updateCount() {
            if (notes && counter) counter.textContent = `${notes.value.length}/${notes.maxLength}`;
        }


        form.addEventListener("input", event => {
            const name = event.target.name;
            if (name === "width_dimension" || name === "length_dimension") updateArea();
            if (["price", "advance_months", "deposit_months"].includes(name)) updatePayment();
            if (name === "unit_description") updateCount();
        });

        // Run once on load (also covers values restored after a refresh)
        updateArea();
        updatePayment();
        updateCount();
    });

})();

// =========================================================
// BULK LISTING — "Add several units at once" (Add Unit page only)
// The switch shows one box per unit number; everything else in the form
// is shared. The numbers are sent as one hidden field, unit_numbers="101,102".
// =========================================================

(function () {

    document.addEventListener("DOMContentLoaded", () => {
        const form = document.querySelector(".unit-wizard-form");
        const toggle = form && form.querySelector("[data-bulk-toggle]");
        const panel = form && form.querySelector("[data-bulk-panel]");
        if (!toggle || !panel) return;

        const grid = panel.querySelector("[data-bulk-grid]");
        const hidden = panel.querySelector("[data-bulk-numbers]");
        const count = panel.querySelector("[data-bulk-count]");
        const identifier = form.elements.identifier;
        const MIN = 2;
        const MAX = Number(panel.dataset.max) || 20;
        const next = Number(panel.dataset.next) || 1;
        const singleMessages = form.dataset.savingMessages;

        // Start from what was typed before (draft / form sent back with errors) or next, next+1
        let numbers = (hidden.value || "").split(",").map(n => n.trim()).filter(Boolean);
        if (numbers.length < MIN) numbers = [String(next), String(next + 1)];

        function save() {
            hidden.value = numbers.join(",");
            hidden.dispatchEvent(new Event("input", { bubbles: true }));   // keeps the page's draft up to date
        }

        // The same number twice can't be sent
        function checkDuplicates() {
            const boxes = [...grid.querySelectorAll("input")];
            boxes.forEach(box => {
                const twice = box.value && boxes.filter(other => other.value === box.value).length > 1;
                box.setCustomValidity(twice ? "Each unit needs its own number." : "");
                box.closest(".bulk-unit").classList.toggle("is-duplicate", Boolean(twice));
            });
        }

        function render() {
            grid.replaceChildren(...numbers.map((value, index) => {
                const box = document.createElement("label");
                box.className = "bulk-unit form-group";     // form-group: same input look as the rest of the form
                const label = document.createElement("span");
                label.textContent = `Unit ${index + 1}`;
                const wrap = document.createElement("span");
                wrap.className = "affix-input";
                const prefix = document.createElement("span");
                prefix.className = "affix affix--prefix";
                prefix.textContent = "Unit";
                const input = document.createElement("input");
                input.type = "number";
                input.min = "1";
                input.required = true;
                input.value = value;
                input.setAttribute("aria-label", `Number of unit ${index + 1}`);
                input.addEventListener("input", () => {
                    numbers[index] = input.value.trim();
                    checkDuplicates();
                    save();
                    updateLabels();
                });
                wrap.append(prefix, input);
                box.append(label, wrap);
                return box;
            }));
            count.textContent = numbers.length;
            panel.querySelector('[data-bulk-step="-1"]').disabled = numbers.length <= MIN;
            panel.querySelector('[data-bulk-step="1"]').disabled = numbers.length >= MAX;
            checkDuplicates();
            save();
            updateLabels();
        }

        panel.querySelectorAll("[data-bulk-step]").forEach(button => button.addEventListener("click", () => {
            if (button.dataset.bulkStep === "1" && numbers.length < MAX) {
                const highest = Math.max(next - 1, ...numbers.map(Number).filter(Number.isFinite));
                numbers.push(String(highest + 1));
            } else if (button.dataset.bulkStep === "-1" && numbers.length > MIN) {
                numbers.pop();
            }
            render();
        }));

        // "Create 8 Units as Vacant", the review step, the saving messages
        function updateLabels() {
            const on = toggle.checked;
            const n = numbers.length;
            form.querySelectorAll("[data-bulk-label]").forEach(button => {
                if (!button.dataset.singleLabel) button.dataset.singleLabel = button.textContent.trim();
                button.textContent = on ? button.dataset.bulkLabel.replace("{n}", n) : button.dataset.singleLabel;
            });
            form.querySelectorAll("[data-bulk-review-count]").forEach(el => { el.textContent = `${n} units`; });
            form.querySelectorAll("[data-bulk-review-units]").forEach(box => {
                box.replaceChildren(...numbers.filter(Boolean).map(number => {
                    const chip = document.createElement("span");
                    chip.className = "review-chip";
                    chip.textContent = `Unit ${number}`;
                    return chip;
                }));
            });
            form.dataset.savingMessages = on ? form.dataset.bulkSavingMessages : singleMessages;
        }

        function setBulk(on) {
            panel.hidden = !on;
            form.querySelectorAll("[data-bulk-only]").forEach(el => { el.hidden = !on; });
            form.querySelectorAll("[data-single-only]").forEach(el => { el.hidden = on; });
            // The single unit number isn't used (or checked) while Bulk listing is on
            identifier.disabled = on;
            grid.querySelectorAll("input").forEach(input => { input.disabled = !on; });
            hidden.disabled = !on;
            if (on) render();
            updateLabels();
        }

        toggle.addEventListener("change", () => setBulk(toggle.checked));
        setBulk(toggle.checked);
    });

})();
