/*
 * Inline job expansion for the Opportunities page.
 *
 * Replaces the dialog on that page only. The Home Dashboard keeps its popup via
 * its own include and `static/js/job_modal.js`; this file is deliberately
 * separate so the two behaviours cannot interfere.
 *
 * Why a separate file rather than a mode flag on job_modal.js
 * ------------------------------------------------------------
 * The dialog and the inline expander read the same data-* attributes and show
 * the same content, but they have different lifecycles: the dialog is one
 * global element with focus trapping and a backdrop, while the expansion is many
 * per-card regions that grow in place. Sharing one module would mean every
 * dialog concern was conditionally skipped for most cards. Keeping them apart
 * leaves each one readable, and the shared description of a job's detail
 * content lives here.
 *
 * Accessibility: the toggle is a real button with aria-expanded and
 * aria-controls, the region is a labelled container, expanding one card
 * collapses any other, and Escape closes the open card.
 */

(function () {
    'use strict';

    var esc = function (value) {
        return String(value === undefined || value === null ? '' : value)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    };

    var isMissing = function (value) {
        return value === undefined || value === null || String(value).trim() === '';
    };

    function text(value, fallback) {
        return isMissing(value) ? (fallback || '') : String(value);
    }

    function paragraphs(value) {
        if (isMissing(value)) return '';
        var blocks = String(value).split(/\n{2,}|\r\n{2,}/);
        var html = '';
        blocks.forEach(function (block) {
            var lines = block.split(/\r\n|\n/).map(function (line) {
                return line.replace(/^\s*[-*\u2022]\s*/, '').trim();
            }).filter(Boolean);
            if (!lines.length) return;
            if (lines.length === 1) {
                html += '<p class="opp-detail__para">' + esc(lines[0]) + '</p>';
            } else {
                html += '<ul class="opp-detail__bullets">' +
                    lines.map(function (line) { return '<li>' + esc(line) + '</li>'; }).join('') +
                    '</ul>';
            }
        });
        return html;
    }

    function section(title, html) {
        if (!html) return '';
        return '<section class="opp-detail__section">' +
            '<h3 class="opp-detail__heading">' + esc(title) + '</h3>' + html +
            '</section>';
    }

    function parseReasons(raw) {
        if (isMissing(raw)) return [];
        try {
            var parsed = JSON.parse(raw);
            return Array.isArray(parsed) ? parsed.filter(Boolean) : [];
        } catch (error) {
            // A malformed value must not break the page; treat it as no reasons.
            return [];
        }
    }

    function splitSkills(value) {
        if (isMissing(value)) return [];
        return String(value).split(',').map(function (s) { return s.trim(); }).filter(Boolean);
    }

    function pillRow(values, kind, emptyText) {
        if (!values.length) {
            return '<p class="opp-detail__none">' + esc(emptyText) + '</p>';
        }
        return '<div class="opp-detail__pills">' + values.map(function (value) {
            return '<span class="ai-pill ai-pill--' + kind + '">' + esc(value) + '</span>';
        }).join('') + '</div>';
    }

    function definitionList(pairs) {
        var rows = pairs.filter(function (pair) { return !isMissing(pair[1]); });
        if (!rows.length) return '';
        return '<dl class="opp-detail__facts">' + rows.map(function (pair) {
            return '<div><dt>' + esc(pair[0]) + '</dt><dd>' + esc(text(pair[1], 'Not provided')) + '</dd></div>';
        }).join('') + '</dl>';
    }

    function buildDetail(toggle) {
        var d = toggle.dataset;
        var reasons = parseReasons(d.matchReasons);
        var fit = isMissing(d.fit) ? '' : String(d.fit);

        var facts = definitionList([
            ['Employment', d.jobType],
            ['Work mode', d.workMode],
            ['Salary / stipend', d.salary],
            ['Experience', d.experience],
            ['Published', d.published],
            ['Application deadline', d.deadline],
            ['Location', d.location],
        ]);

        var matched = d.matchedSkills ? d.matchedSkills.split(',').map(function (s) { return s.trim(); }).filter(Boolean) : [];
        var missing = d.missingSkills ? d.missingSkills.split(',').map(function (s) { return s.trim(); }).filter(Boolean) : [];

        return '' +
            section('Job summary', paragraphs(d.description)) +
            section('Why this matches your profile',
                reasons.length
                    ? '<ul class="opp-detail__bullets">' +
                      reasons.map(function (r) { return '<li>' + esc(r) + '</li>'; }).join('') + '</ul>'
                    : '<p class="opp-detail__none">No match reasons were reported for this role.</p>') +
            (fit
                ? section('Skills fit',
                    '<p class="opp-detail__para"><strong>Profile Skill Fit: ' + esc(fit) + '%</strong></p>' +
                    '<p class="opp-detail__note">Calculated from the required and preferred skills in your ' +
                    'profile. It is not a probability of getting the job.</p>')
                : '') +
            section('Skill comparison',
                '<div class="opp-detail__compare">' +
                    '<div class="opp-detail__group">' +
                        '<p class="opp-detail__group-title">Required skills</p>' +
                        pillRow(splitSkills(d.requiredSkills), 'required', 'This posting lists no required skills.') +
                    '</div>' +
                    '<div class="opp-detail__group">' +
                        '<p class="opp-detail__group-title">Preferred skills</p>' +
                        pillRow(splitSkills(d.preferredSkills), 'required', 'This posting lists no preferred skills.') +
                    '</div>' +
                    '<div class="opp-detail__group">' +
                        '<p class="opp-detail__group-title">Your profile skills (matched)</p>' +
                        pillRow(matched, 'have', 'None of the required skills are in your profile yet.') +
                    '</div>' +
                    '<div class="opp-detail__group">' +
                        '<p class="opp-detail__group-title">Skills to learn</p>' +
                        pillRow(missing, 'missing', 'Your profile already covers the required skills.') +
                    '</div>' +
                '</div>') +
            section('Responsibilities', paragraphs(d.responsibilities)) +
            section('Qualifications', paragraphs(d.qualifications)) +
            section('Role details', facts);
    }

    function setExpanded(toggle, expanded) {
        var card = toggle.closest('[data-opp-card]');
        if (!card) return;
        var region = document.getElementById(toggle.getAttribute('aria-controls'));
        if (!region) return;

        var body = region.querySelector('[data-opp-detail-body]');

        if (expanded) {
            // Built on first expand, so a collapsed page does no DOM work for
            // every card at once.
            if (body && !body.dataset.built) {
                body.innerHTML = buildDetail(toggle);
                body.dataset.built = '1';
            }
            region.hidden = false;
            card.classList.add('is-expanded');
            // Let the height settle before marking the transition as running,
            // otherwise the card jumps rather than growing.
            window.requestAnimationFrame(function () {
                card.classList.add('is-open');
            });
        } else {
            region.hidden = true;
            card.classList.remove('is-expanded', 'is-open');
        }

        toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
        var label = toggle.childNodes[0];
        if (label && label.nodeType === 3) {
            label.textContent = expanded ? 'Hide Details' : 'View Details';
        }
        toggle.setAttribute('aria-label',
            expanded ? 'Hide details for this job' : 'View details for this job');
    }

    function collapseOthers(current) {
        document.querySelectorAll('[data-opp-toggle][aria-expanded="true"]').forEach(function (toggle) {
            if (toggle !== current) setExpanded(toggle, false);
        });
    }

    document.addEventListener('click', function (event) {
        var toggle = event.target.closest('[data-opp-toggle]');
        if (!toggle) return;
        event.preventDefault();
        var isOpen = toggle.getAttribute('aria-expanded') === 'true';
        if (isOpen) {
            setExpanded(toggle, false);
            return;
        }
        collapseOthers(toggle);
        setExpanded(toggle, true);
        toggle.focus();
    });

    // Escape collapses the open card, matching the dialog's behaviour without
    // stealing focus from the page for no reason.
    document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape') return;
        var open = document.querySelector('[data-opp-toggle][aria-expanded="true"]');
        if (!open) return;
        setExpanded(open, false);
        open.focus();
    });

    // Exposed for verification; harmless in normal use.
    window.opportunityExpand = {
        setExpanded: setExpanded,
        buildDetail: buildDetail
    };
}());