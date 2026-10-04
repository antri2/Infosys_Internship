# CareerAI (Flask + MySQL + HTML/CSS/JS)

CareerAI is a Flask/MySQL career and internship assistant for freshers and experienced users. It uses Groq for LLM features and FastEmbed with `BAAI/bge-small-en-v1.5` plus FAISS for semantic job retrieval.

## Fresh setup

1. **Create the virtual environment and install dependencies**
   ```bash
   python -m venv venv
   source venv/bin/activate        # Windows PowerShell: venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. **Configure the environment**
   ```bash
   cp .env.example .env             # Windows: Copy-Item .env.example .env
   ```
   Set the MySQL credentials, a long random `SECRET_KEY`, and a valid `GROQ_API_KEY` in `.env`.

3. **Initialize the database schema and M3 migration**
   ```bash
   python -c "from database.db import init_db; init_db()"
   ```
   This creates/updates the configured `MYSQL_DATABASE`. It does not load job data.

4. **Explicitly synchronize the canonical 185-job dataset**
   ```bash
   python Data/Loads_jobs_to_dataset.py
   ```
   The command idempotently upserts `Data/jobs_clean.csv` into MySQL, verifies every canonical row, and validates the checked-in FAISS lookup/metadata/index. It is safe to run again after dataset changes and is not run on every Flask startup.

5. **Start CareerAI**
   ```bash
   python app.py
   ```
   Runs at `http://localhost:5000`.

## Updating the demonstration dataset

When `jobs_clean.csv` changes, rebuild the vector artifacts and then synchronize MySQL:

```bash
python Data/clean_dataset.py
python -c "from services.rag_service import build_index; build_index()"
python Data/Loads_jobs_to_dataset.py
```

The CSV is the canonical source used to populate both MySQL and the FAISS lookup data.

## Supported resume formats

**PDF and DOCX only.** The browser accepts `.pdf,.docx`, and the server enforces the same extension allowlist with a 5 MB upload limit. Text-based documents are extracted with PyMuPDF and python-docx before structured parsing through Groq.

## Project tests

Run the focused Step 1 tests with:

```bash
pytest -q
```

The tests use the isolated `career_ai_step1_test` MySQL database and do not modify development data.
