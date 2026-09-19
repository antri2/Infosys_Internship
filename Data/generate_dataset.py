"""
M2.1 -- Dataset generation.

Builds a raw dataset of internship/job postings by combining domain
templates (title, skill pools, responsibilities, qualifications) with
companies and locations. This is a common, legitimate way to bootstrap a
training/demo dataset before switching to real scraped or API-sourced
postings later -- every field follows the schema a real job-board API
(e.g. LinkedIn, Naukri, Internshala) would actually return, so swapping
in real data later is a drop-in replacement, not a redesign.

We deliberately inject a handful of exact duplicates and a handful of
incomplete rows into the raw output, so clean_dataset.py has genuine
duplicate/incomplete rows to detect and remove -- matching the M2.1
requirement to demonstrate a real cleaning step, not a trivial no-op.

Run:
    python data/generate_dataset.py
Produces:
    data/jobs_raw.csv
"""
import csv
import random
from pathlib import Path

random.seed(42)  # reproducible dataset across runs

OUT_PATH = Path(__file__).resolve().parent / "jobs_raw.csv"

COMPANIES = [
    "Nexalytics Technologies", "Brightwave Technologies", "PixelForge Studios",
    "CloudNine Systems", "Quantify Analytics", "ByteBridge Solutions",
    "Sunrise Softworks", "Vertex Digital Labs", "Orbit Innovations",
    "Zenith Cloud Systems", "Meridian Data Co", "Skyline Tech Ventures",
    "Novacore Systems", "BluePeak Analytics", "Ironclad Cyber Solutions",
    "Lumen Software Labs", "Crestline Technologies", "Northstar AI",
    "Pinnacle Web Works", "Silverline Consulting", "Everest Cloud Services",
    "Catalyst Robotics", "Momentum Fintech", "Harborlight Data Systems",
    "Evergreen IT Solutions", "TerraByte Networks", "Clarity Insights Inc",
    "Fusion Edge Technologies", "Redwood Analytics", "Bluepine Software",
    "GreenTech Innovations", "Apex Digital Solutions", "Coral Bay Systems",
    "Highbridge Technologies", "Starlight Design Studio", "Ridgeline Tech",
    "Vantage Point Analytics", "Wavelength Media Labs", "Solstice Software",
    "Amberwood Consulting", "Falcon Edge Systems", "Bright Horizon Tech",
    "Cobalt Cloud Works", "Marble Arch Analytics", "Driftwood Digital",
    "Palm Grove Technologies", "Indigo Wave Solutions", "Anchor Point Systems",
    "Lighthouse Data Co", "Emberstone Software",
]

LOCATIONS = [
    "Bangalore", "Hyderabad", "Pune", "Mumbai", "Delhi NCR", "Chennai",
    "Indore", "Ahmedabad", "Kolkata", "Gurgaon", "Noida", "Jaipur",
    "Kochi", "Coimbatore", "Remote", "Chandigarh", "Nagpur", "Bhopal",
]

EDUCATION_LEVELS = [
    "Pursuing B.Tech/B.E.", "B.Tech/B.E. (Computer Science or related)",
    "Pursuing MCA", "MCA / M.Sc Computer Science", "BCA / B.Sc IT",
    "Pursuing B.Tech (any branch)", "Any graduate (technical background preferred)",
    "MBA (any specialization)", "Pursuing MBA", "B.Com / M.Com",
    "Diploma or Degree in relevant field",
]

