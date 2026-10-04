function showPropertyForm() {
    document.getElementById('listings-list-view').hidden = true;
    document.getElementById('listings-form-view').hidden = false;

    // Reset wizard to Step 1
    currentStep = 1;
    goToStep(1);
}

function showListingsList() {
    document.getElementById('listings-form-view').hidden = true;
    document.getElementById('listings-list-view').hidden = false;
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

    if (currentStep === 2 && !hasPinnedLocation()) {
        return;
    }

    if (currentStep < 4) {
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
}


// ---------------------------------------------------------
// STEP 2: a pin on the map is required
// ---------------------------------------------------------

function hasPinnedLocation() {
    const form = document.querySelector('.property-wizard-form');
    const lat = form && form.querySelector('[name="latitude"]');
    const lng = form && form.querySelector('[name="longitude"]');
    const note = document.getElementById('location-required-note');
    const pinned = Boolean(lat && lng && lat.value && lng.value);

    if (note) note.hidden = pinned;
    return pinned;
}


// ---------------------------------------------------------
// UPDATE BUTTONS
// ---------------------------------------------------------

function updateWizardButtons() {

    const backButton = document.querySelector('.wizard-back');
    const nextButton = document.querySelector('.wizard-next');
    const submitButton = document.querySelector('.wizard-submit');

    if (!backButton || !nextButton || !submitButton) {
        return;
    }


    // STEP 1
    // Only Next
    if (currentStep === 1) {

        backButton.hidden = true;
        nextButton.hidden = false;
        submitButton.hidden = true;

    }


    // STEP 2 AND 3
    // Back + Next
    else if (currentStep === 2 || currentStep === 3) {

        backButton.hidden = false;
        nextButton.hidden = false;
        submitButton.hidden = true;

    }


    // STEP 4
    // Back + Create Property
    else if (currentStep === 4) {

        backButton.hidden = false;
        nextButton.hidden = true;
        submitButton.hidden = false;

    }
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
    goToStep(1);

    const form = document.querySelector('.property-wizard-form');
    if (!form) return;

    form.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter' || currentStep >= 4) return;
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

        if (!hasPinnedLocation()) {
            e.preventDefault();
            goToStep(2);
        }
    });

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
