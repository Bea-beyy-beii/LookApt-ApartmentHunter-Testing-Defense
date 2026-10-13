function showPropertyForm() {
    document.getElementById('listings-list-view').hidden = true;
    document.getElementById('listings-form-view').hidden = false;

    // Reset wizard to Step 1
    currentStep = 1;
    goToStep(1);
    
    window.Breadcrumbs?.push("Create New Property", showListingsList);
}

function showListingsList() {
    document.getElementById('listings-form-view').hidden = true;
    document.getElementById('listings-list-view').hidden = false;

    window.Breadcrumbs?.pop();
}

function totalSteps() {
    return document.querySelectorAll('.wizard-step-panel').length || 1;
}


// =========================================================
// WIZARD
// =========================================================

let currentStep = 1;

// ---------------------------------------------------------
// NEXT
// ---------------------------------------------------------

function wizardNext() {
    const panel = document.querySelector(`.wizard-step-panel[data-step="${currentStep}"]`);
    const fields = panel.querySelectorAll('input, select, textarea');

    for (const field of fields) {
        if (!field.checkValidity()) {
            field.reportValidity();
            return;
        }
    }

    // Only the property wizard's location step has a map pin
    if (panel.querySelector('[name="latitude"]') && !hasPinnedLocation()) {
        return;
    }

    if (!hasEnoughMedia(panel)) return;

    if (currentStep < totalSteps()) {
        goToStep(currentStep + 1);
    }
}

// ---------------------------------------------------------
// BACK
// ---------------------------------------------------------

function wizardBack() {
    if (currentStep > 1) {
        goToStep(currentStep - 1);
    }
}

// ---------------------------------------------------------
// GO TO STEP
// ---------------------------------------------------------

function goToStep(step) {

    currentStep = step;

    // Show only the selected step panel
    document.querySelectorAll('.wizard-step-panel').forEach(panel => {
        panel.hidden = Number(panel.dataset.step) !== currentStep;
    });

    // Update step indicator
    updateStepIndicator(currentStep);

    // Update navigation buttons
    updateWizardButtons();

    // Maps inside a step that was hidden need a redraw once visible
    if (window.LookAptMaps) {
        const panel = document.querySelector(`.wizard-step-panel[data-step="${currentStep}"]`);
        if (panel) window.LookAptMaps.refreshAll(panel);
    }


    document.dispatchEvent(new CustomEvent("wizard:step", { detail: { step: currentStep } }));
}


// ---------------------------------------------------------
// STEP 2: a pin on the map is required
// ---------------------------------------------------------

function hasPinnedLocation() {
    const form = document.querySelector('.wizard-form');
    const lat = form && form.querySelector('[name="latitude"]');
    const lng = form && form.querySelector('[name="longitude"]');
    const note = document.getElementById('location-required-note');
    const pinned = Boolean(lat && lng && lat.value && lng.value);

    if (note) note.hidden = pinned;
    return pinned;
}


// ---------------------------------------------------------
// PHOTO STEP: at least 2 photos (complex) / photos or videos (unit)
// photo_upload.js keeps the count in data-total
// ---------------------------------------------------------

function hasEnoughMedia(panel) {
    const upload = panel && panel.querySelector('[data-photo-upload][data-min]');
    if (!upload) return true;
    const total = Number(upload.dataset.total ?? upload.dataset.existing ?? 0);
    if (total >= Number(upload.dataset.min)) return true;
    const error = upload.querySelector('.photo-upload-error');
    if (error) {
        error.textContent = upload.dataset.minMessage;
        error.hidden = false;
    }
    return false;
}


// ---------------------------------------------------------
// "SELECT ALL" for Property Features / Amenities
// ---------------------------------------------------------

function syncSelectAll(button) {
    const boxes = [...button.closest('.form-group').querySelectorAll('[data-check-feature] input[type="checkbox"]')];
    const allOn = boxes.length > 0 && boxes.every(box => box.checked);
    button.textContent = allOn ? 'Clear all' : 'Select all';
    button.setAttribute('aria-pressed', String(allOn));
}

document.addEventListener('click', function (e) {
    const button = e.target.closest('[data-select-all]');
    if (!button) return;
    const boxes = [...button.closest('.form-group').querySelectorAll('[data-check-feature] input[type="checkbox"]')];
    const turnOn = !boxes.every(box => box.checked);
    boxes.forEach(box => {
        if (box.checked === turnOn) return;
        box.checked = turnOn;
        box.dispatchEvent(new Event('change', { bubbles: true }));    // keeps the draft + review in sync
    });
    syncSelectAll(button);
});

document.addEventListener('change', function (e) {
    const group = e.target.closest && e.target.closest('.form-group');
    const button = group && group.querySelector('[data-select-all]');
    if (button) syncSelectAll(button);
});

document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-select-all]').forEach(syncSelectAll);    // e.g. editing with all ticked
});


// ---------------------------------------------------------
// UPDATE BUTTONS
// ---------------------------------------------------------