# Each domain: (title pool, required skill pool, preferred skill pool,
# responsibility templates, description opener)
DOMAINS = {
    "Software Development": dict(
        titles=["Software Development Intern", "Backend Developer Intern",
                "Frontend Developer Intern", "Full Stack Developer",
                "Junior Software Engineer", "Software Engineer Intern"],
        required=["Python", "Java", "Git", "REST APIs", "SQL", "Data Structures", "OOP"],
        preferred=["Docker", "AWS", "Microservices", "CI/CD", "Kubernetes"],
        resp=["Write clean, maintainable code for {x}", "Debug and fix issues in existing modules",
              "Participate in code reviews", "Collaborate with cross-functional teams on {x}",
              "Write unit tests for new features"],
        desc="We are looking for a motivated individual to join our engineering team and help build {x}.",
    ),
    "Data Science & ML": dict(
        titles=["Data Science Intern", "Machine Learning Intern",
                "ML Engineer", "Data Analyst Intern", "AI Research Intern"],
        required=["Python", "Pandas", "NumPy", "Scikit-learn", "SQL", "Statistics"],
        preferred=["TensorFlow", "PyTorch", "NLP", "Deep Learning", "MLOps"],
        resp=["Clean and preprocess datasets for {x}", "Build and evaluate ML models",
              "Perform exploratory data analysis on {x}", "Present findings to stakeholders",
              "Deploy models into production pipelines"],
        desc="Join our data team to help extract insights and build predictive models for {x}.",
    ),
    "Web Development": dict(
        titles=["Web Developer Intern", "React Developer Intern",
                "UI Developer", "JavaScript Developer", "Web Development Trainee"],
        required=["HTML", "CSS", "JavaScript", "React", "Responsive Design"],
        preferred=["Next.js", "TypeScript", "Tailwind CSS", "Node.js"],
        resp=["Build responsive UI components for {x}", "Optimize page load performance",
              "Fix cross-browser compatibility issues", "Integrate REST APIs into the frontend"],
        desc="Help us build and maintain fast, modern web experiences for {x}.",
    ),
    "Mobile App Development": dict(
        titles=["Android Developer Intern", "iOS Developer Intern",
                "Flutter Developer", "Mobile App Development Intern"],
        required=["Kotlin", "Java", "Android SDK", "Flutter", "Dart"],
        preferred=["Firebase", "REST APIs", "SQLite", "Swift"],
        resp=["Develop and test mobile features for {x}", "Fix bugs reported by QA",
              "Optimize app performance and battery usage", "Integrate third-party SDKs"],
        desc="Work on our mobile app used by thousands of users to build {x}.",
    ),
    "Cybersecurity": dict(
        titles=["Cybersecurity Intern", "SOC Analyst Intern",
                "Security Research Intern", "Penetration Testing Intern"],
        required=["Networking Fundamentals", "Linux", "OWASP Top 10", "Wireshark"],
        preferred=["Python Scripting", "Burp Suite", "SIEM Tools", "Cloud Security"],
        resp=["Monitor systems for security incidents related to {x}", "Assist in vulnerability assessments",
              "Document security findings and remediation steps", "Support incident response drills"],
        desc="Support our security team in protecting systems and data related to {x}.",
    ),
    "Cloud & DevOps": dict(
        titles=["DevOps Intern", "Cloud Engineer Intern", "Site Reliability Intern",
                "Cloud Support Engineer"],
        required=["Linux", "AWS", "Docker", "Shell Scripting", "Git"],
        preferred=["Kubernetes", "Terraform", "Jenkins", "Azure", "GCP"],
        resp=["Automate deployment pipelines for {x}", "Monitor infrastructure uptime",
              "Manage container orchestration", "Assist in cloud cost optimization"],
        desc="Help us build and maintain scalable, reliable cloud infrastructure for {x}.",
    ),
    "UI/UX Design": dict(
        titles=["UI/UX Design Intern", "Product Designer Intern", "Graphic Design Intern"],
        required=["Figma", "Adobe XD", "Wireframing", "User Research", "Prototyping"],
        preferred=["Adobe Illustrator", "Design Systems", "Usability Testing"],
        resp=["Design wireframes and mockups for {x}", "Conduct user research and usability tests",
              "Collaborate with developers to implement designs", "Maintain design system consistency"],
        desc="Join our design team to craft intuitive user experiences for {x}.",
    ),
    "Digital Marketing": dict(
        titles=["Digital Marketing Intern", "SEO Intern", "Social Media Marketing Intern",
                "Content Marketing Intern"],
        required=["SEO", "Google Analytics", "Content Writing", "Social Media Marketing"],
        preferred=["Google Ads", "Email Marketing", "Canva", "HubSpot"],
        resp=["Plan and execute campaigns for {x}", "Analyze campaign performance metrics",
              "Create content calendars", "Optimize website content for search engines"],
        desc="Help grow our brand presence and drive engagement for {x}.",
    ),
    "Business Analysis": dict(
        titles=["Business Analyst Intern", "Junior Business Analyst",
                "Product Analyst Intern"],
        required=["Excel", "SQL", "Data Analysis", "Requirement Gathering"],
        preferred=["Power BI", "Tableau", "Agile", "JIRA"],
        resp=["Gather and document business requirements for {x}", "Analyze data to identify trends",
              "Prepare reports and dashboards", "Support product roadmap planning"],
        desc="Support our product and strategy teams by analyzing data related to {x}.",
    ),
    "Finance & Accounting": dict(
        titles=["Finance Intern", "Accounting Intern", "Financial Analyst Intern"],
        required=["Excel", "Financial Modeling", "Accounting Principles", "Tally"],
        preferred=["Power BI", "SAP", "Budgeting", "Forecasting"],
        resp=["Assist in preparing financial reports for {x}", "Reconcile accounts and transactions",
              "Support budgeting and forecasting activities", "Assist with audit documentation"],
        desc="Support our finance team with reporting and analysis for {x}.",
    ),
    "Human Resources": dict(
        titles=["HR Intern", "Talent Acquisition Intern", "HR Operations Intern"],
        required=["Communication Skills", "MS Office", "Recruitment", "HRIS"],
        preferred=["Employer Branding", "Onboarding Programs", "HR Analytics"],
        resp=["Source and screen candidates for {x}", "Coordinate interview scheduling",
              "Support onboarding of new hires", "Maintain HR records and databases"],
        desc="Join our HR team to support hiring and employee experience for {x}.",
    ),
    "Content Writing": dict(
        titles=["Content Writing Intern", "Technical Writer Intern", "Copywriting Intern"],
        required=["Content Writing", "Editing", "Research Skills", "SEO Writing"],
        preferred=["WordPress", "Grammarly", "Content Strategy"],
        resp=["Write and edit content for {x}", "Research industry topics for blog posts",
              "Optimize content for SEO", "Proofread and edit team submissions"],
        desc="Help us create engaging, high-quality content for {x}.",
    ),
    "Quality Assurance": dict(
        titles=["QA Intern", "Software Testing Intern", "Automation Testing Intern"],
        required=["Manual Testing", "Test Case Design", "Bug Tracking", "SQL"],
        preferred=["Selenium", "Postman", "JMeter", "API Testing"],
        resp=["Write and execute test cases for {x}", "Log and track defects",
              "Perform regression testing", "Automate repetitive test scenarios"],
        desc="Help ensure the quality and reliability of {x} before release.",
    ),
    "Embedded Systems & IoT": dict(
        titles=["Embedded Systems Intern", "IoT Developer Intern", "Firmware Intern"],
        required=["C", "C++", "Microcontrollers", "Embedded C"],
        preferred=["RTOS", "Arduino", "Raspberry Pi", "PCB Design"],
        resp=["Develop firmware for {x}", "Test hardware-software integration",
              "Debug embedded systems issues", "Document hardware interfaces"],
        desc="Work on embedded hardware and firmware for {x}.",
    ),
    "Product Management": dict(
        titles=["Product Management Intern", "Associate Product Manager Intern"],
        required=["Product Roadmapping", "User Research", "Agile", "Communication Skills"],
        preferred=["JIRA", "SQL", "A/B Testing", "Figma"],
        resp=["Assist in defining product requirements for {x}", "Coordinate with engineering and design",
              "Analyze user feedback and metrics", "Support sprint planning"],
        desc="Support our product team in shaping the roadmap for {x}.",
    ),
}

