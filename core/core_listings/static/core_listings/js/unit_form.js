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