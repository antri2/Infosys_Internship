/* ==========================================================================
   Resume upload
   --------------------------------------------------------------------------
   Uploads a PDF/DOCX to /resume/parse, which extracts the profile and writes
   it to MySQL. On success the page stops rendering a two-line summary and
   sends the user to "Review Your Profile", which shows every parsed section
   and lets them correct it -- the parse result alone is too thin to check.
   ========================================================================== */

document.addEventListener("DOMContentLoaded", () => {
    const dropzone = document.getElementById("dropzone");
    const fileInput = document.getElementById("resume-file");
    const statusBox = document.getElementById("upload-status");
    const resultBox = document.getElementById("extracted-result");
    const continueBtn = document.getElementById("continue-btn");

    if (!dropzone || !fileInput) return;

    dropzone.addEventListener("click", () => fileInput.click());

    dropzone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropzone.classList.add("is-over");
    });
    dropzone.addEventListener("dragleave", () => dropzone.classList.remove("is-over"));
    dropzone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropzone.classList.remove("is-over");
        if (e.dataTransfer.files.length) {
            fileInput.files = e.dataTransfer.files;
            uploadResume(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener("change", () => {
        if (fileInput.files.length) uploadResume(fileInput.files[0]);
    });

    function uploadResume(file) {
        const allowed = ["pdf", "docx"];
        const ext = file.name.split(".").pop().toLowerCase();
        if (!allowed.includes(ext)) {
            showStatus("Only PDF and DOCX files are supported.", true);
            return;
        }

        showStatus("Parsing " + file.name + " with AI…", false);
        resultBox.hidden = true;
        continueBtn.setAttribute("aria-disabled", "true");
        continueBtn.classList.remove("is-ready");

        const formData = new FormData();
        formData.append("resume", file);

        fetch("/resume/parse", { method: "POST", body: formData })
            .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
            .then(({ ok, data }) => {
                if (!ok || data.status === "failed") {
                    showStatus(data.error || "Could not parse this resume. Try again.", true);
                    return;
                }
                showStatus("Resume parsed. Check each section below before continuing.", false);
                renderExtracted(data.profile);
                enableContinue();
            })
            .catch(() => showStatus("Something went wrong. Check your connection and try again.", true));
    }

    function showStatus(message, isError) {
        statusBox.hidden = false;
        statusBox.textContent = message;
        statusBox.className = "upload-status" + (isError ? " upload-status--error" : "");
    }

    /* A short confirmation only. The editable view is the review page, so this
       deliberately does not try to reproduce the profile in place. */
    function renderExtracted(profile) {
        const profile_ = profile || {};
        const count = (list) => (Array.isArray(list) ? list.length : 0);

        const sections = [
            ["Skills", count(profile_.skills)],
            ["Education", count(profile_.education)],
            ["Work experience", count(profile_.experience)],
            ["Projects", count(profile_.projects)],
            ["Certifications", count(profile_.certifications)],
        ];

        const chips = sections
            .map(([label, total]) =>
                '<span class="sc-stage__chip">' + label + ": " + total + "</span>")
            .join("");

        resultBox.innerHTML =
            '<p class="sc-field__label" style="margin-top:18px;">What was extracted</p>' +
            '<div class="sc-stage__chips">' + chips + "</div>" +
            '<p class="sc-field__hint">Open "Review your profile" to correct anything.</p>';
        resultBox.hidden = false;
    }

    function enableContinue() {
        continueBtn.setAttribute("aria-disabled", "false");
        continueBtn.classList.add("is-ready");
    }
});