DOMAIN_TOPICS = {
    "Software Development": ["an internal tools platform", "a customer-facing SaaS product", "a payments backend"],
    "Data Science & ML": ["a recommendation engine", "customer churn prediction", "a fraud detection system"],
    "Web Development": ["an e-commerce storefront", "a company dashboard", "a marketing website"],
    "Mobile App Development": ["a fitness tracking app", "a food delivery app", "a banking app"],
    "Cybersecurity": ["cloud infrastructure", "internal networks", "customer data systems"],
    "Cloud & DevOps": ["a multi-region deployment", "microservices infrastructure", "CI/CD pipelines"],
    "UI/UX Design": ["a mobile banking app", "an internal admin dashboard", "a consumer marketplace app"],
    "Digital Marketing": ["a new product launch", "a B2B SaaS brand", "an e-commerce store"],
    "Business Analysis": ["a subscription product", "internal operations", "a logistics platform"],
    "Finance & Accounting": ["quarterly financial statements", "vendor payments", "annual budgeting"],
    "Human Resources": ["campus hiring", "lateral hiring", "employee engagement programs"],
    "Content Writing": ["our developer blog", "product documentation", "marketing campaigns"],
    "Quality Assurance": ["a mobile banking app", "an e-commerce checkout flow", "an internal API"],
    "Embedded Systems & IoT": ["a smart home device", "an industrial IoT sensor", "a wearable device"],
    "Product Management": ["a B2B analytics product", "a consumer mobile app", "an internal tools suite"],
}