function updateWizardButtons() {

    const backButton = document.querySelector('.wizard-back');
    const nextButton = document.querySelector('.wizard-next');
    const submitGroup = document.querySelector('.wizard-submit-group');

    if (!backButton || !nextButton || !submitGroup) {
        return;
    }

    backButton.hidden = currentStep === 1;
    nextButton.hidden = currentStep === totalSteps();
    submitGroup.hidden = currentStep !== totalSteps();
}


function updateStepIndicator(step) {
    document.querySelectorAll('.wizard-steps .wizard-step').forEach((el, index) => {
        const stepNumber = index + 1;
        const circle = el.querySelector('.step-circle');

        el.classList.toggle('active', stepNumber === step);
        el.classList.toggle('completed', stepNumber < step);

        circle.textContent = stepNumber < step ? '✓' : stepNumber;
    });
}


// ---------------------------------------------------------
// INITIALIZE
// ---------------------------------------------------------

document.addEventListener('DOMContentLoaded', function () {

    // After a failed submit, open the first step that has an error
    const firstError = document.querySelector('.wizard-step-panel .field-error');
    goToStep(firstError ? Number(firstError.closest('.wizard-step-panel').dataset.step) : 1);

    const form = document.querySelector('.wizard-form');
    if (!form) return;

    form.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter' || currentStep >= totalSteps()) return;
        if (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'BUTTON') return;

        e.preventDefault();
        wizardNext();
    });

    form.addEventListener('submit', function (e) {
        const panels = document.querySelectorAll('.wizard-step-panel');
        for (const panel of panels) {
            const invalid = [...panel.querySelectorAll('input, select, textarea')]
                .find(f => !f.checkValidity());
            if (invalid) {
                e.preventDefault();
                goToStep(Number(panel.dataset.step));
                invalid.reportValidity();
                return;
            }
        }

        if (form.querySelector('[name="latitude"]') && !hasPinnedLocation()) {
            e.preventDefault();
            goToStep(2);
        }

        const photoPanel = form.querySelector('[data-photo-upload][data-min]')?.closest('.wizard-step-panel');
        if (!e.defaultPrevented && photoPanel && !hasEnoughMedia(photoPanel)) {
            e.preventDefault();
            goToStep(Number(photoPanel.dataset.step));
        }

        // Valid submit: cover the page with a "Creating…" screen while files upload
        if (!e.defaultPrevented) showSavingOverlay(form);
    });

    // Back button after submitting: the browser may restore the page with the overlay still on
    window.addEventListener('pageshow', hideSavingOverlay);

    // Coming back with the browser's Back button: unlock the form again
    window.addEventListener('pageshow', () => form.classList.remove('is-saving'));

    // Keep the Review step in sync with the map in step 2
    form.addEventListener('lookapt:map-change', function (e) {
        const reviewAddress = document.getElementById('review-address');
        if (reviewAddress && e.detail.address) reviewAddress.textContent = e.detail.address;
        hasPinnedLocation();
    });

    form.addEventListener('input', function (e) {
        if (e.target.name !== 'address') return;
        e.target.dataset.autofilled = '0';
        const reviewAddress = document.getElementById('review-address');
        if (reviewAddress) reviewAddress.textContent = e.target.value;
    });
});

// ---------------------------------------------------------
// "CREATING…" OVERLAY (shown while the form uploads)
// Messages come from the form's data-saving-messages attribute. Each one
// stays SAVING_MESSAGE_MS; the last one stays until the page changes.
// ---------------------------------------------------------

const SAVING_MESSAGE_MS = 4000;
let savingTimer = null;

function showSavingOverlay(form) {
    let messages = ['Saving…'];
    try {
        messages = JSON.parse(form.dataset.savingMessages || '["Saving…"]');
    } catch (error) {
        /* keep the default */
    }

    let overlay = document.querySelector('.saving-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.className = 'saving-overlay';
        overlay.setAttribute('role', 'status');
        overlay.setAttribute('aria-live', 'polite');
        overlay.innerHTML = `
            <div class="saving-card">
                <div class="saving-spinner" aria-hidden="true"></div>
                <strong class="saving-text"></strong>
                <div class="saving-progress" aria-hidden="true"><span></span></div>
                <small>This can take a moment for photos and videos. Please don't close this page.</small>
            </div>`;
        document.body.append(overlay);
    }

    const text = overlay.querySelector('.saving-text');
    let index = 0;

    function showMessage() {
        text.classList.remove('is-visible');
        // let the fade-out finish, then swap the text and fade back in
        setTimeout(() => {
            text.textContent = messages[index];
            text.classList.add('is-visible');
            index += 1;
            // Stay on the last message ("Almost done…") instead of starting over
            if (index >= messages.length) clearInterval(savingTimer);
        }, 300);
    }

    clearInterval(savingTimer);
    showMessage();
    savingTimer = setInterval(showMessage, SAVING_MESSAGE_MS);
    overlay.hidden = false;
}

function hideSavingOverlay() {
    clearInterval(savingTimer);
    const overlay = document.querySelector('.saving-overlay');
    if (overlay) overlay.hidden = true;
}

