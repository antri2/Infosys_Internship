# CareerAI (Flask + MySQL + HTML/CSS/JS)

## Setup

1. **MySQL**: create the database and run the schema.
   ```bash
   mysql -u root -p -e "CREATE DATABASE career_ai;"
   mysql -u root -p career_ai < database/schema.sql
   ```

2. **LLM (Hugging Face, local, no API key)**: nothing to install separately --
   `transformers` downloads the model automatically on first resume upload.
   Set `HF_MODEL_NAME` in `.env` if you want a different model than the
   default (Qwen 2.5 1.5B Instruct).

3. **Backend**
   ```bash
   python -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\activate
   pip install -r requirements.txt

   cp .env.example .env
   # edit .env: set your real MySQL credentials

   python app.py
   ```
   Runs at http://localhost:5000

## File formats supported

**PDF and DOCX only.** Enforced both in the browser (`accept=".pdf,.docx"`)
and on the server (`config.ALLOWED_RESUME_TYPES`) -- anything else is
rejected with a clear error before it reaches the parser.

## Tested against real MySQL

Every route in this project was tested against an actual running MySQL 8.0
instance (not SQLite, not mocked): register, duplicate-email rejection,
login, wrong-password rejection, resume upload -> parse -> save (skills,
education, experience all verified in their real tables), manual profile
edit, and the mandatory-resume-upload redirect for new users. The only
thing mocked in testing was the LLM call itself (to avoid a multi-GB model
download in a test environment) -- everything else, including real PDF
text extraction via PyMuPDF, ran for real.
