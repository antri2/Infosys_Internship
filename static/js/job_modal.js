/* ==========================================================================
   Job details modal
   --------------------------------------------------------------------------
   Replaces the old inline expand (toggleDetail / toggleDbRec), which pushed
   the page taller every time a job was opened.

   The dialog element is rendered once per page. Each View Details button
   carries the job's fields in data-* attributes, so opening a job needs no
   extra request and the content always comes from the row the page already
   rendered -- nothing is invented client-side.

   Loaded by home.html and opportunities.html.
   ========================================================================== */

(function () {
    "use strict";

    const modal = document.getElementById("aiJobModal");
    if (!modal) return;

    const panel = modal.querySelector(".ai-modal__panel");
    const backdrop = modal.querySelector(".ai-modal__backdrop");
    const closeBtn = modal.querySelector(".ai-modal__close");
    const badge = modal.querySelector(".ai-modal__badge");
    const titleEl = modal.querySelector(".ai-modal__title");
    const subEl = modal.querySelector(".ai-modal__sub");
    const bodyEl = modal.querySelector(".ai-modal__body");
    const actionsEl = modal.querySelector(".ai-modal__actions");
    /* The page's controls live in a <template>, not a data-* attribute: the
       markup contains double quotes that would terminate an attribute value. */
    const actionsTemplate = modal.querySelector("#aiJobModalActions");

    let lastFocused = null;

    /* ------------------------------------------------------------------ */
    /* Rendering helpers                                                    */
    /* ------------------------------------------------------------------ */

    function text(value, fallback) {
        const v = (value || "").trim();
        return v || (fallback || "Not provided");
    }

    function escapeHtml(value) {
        return String(value == null ? "" : value)
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }

    function isMissing(value) {
        return !(value || "").trim();
    }

    function section(title, html) {
        return "<h4>" + escapeHtml(title) + "</h4>" + (html || "");
    }

    /* Multi-line text keeps the source's own line breaks. */
    function paragraphs(value) {
        return String(value)
            .split(/\n+/)
            .map(function (line) { return line.trim(); })
            .filter(Boolean)
            .map(function (line) { return "<p>" + escapeHtml(line) + "</p>"; })
            .join("");
    }

    function bullets(items, emptyText) {
        const list = (items || []).filter(Boolean);
        if (!list.length) return '<p class="ai-modal__none">' + escapeHtml(emptyText) + "</p>";
        return "<ul>" + list.map(function (item) {
            return "<li>" + escapeHtml(item) + "</li>";
        }).join("") + "</ul>";
    }

    /* A job with no reasons leaves the attribute empty, and JSON.parse("")
       throws -- which would abort open() before the dialog ever appeared. */
    function parseReasons(raw) {
        if (!raw) return [];
        try {
            var parsed = JSON.parse(raw);
            return Array.isArray(parsed) ? parsed : [];
        } catch (error) {
            return [];
        }
    }

    /* Accepts a real array or the comma-separated string a data-* attribute
       always produces. Every dataset value is a string by definition, so
       splitting here keeps both the Home and Opportunities call sites
       working; passing an empty string would otherwise make
       `(values || []).filter` fail on a non-array. */
    function pillRow(values, variant) {
        const list = (Array.isArray(values) ? values : splitSkills(values))
            .map(function (v) { return String(v).trim(); })
            .filter(Boolean);
        if (!list.length) return '<p class="ai-modal__none">Not provided</p>';
        return '<div class="ai-pill-row">' + list.map(function (v) {
            return '<span class="ai-pill ai-pill--' + variant + '">' + escapeHtml(v) + "</span>";
        }).join("") + "</div>";
    }

    /* Splits the stored comma-separated skill strings into a clean list. */
    function splitSkills(value) {
        return String(value || "")
            .split(",")
            .map(function (s) { return s.trim(); })
            .filter(Boolean);
    }

    function field(label, value) {
        var missing = isMissing(value);
        return '<div class="job-card__facts" style="grid-template-columns:1fr;gap:10px;">' +
            '<div><span class="job-card__fact-label">' + escapeHtml(label) + "</span>" +
            '<span class="job-card__fact-value' + (missing ? " job-card__none" : "") + '">' +
            escapeHtml(text(value)) + "</span></div></div>";
    }

    /* ------------------------------------------------------------------ */
    /* Open / close                                                        */
    /* ------------------------------------------------------------------ */

    function open(job) {
        lastFocused = document.activeElement;

        badge.textContent = (job.company || "?").trim().charAt(0).toUpperCase();
        titleEl.textContent = text(job.title, "Untitled role");

        var subParts = [];
        if (!isMissing(job.company)) subParts.push(job.company);
        if (!isMissing(job.location)) subParts.push(job.location);
        if (!isMissing(job.jobType)) subParts.push(job.jobType);
        if (!isMissing(job.salary)) subParts.push(job.salary);
        subEl.textContent = subParts.length ? subParts.join("  ·  ") : "No company or location was provided for this role.";

        var html = "";

        /* Job summary. The old inline panel led with the description, so the
           dialog keeps the same order: what the job is, then why it fits. */
        html += section("Job summary", paragraphs(job.description));

        /* Work mode, employment and the published date. These moved off the
           job cards when those were decluttered; they are still shown, here,
           and only when the posting actually carries them. */
        var details = [];
        if (!isMissing(job.workMode)) details.push(["Work mode", job.workMode]);
        if (!isMissing(job.jobType)) details.push(["Employment", job.jobType]);
        if (details.length) {
            html += section("Job details",
                '<div class="job-card__facts">' + details.map(function (pair) {
                    return '<div><dt class="job-card__fact-label">' + escapeHtml(pair[0]) +
                        '</dt><dd class="job-card__fact-value">' + escapeHtml(text(pair[1])) +
                        "</dd></div>";
                }).join("") + "</div>");
        }

        html += section(
            "Why this matches your profile",
            bullets(job.matchReasons, "No match reasons were reported for this role.")
        );

        if (!isMissing(job.fit)) {
            html += section("Skills fit",
                "<p><strong>Profile Skill Fit: " + escapeHtml(job.fit) + "%</strong></p>" +
                "<p>Calculated from the required and preferred skills in your profile. " +
                "It is not a probability of getting the job.</p>");
        }

        /* The three skill groups the Opportunities page showed before the
           redesign, restored here. */
        html += '<h4>Skill comparison</h4><div class="ai-compare ai-compare--3">';
        html += '<div class="ai-compare__group ai-compare__group--req">' +
            '<p class="ai-compare__title">Required skills</p>' +
            pillRow(splitSkills(job.requiredSkills), "required") + "</div>";
        html += '<div class="ai-compare__group ai-compare__group--req">' +
            '<p class="ai-compare__title">Preferred skills</p>' +
            pillRow(splitSkills(job.preferredSkills), "preferred") + "</div>";
        html += '<div class="ai-compare__group ai-compare__group--have">' +
            '<p class="ai-compare__title">Your profile skills (matched)</p>' +
            pillRow(job.matchedSkills, "have") + "</div>";
        html += '<div class="ai-compare__group ai-compare__group--learn">' +
            '<p class="ai-compare__title">Skills to learn</p>' +
            pillRow(job.missingSkills, "missing") + "</div>";
        html += "</div>";

        html += section("Responsibilities", paragraphs(job.responsibilities));
        html += section("Qualifications", paragraphs(job.qualifications));

        /* Deadline only when the source actually carries one. */
        if (!isMissing(job.deadline)) {
            html += section("Application deadline", "<p>" + escapeHtml(job.deadline) + "</p>");
        }

        html += section("Experience required",
            isMissing(job.experience) ? "" : "<p>" + escapeHtml(job.experience) + "</p>");

        bodyEl.innerHTML = html;

        /* The action row is built by the page, because Home and Opportunities
           expose different controls for the same job. */
        actionsEl.innerHTML = actionsTemplate ? actionsTemplate.innerHTML : "";

        modal.hidden = false;
        document.body.classList.add("ai-modal-open");

        /* Publish the open job so a page can point its own dialog controls at
           this job without re-reading the button that opened it. */
        window.aiJobModal.currentJobId = job.jobId;
        document.dispatchEvent(new CustomEvent("ai-job-modal:open", { detail: job }));

        if (closeBtn) closeBtn.focus();
    }

    function close() {
        modal.hidden = true;
        document.body.classList.remove("ai-modal-open");
        window.aiJobModal.currentJobId = null;
        if (lastFocused && lastFocused.focus) lastFocused.focus();
    }

    /* ------------------------------------------------------------------ */
    /* Wiring                                                              */
    /* ------------------------------------------------------------------ */

    /* Delegated so it keeps working for any card the page renders. */
    document.addEventListener("click", function (event) {
        var trigger = event.target.closest("[data-job-open]");
        if (!trigger) return;
        event.preventDefault();
        open({
            jobId: trigger.dataset.jobId,
            title: trigger.dataset.title,
            company: trigger.dataset.company,
            location: trigger.dataset.location,
            jobType: trigger.dataset.jobType,
            salary: trigger.dataset.salary,
            deadline: trigger.dataset.deadline,
            experience: trigger.dataset.experience,
            workMode: trigger.dataset.workMode,
            fit: trigger.dataset.fit,
            description: trigger.dataset.description,
            responsibilities: trigger.dataset.responsibilities,
            qualifications: trigger.dataset.qualifications,
            requiredSkills: trigger.dataset.requiredSkills,
            preferredSkills: trigger.dataset.preferredSkills,
            matchedSkills: trigger.dataset.matchedSkills,
            missingSkills: trigger.dataset.missingSkills,
            matchReasons: parseReasons(trigger.dataset.matchReasons)
        });
    });

    if (closeBtn) closeBtn.addEventListener("click", close);
    if (backdrop) backdrop.addEventListener("click", close);

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && !modal.hidden) close();
    });

    /* Keep Tab inside the dialog while it is open. */
    modal.addEventListener("keydown", function (event) {
        if (event.key !== "Tab") return;
        var focusable = panel.querySelectorAll(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (!focusable.length) return;
        var first = focusable[0];
        var last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    });

    /* Exposed so the pages' own buttons can reuse the same dialog. */
    window.aiJobModal = { open: open, close: close, currentJobId: null };
})();