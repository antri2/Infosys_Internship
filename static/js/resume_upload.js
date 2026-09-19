document.addEventListener("DOMContentLoaded", () => {
    const dropzone = document.getElementById("dropzone");
    const fileInput = document.getElementById("resume-file");
    const statusBox = document.getElementById("upload-status");
    const resultBox = document.getElementById("extracted-result");
    const continueBtn = document.getElementById("continue-btn");

    dropzone.addEventListener("click", () => fileInput.click());

    dropzone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropzone.style.borderColor = "#1657D0";
    });
    dropzone.addEventListener("dragleave", () => {
        dropzone.style.borderColor = "";
    });
    dropzone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropzone.style.borderColor = "";
        if (e.dataTransfer.files.length) {
            fileInput.files = e.dataTransfer.files;
            uploadResume(fileInput.files[0]);
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

        showStatus(`Parsing ${file.name} with AI...`, false);
        resultBox.hidden = true;

        const formData = new FormData();
        formData.append("resume", file);

        fetch("/resume/parse", { method: "POST", body: formData })
            .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
            .then(({ ok, data }) => {
                if (!ok || data.status === "failed") {
                    showStatus(data.error || "Could not parse this resume. Try again.", true);
                    return;
                }
                showStatus("Resume parsed successfully.", false);
                renderExtracted(data.profile);
                continueBtn.disabled = false;
            })
            .catch(() => showStatus("Something went wrong. Check your connection and try again.", true));
    }

    function showStatus(message, isError) {
        statusBox.hidden = false;
        statusBox.textContent = message;
        statusBox.style.color = isError ? "#B91C1C" : "#1657D0";
    }

    function renderExtracted(profile) {
        const skills = (profile.skills || []).map((s) => `<span class="tag">${s.name}</span>`).join(" ");
        resultBox.innerHTML = `
            <p><b>Summary:</b> ${profile.summary || "Not available"}</p>
            <p><b>Skills:</b></p>
            <div class="tag-row">${skills || "<span class='muted'>None extracted</span>"}</div>
        `;
        resultBox.hidden = false;
    }

    continueBtn.addEventListener("click", () => {
        window.location.href = "/home";
    });
});
