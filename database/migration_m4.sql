-- M4: independently versioned, user-managed resumes.
--
-- Why a new table rather than reusing `tailored_resumes`:
--   tailored_resumes is UNIQUE (user_id, job_id) and holds the *generated*
--   draft for a job, including the AI wording suggestions that still need
--   review. It is the generation cache, not the user's saved work.
--
--   The Resume Builder needs a different thing: several finished resumes per
--   role, each renamed by the user, each optionally tied to a specific job or
--   company, and each editable without touching the generated draft, the
--   candidate's profile, or any sibling version. That is a different entity,
--   so it gets its own table and `tailored_resumes` is left untouched.
--
-- `sections` holds the user's edited, structured content. `content_text` is
-- the deterministic plain-text rendering of exactly those sections, so the
-- TXT download, the PDF and the on-screen preview can never disagree.
--
-- job_id is nullable: most resumes are built for a role rather than a
-- specific posting. ON DELETE SET NULL (not CASCADE, as tailored_resumes uses)
-- so deleting a job listing never silently destroys work a user saved.

CREATE TABLE IF NOT EXISTS resume_versions (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    user_id             INT NOT NULL,
    title               VARCHAR(255) NOT NULL,
    target_role         VARCHAR(120) NULL,
    job_id              INT NULL,
    company             VARCHAR(255) NULL,
    job_description     TEXT NULL,
    template_key        VARCHAR(40) NOT NULL DEFAULT 'chronological',
    custom_instructions TEXT NULL,
    sections            MEDIUMTEXT NULL,
    content_text        MEDIUMTEXT NULL,
    source_fact_check   VARCHAR(30) NULL,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- No UNIQUE constraint: the same role may legitimately have several
    -- saved versions (different employers, different applications).
    INDEX idx_resume_versions_user (user_id, updated_at DESC),
    INDEX idx_resume_versions_role (user_id, target_role),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE SET NULL
) ENGINE=InnoDB;