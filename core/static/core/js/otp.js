/* =========================================================
   OTP INPUTS
========================================================= */

const otpInputs = document.querySelectorAll('.otp-inputs input');
const otpForm = document.getElementById('otpForm');
const verifyButton = document.getElementById('verifyButton');


/* =========================================================
   INPUT BEHAVIOR
========================================================= */

otpInputs.forEach((input, index) => {

    /* Allow only numbers */

    input.addEventListener('input', () => {

        input.value = input.value.replace(/\D/g, '').slice(0, 1);


        /* Automatically move to next box */

        if (
            input.value !== '' &&
            index < otpInputs.length - 1
        ) {

            otpInputs[index + 1].focus();

        }


        updateVerifyButton();

    });


    /* Keyboard behavior */

    input.addEventListener('keydown', (event) => {

        /* Move backwards with Backspace */

        if (
            event.key === 'Backspace' &&
            input.value === '' &&
            index > 0
        ) {

            otpInputs[index - 1].focus();

        }


        /* Move backwards with ArrowLeft */

        if (
            event.key === 'ArrowLeft' &&
            index > 0
        ) {

            otpInputs[index - 1].focus();

        }


        /* Move forwards with ArrowRight */

        if (
            event.key === 'ArrowRight' &&
            index < otpInputs.length - 1
        ) {

            otpInputs[index + 1].focus();

        }

    });

});


/* =========================================================
   PASTE OTP
========================================================= */

otpInputs.forEach((input) => {

    input.addEventListener('paste', (event) => {

        event.preventDefault();


        const pasted = event.clipboardData
            .getData('text')
            .replace(/\D/g, '')
            .slice(0, otpInputs.length);


        if (!pasted) {
            return;
        }


        pasted.split('').forEach((number, index) => {

            if (otpInputs[index]) {

                otpInputs[index].value = number;

            }

        });


        /* Focus the next empty box */

        const nextEmptyIndex = pasted.length;

        if (nextEmptyIndex < otpInputs.length) {

            otpInputs[nextEmptyIndex].focus();

        } else {

            otpInputs[otpInputs.length - 1].focus();

        }


        updateVerifyButton();

    });

});


/* =========================================================
   VERIFY BUTTON
========================================================= */

function updateVerifyButton() {

    const otpComplete = [...otpInputs]
        .every(input => input.value !== '');


    verifyButton.disabled = !otpComplete;

}


/* =========================================================
   FORM SUBMISSION
========================================================= */

otpForm.addEventListener('submit', (event) => {

    const otp = [...otpInputs]
        .map(input => input.value)
        .join('');


    if (otp.length !== 6) {

        event.preventDefault();

        otpInputs[otp.length]?.focus();

        return;

    }

});


/* =========================================================
   COUNTDOWN
   How long the code still works (seconds come from the server).
========================================================= */

const timer = document.getElementById('timer');

let remainingTime = parseInt(timer.dataset.seconds, 10) || 0;


function formatTime(totalSeconds) {

    const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, '0');

    const seconds = String(totalSeconds % 60).padStart(2, '0');

    return `${minutes}:${seconds}s`;
}


function updateTimer() {

    if (remainingTime <= 0) {

        clearInterval(countdown);

        timer.textContent = 'Expired';

        otpInputs.forEach(input => {

            input.disabled = true;

        });

        verifyButton.disabled = true;

        return;

    }


    timer.textContent = formatTime(remainingTime);

    remainingTime--;

}


const countdown = setInterval(
    updateTimer,
    1000
);

updateTimer();


/* =========================================================
   RESEND
   Locked for 60 s after a code is sent ("Resend in 42s").
========================================================= */

const resendButton = document.getElementById('resendLink');

let resendWait = parseInt(resendButton?.dataset.seconds, 10) || 0;


function updateResend() {

    if (!resendButton) {
        return;
    }


    if (resendWait <= 0) {

        clearInterval(resendCountdown);

        resendButton.disabled = false;

        resendButton.textContent = 'Resend';

        return;

    }


    resendButton.disabled = true;

    resendButton.textContent = `Resend in ${resendWait}s`;

    resendWait--;

}


const resendCountdown = setInterval(
    updateResend,
    1000
);

updateResend();


/* =========================================================
   INITIAL STATE
========================================================= */

updateVerifyButton();