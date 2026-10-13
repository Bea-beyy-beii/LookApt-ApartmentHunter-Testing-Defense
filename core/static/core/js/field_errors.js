// =========================================================
// FIELD ERRORS — the browser's "Please fill out this field." bubbles are
// replaced by a message under the field (core/css/components/field_errors.css).
//
// Works for every form on the page: a submit with an empty required field,
// or a script calling field.reportValidity() / checkValidity(), fires the
// field's "invalid" event; we stop the bubble and write the message into the
// field's own error line (.field-error, .ac-error, .lm-field-error ...),
// or add one under the field. Typing in the field clears it again.
//
// A field can choose its words:
//   data-error-required="Enter your first name."
//   data-error-pattern="Use 11 digits starting with 09."
// =========================================================

(function () {

    class FieldErrors {

        static BOXES = ".form-group, .ac-field, .lm-field";
        static LOOSE_BOXES = "fieldset, label";
        static LINES = ".field-error, .ac-error, .lm-field-error, .ap-error";
        static WRAPPERS = ".input-wrapper, .affix-input, .lm-input";

        constructor() {
            this.pending = [];        // fields that just failed, to focus the first one
            document.addEventListener("invalid", event => this.onInvalid(event), true);
            document.addEventListener("input", event => this.onEdit(event.target), true);
            document.addEventListener("change", event => this.onEdit(event.target), true);
        }

        // ---------- Words ----------

        message(field) {
            const v = field.validity;
            const data = field.dataset;
            if (v.customError) return field.validationMessage;          // set by the page's own checks
            if (v.valueMissing) {
                if (data.errorRequired) return data.errorRequired;
                if (field.type === "checkbox") return "Please tick this box to continue.";
                if (field.type === "radio" || field.tagName === "SELECT") return "Please choose an option.";
                if (field.type === "file") return "Please add a file.";
                return "This field is required.";
            }
            if (v.typeMismatch) return field.type === "email" ? "Enter a valid email address." : "Enter a valid link.";
            if (v.badInput) return "Enter a number.";
            if (v.patternMismatch) return data.errorPattern || field.title || "Please use the format shown.";
            if (v.tooShort) return `Use at least ${field.minLength} characters.`;
            if (v.tooLong) return `Use ${field.maxLength} characters or fewer.`;
            if (v.rangeUnderflow) return `Must be ${field.min} or more.`;
            if (v.rangeOverflow) return `Must be ${field.max} or less.`;
            if (v.stepMismatch) return Number(field.step || 1) === 1 ? "Enter a whole number." : `Use steps of ${field.step}.`;
            return field.validationMessage || "Please check this field.";
        }

        // ---------- Where it goes ----------

        box(field) {
            return field.closest(FieldErrors.BOXES) || field.closest(FieldErrors.LOOSE_BOXES);
        }

        // The field's error line, if it has one
        findLine(field) {
            const box = this.box(field);
            const scope = box || field.form || document;
            return (field.name && scope.querySelector(`[data-error-for="${CSS.escape(field.name)}"]`))
                || (box && box.querySelector(FieldErrors.LINES));
        }

        line(field) {
            const box = this.box(field);
            const own = this.findLine(field);
            if (own) return own;

            // No line yet: add one under the field (or under its wrapper)
            const line = document.createElement("p");
            line.className = "field-error";
            line.dataset.liveError = "";
            line.setAttribute("aria-live", "polite");
            if (box && box !== field) box.append(line);
            else (field.closest(FieldErrors.WRAPPERS) || field).after(line);
            return line;
        }

        // ---------- Show / clear ----------

        onInvalid(event) {
            const field = event.target;
            if (!(field instanceof HTMLElement) || !field.willValidate) return;
            event.preventDefault();                 // no browser bubble
            this.show(field, this.message(field));

            this.pending.push(field);
            if (this.pending.length === 1) {
                setTimeout(() => {
                    const first = this.pending.find(f => f.offsetParent !== null);
                    this.pending = [];
                    if (first && !first.contains(document.activeElement)) {
                        first.focus({ preventScroll: true });
                        first.scrollIntoView({ block: "center", behavior: "smooth" });
                    }
                });
            }
        }

        show(field, text) {
            const line = this.line(field);
            line.textContent = text;
            line.hidden = false;
            if (!line.id) line.id = `${field.name || "field"}-error-${Math.random().toString(36).slice(2, 7)}`;
            this.group(field).forEach(member => {
                member.setAttribute("aria-invalid", "true");
                const described = (member.getAttribute("aria-describedby") || "").split(" ");
                if (!described.includes(line.id)) member.setAttribute("aria-describedby", [...described, line.id].join(" ").trim());
            });
            this.box(field)?.classList.add("has-error");
            field._fieldError = line;
        }

        onEdit(field) {
            if (!(field instanceof HTMLElement) || !field.validity) return;
            const flagged = field._fieldError || field.getAttribute("aria-invalid") === "true"
                || this.box(field)?.classList.contains("has-error");       // also an error sent back by the server
            if (flagged && this.quietlyValid(field)) this.clear(field);
        }

        // checkValidity() would fire "invalid" again while typing; read validity instead
        quietlyValid(field) {
            return this.group(field).every(member => member.validity.valid);
        }

        clear(field) {
            const line = field._fieldError || this.findLine(field);
            if (line) {
                line.textContent = "";
                if (line.matches(".lm-field-error")) line.hidden = true;
            }
            this.group(field).forEach(member => {
                member.removeAttribute("aria-invalid");
                member._fieldError = null;
            });
            this.box(field)?.classList.remove("has-error");
        }

        // Radios with the same name are one field
        group(field) {
            if (field.type !== "radio" || !field.form || !field.name) return [field];
            return [...field.form.querySelectorAll(`input[type="radio"][name="${CSS.escape(field.name)}"]`)];
        }
    }

    window.fieldErrors = new FieldErrors();

})();
