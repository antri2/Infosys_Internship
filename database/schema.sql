CREATE DATABASE IF NOT EXISTS career_ai
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE career_ai;

CREATE TABLE IF NOT EXISTS users (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    email           VARCHAR(255) NOT NULL UNIQUE,
    phone           VARCHAR(30),
    password_hash   VARCHAR(255) NOT NULL,
    career_status   ENUM('Fresher', 'Experienced') NOT NULL DEFAULT 'Fresher',
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS resumes (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL,
    file_path       VARCHAR(500) NOT NULL,
    file_type       VARCHAR(10) NOT NULL,
    parse_status    ENUM('uploaded', 'parsing', 'parsed', 'failed') NOT NULL DEFAULT 'uploaded',
    uploaded_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS profiles (
    user_id         INT PRIMARY KEY,
    resume_id       INT,
    college         VARCHAR(255),
    degree          VARCHAR(255),
    passing_year    INT,
    cgpa            DECIMAL(4,2),
    summary         TEXT,
    experience      TEXT,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (resume_id) REFERENCES resumes(id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS skills (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL,
    name            VARCHAR(120) NOT NULL,
    category        VARCHAR(50),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS education (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL,
    institution     VARCHAR(255) NOT NULL,
    degree          VARCHAR(255),
    field           VARCHAR(255),
    start_date      VARCHAR(30),
    end_date        VARCHAR(30),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS experience (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL,
    title           VARCHAR(255) NOT NULL,
    organization    VARCHAR(255),
    start_date      VARCHAR(30),
    end_date        VARCHAR(30),
    description     TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS projects (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL,
    title           VARCHAR(255) NOT NULL,
    description     TEXT,
    tech_stack      VARCHAR(255),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS jobs (
    job_id              INT PRIMARY KEY,
    title               VARCHAR(255) NOT NULL,
    company             VARCHAR(255) NOT NULL,
    location            VARCHAR(120) NOT NULL,
    job_type            VARCHAR(30),
    domain              VARCHAR(100),
    description         TEXT NOT NULL,
    responsibilities    TEXT,
    required_skills     TEXT NOT NULL,
    preferred_skills    TEXT,
    qualifications      VARCHAR(255) NOT NULL,
    experience_required VARCHAR(60),
    education_required  VARCHAR(255),
    stipend_or_salary   VARCHAR(60),
    apply_link          VARCHAR(500),
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;


CREATE TABLE IF NOT EXISTS applications (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL,
    job_id          INT NOT NULL,
    status          ENUM('saved', 'applied', 'interview', 'under_review', 'rejected')
                        NOT NULL DEFAULT 'saved',
    applied_on      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_user_job (user_id, job_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
) ENGINE=InnoDB;