JOB_TYPES = ["Internship", "Full-time", "Internship", "Internship"]  # weighted toward internships


def pick_skills(pool, k_min, k_max):
    k = random.randint(k_min, min(k_max, len(pool)))
    return random.sample(pool, k)


def make_row(job_id, domain_name, domain):
    title = random.choice(domain["titles"])
    company = random.choice(COMPANIES)
    location = random.choice(LOCATIONS)
    job_type = random.choice(JOB_TYPES)
    topic = random.choice(DOMAIN_TOPICS[domain_name])

    required_skills = pick_skills(domain["required"], 3, 5)
    preferred_skills = pick_skills(domain["preferred"], 1, 3)
    resp_lines = random.sample(domain["resp"], min(3, len(domain["resp"])))
    responsibilities = " | ".join(r.format(x=topic) for r in resp_lines)
    description = domain["desc"].format(x=topic)

    experience = "0 years (Fresher/Student)" if job_type == "Internship" else random.choice(
        ["0-1 years", "1-2 years", "0-2 years"])
    education = random.choice(EDUCATION_LEVELS)
    stipend_salary = (
        f"₹{random.choice([8, 10, 12, 15, 18, 20, 25])},000/month"
        if job_type == "Internship"
        else f"₹{random.choice([3, 4, 5, 6, 8])} LPA"
    )

    return {
        "job_id": job_id,
        "title": title,
        "company": company,
        "location": location,
        "job_type": job_type,
        "domain": domain_name,
        "description": description,
        "responsibilities": responsibilities,
        "required_skills": ", ".join(required_skills),
        "preferred_skills": ", ".join(preferred_skills),
        "qualifications": education,
        "experience_required": experience,
        "education_required": education,
        "stipend_or_salary": stipend_salary,
        "apply_link": f"https://careers.example.com/jobs/{job_id}",
    }


FIELDNAMES = [
    "job_id", "title", "company", "location", "job_type", "domain",
    "description", "responsibilities", "required_skills", "preferred_skills",
    "qualifications", "experience_required", "education_required",
    "stipend_or_salary", "apply_link",
]


def main():
    rows = []
    job_id = 1
    domain_names = list(DOMAINS.keys())

    # Generate ~185 clean rows, roughly evenly spread across domains
    target = 185
    while len(rows) < target:
        domain_name = domain_names[len(rows) % len(domain_names)]
        rows.append(make_row(job_id, domain_name, DOMAINS[domain_name]))
        job_id += 1

    # --- Deliberately inject dirty rows for the cleaning step to remove ---
    # 1) Exact duplicates (copy a few existing rows verbatim, new job_id)
    for dup_source in random.sample(rows, 6):
        dup = dict(dup_source)
        dup["job_id"] = job_id
        rows.append(dup)
        job_id += 1

    # 2) Incomplete rows (missing required fields)
    for _ in range(5):
        domain_name = random.choice(domain_names)
        row = make_row(job_id, domain_name, DOMAINS[domain_name])
        # blank out a required field at random
        blank_field = random.choice(["title", "required_skills", "description", "company"])
        row[blank_field] = ""
        rows.append(row)
        job_id += 1

    # 3) Irrelevant/junk row (not a real job posting at all)
    rows.append({
        "job_id": job_id, "title": "TEST DO NOT USE", "company": "", "location": "",
        "job_type": "", "domain": "", "description": "asdkjaslkdj testing 123",
        "responsibilities": "", "required_skills": "", "preferred_skills": "",
        "qualifications": "", "experience_required": "", "education_required": "",
        "stipend_or_salary": "", "apply_link": "",
    })
    job_id += 1

    random.shuffle(rows)

    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} raw rows (including intentionally dirty ones) to {OUT_PATH}")


if __name__ == "__main__":
    main()