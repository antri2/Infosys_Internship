/* ==========================================================================
   Login / Register form behaviour
   --------------------------------------------------------------------------
   Progressive enhancement only: both forms still work if this file fails to
   load. Every rule here mirrors routes/auth.py, so the message shown in the
   browser is the message the server would return.

   * Password show/hide on every [data-password-toggle] button.
   * Live password-strength meter with the five documented requirements.
   * Exactly-ten-digit phone, reported next to the field.
   * Inline validation messages instead of native bubbles, which cannot be
     styled to match the rest of the page.
   ========================================================================== */

(function () {
    "use strict";

    /* ---- Rules. Keep in step with PASSWORD_RULES in routes/auth.py. ---- */
    var PASSWORD_RULES = {
        length: function (v) { return v.length >= 8; },
        upper: function (v) { return /[A-Z]/.test(v); },
        lower: function (v) { return /[a-z]/.test(v); },
        digit: function (v) { return /[0-9]/.test(v); },
        special: function (v) { return /[^A-Za-z0-9]/.test(v); }
    };

    var STRENGTH_LABELS = {
        0: "Password strength: not set",
        1: "Password strength: too weak",
        2: "Password strength: fair",
        3: "Password strength: good",
        4: "Password strength: strong"
    };

    var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
    var PHONE_RE = /^[0-9]{10}$/;

    var EYE = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>';
    var EYE_OFF = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"></path><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"></path><path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>';

    /* ---------------- Password show / hide ---------------- */
    document.querySelectorAll("[data-password-toggle]").forEach(function (button) {
        button.addEventListener("click", function () {
            var input = document.getElementById(button.getAttribute("data-password-toggle"));
            if (!input) return;

            var wasHidden = input.type === "password";
            input.type = wasHidden ? "text" : "password";
            button.setAttribute("aria-pressed", wasHidden ? "true" : "false");
            button.setAttribute("aria-label", wasHidden ? "Hide password" : "Show password");
            button.innerHTML = wasHidden ? EYE_OFF : EYE;
            input.focus();
        });
    });

    /* ---------------- Password strength ---------------- */
    var strengthBox = document.getElementById("strength");
    var strengthLabel = document.getElementById("strength-label");
    var ruleItems = document.querySelectorAll("#password-rules [data-rule]");

    function paintStrength(value) {
        if (!strengthBox) return;

        var met = 0;
        ruleItems.forEach(function (item) {
            var rule = PASSWORD_RULES[item.getAttribute("data-rule")];
            var ok = !!rule && rule(value);
            item.classList.toggle("is-met", ok);
            if (ok) met += 1;
        });

        // A blank field reads as level 0, never as a passing score.
        var level = value.length === 0 ? 0 : Math.min(4, met);
        strengthBox.setAttribute("data-level", String(level));
        if (strengthLabel) {
            strengthLabel.setAttribute("data-level", String(level));
            strengthLabel.textContent = STRENGTH_LABELS[level];
        }
    }

    var passwordInput = document.querySelector("[data-strength-source]");
    if (passwordInput) {
        passwordInput.addEventListener("input", function () {
            paintStrength(passwordInput.value);
        });
    }

    /* ---------------- Inline field errors ---------------- */
    function setError(fieldId, message) {
        var input = document.getElementById(fieldId);
        var box = document.getElementById(fieldId + "-error");
        var field = input ? input.closest(".sc-field") : null;

        if (box) box.textContent = message || "";
        if (field) {
            field.classList.toggle("is-invalid", !!message);
            field.classList.toggle("is-valid", !message && !!(input && input.value));
        }
        if (input) {
            if (message) input.setAttribute("aria-invalid", "true");
            else input.removeAttribute("aria-invalid");
        }
        return !message;
    }

    function clearError(fieldId) {
        var input = document.getElementById(fieldId);
        var field = input ? input.closest(".sc-field") : null;
        if (field) field.classList.remove("is-invalid");
    }

    /* ---------------- Phone: digits only, exactly ten ---------------- */
    var phoneInput = document.querySelector("[data-phone-input]");
    function phoneError() {
        return "Enter exactly 10 digits.";
    }

    if (phoneInput) {
        // Strip non-digits as they are typed or pasted, so the field can never
        // hold a character the server would reject anyway.
        phoneInput.addEventListener("input", function () {
            var digits = phoneInput.value.replace(/\D+/g, "");
            if (digits.length > 10) digits = digits.slice(0, 10);
            if (phoneInput.value !== digits) phoneInput.value = digits;

            var field = phoneInput.closest(".sc-field");
            if (field && field.classList.contains("is-invalid")) {
                setError("phone", PHONE_RE.test(phoneInput.value) ? "" : phoneError());
            }
        });

        phoneInput.addEventListener("blur", function () {
            if (!phoneInput.value) return;   // phone stays optional
            setError("phone", PHONE_RE.test(phoneInput.value) ? "" : phoneError());
        });
    }

    var confirmInput = document.querySelector("[data-confirm-for]");

    /* ---------------- Submit-time validation ---------------- */
    var form = document.querySelector("[data-auth-form]");
    if (!form) return;

    form.addEventListener("submit", function (event) {
        var register = form.hasAttribute("data-register-form");
        var ok = true;

        var email = document.getElementById("email");
        if (email) {
            ok = setError("email",
                email.value.trim() && EMAIL_RE.test(email.value.trim())
                    ? ""
                    : "Enter a valid email address.") && ok;
        }

        if (phoneInput) {
            var phone = phoneInput.value.trim();
            // Blank is allowed: the column is nullable and phone is optional.
            ok = setError("phone",
                !phone ? "" : (PHONE_RE.test(phone) ? "" : phoneError())) && ok;
        }

        if (register) {
            var name = document.getElementById("name");
            if (name) {
                ok = setError("name", name.value.trim() ? "" : "Enter your name.") && ok;
            }

            var password = document.getElementById("password");
            if (password) {
                var unmet = Object.keys(PASSWORD_RULES).filter(function (key) {
                    return !PASSWORD_RULES[key](password.value);
                });
                if (!password.value) {
                    ok = setError("password", "Choose a password.") && ok;
                } else if (unmet.length) {
                    ok = setError("password", unmet.length === 1
                        ? "One requirement is still missing (see the list below)."
                        : unmet.length + " requirements are still missing (see the list below).") && ok;
                } else {
                    ok = setError("password", "") && ok;
                }
            }

            if (confirmInput && password) {
                if (!confirmInput.value) {
                    ok = setError("confirm_password", "Confirm your password.") && ok;
                } else if (confirmInput.value !== password.value) {
                    ok = setError("confirm_password", "Passwords do not match.") && ok;
                } else {
                    ok = setError("confirm_password", "") && ok;
                }
            }
        } else {
            var loginPassword = document.getElementById("password");
            if (loginPassword) {
                ok = setError("password", loginPassword.value ? "" : "Enter your password.") && ok;
            }
        }

        if (!ok) {
            event.preventDefault();
            var firstBad = form.querySelector(".sc-field.is-invalid input");
            if (firstBad) {
                firstBad.focus();
                if (firstBad.scrollIntoView) {
                    firstBad.scrollIntoView({ block: "center" });
                }
            }
        }
    });

    // Clear a field's error as soon as the user starts fixing it.
    form.addEventListener("input", function (event) {
        var field = event.target.closest(".sc-field");
        if (field && field.classList.contains("is-invalid") && event.target.id) {
            clearError(event.target.id);
        }
    });

    // Pre-fill the meter if the browser restored a value.
    if (passwordInput && passwordInput.value) paintStrength(passwordInput.value);
})();