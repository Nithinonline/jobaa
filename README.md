# Joba

AI-powered resume tailoring app that helps job seekers optimize resumes for specific job descriptions. Joba scores profile-to-JD fit, generates ATS-friendly tailored resumes, and tracks version history.

**Stack:** Streamlit · Python · SQLite · Groq (or Ollama)

---

## Developer Guide

### Prerequisites

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| Python | 3.8+ | 3.10+ |
| RAM | 2 GB | 8 GB |
| Disk | 1 GB | 5 GB |
| API key | [Groq API key](https://console.groq.com) (free tier available) | — |

You also need `git` and `pip`. On first run, `sentence-transformers` downloads ML models (~300 MB).

---

### 1. Clone and enter the project

```bash
git clone <repository-url>
cd jobaa
```

---

### 2. Create and activate a virtual environment

**Windows (PowerShell)**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

---

### 3. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

### 4. Configure environment variables

Create a `.env` file in the project root (this file is gitignored):

```env
GROQ_API_KEY=gsk_your_key_here
```

Get a key from the [Groq Console](https://console.groq.com).

**Alternative (session only, PowerShell):**

```powershell
$env:GROQ_API_KEY = "gsk_your_key_here"
```

**Optional variables**

| Variable | Purpose | Default |
|----------|---------|---------|
| `GROQ_API_KEY` | Groq LLM API authentication | — |
| `JOBAA_DB_PATH` | Custom SQLite database path | `./joba.db` |

LLM settings can also be changed in `config.yaml` (provider, model, score thresholds).

---

### 5. Initialize the database

The database is created automatically when the app starts. To initialize it manually:

```bash
python -c "from db.session import init_db; init_db()"
```

This creates `joba.db` in the project root (unless `JOBAA_DB_PATH` is set).

---

### 6. Run the application

```bash
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

**Debug logging (optional):**

```bash
streamlit run app.py --logger.level=debug
```

---

### 7. First-time app workflow

1. **Sign up** — create a local account on the login screen.
2. **Profile** — fill in skills, experience, education, and contact details.
3. **Upload JD** — paste text or upload a PDF/DOCX job description.
4. **Match score** — review semantic and keyword fit (default threshold: 70%).
5. **Generate resume** — create a tailored resume and export as PDF, DOCX, or Markdown.
6. **History** — browse saved resume versions.

---

### 8. Run tests

From the project root with the virtual environment active:

```bash
pip install pytest
pytest tests/ -v
```

Run a single test file:

```bash
pytest tests/test_ats_scorer.py -v
```

---

## Configuration

Edit `config.yaml` to change LLM provider, models, and scoring thresholds:

```yaml
llm:
  provider: "groq"          # or "ollama"
  groq:
    model: "llama-3.1-8b-instant"
    api_key: "${GROQ_API_KEY}"
  ollama:
    model: "llama3.2"
    base_url: "http://localhost:11434"

thresholds:
  match_score: 70           # minimum fit score to generate a resume
  ats_score: 95             # target ATS score during generation
  max_iterations: 3         # resume refinement loops
```

### Using Ollama instead of Groq

1. Install [Ollama](https://ollama.ai) and pull a model: `ollama pull llama3.2`
2. Start the server: `ollama serve`
3. Set `provider: "ollama"` in `config.yaml`

---

## Project structure

```
jobaa/
├── app.py                 # Main Streamlit entry point
├── config.yaml            # LLM and threshold configuration
├── requirements.txt       # Python dependencies
├── auth/                  # Login and signup
├── core/                  # Matching, ATS scoring, LLM, PDF export
├── db/                    # SQLAlchemy models and SQLite session
├── pages/                 # Streamlit page modules
└── tests/                 # Pytest test suite
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `Groq API key not configured` | Set `GROQ_API_KEY` in `.env` or as an environment variable |
| `Ollama service not available` | Run `ollama serve` in a separate terminal |
| `Database is locked` | Close other processes using `joba.db`, or set `JOBAA_DB_PATH` to a new file |
| PDF export fails | Ensure `reportlab` is installed: `pip install reportlab` |
| PDF text extraction fails | Use a PDF with selectable text, not a scanned image |
| Slow first startup | Normal — `sentence-transformers` downloads models on first use |

---

## Additional documentation

| Document | Description |
|----------|-------------|
| [QUICK_REFERENCE.md](QUICK_REFERENCE.md) | Algorithms, data models, and quick commands |
| [TECHNICAL_DOCUMENTATION.md](TECHNICAL_DOCUMENTATION.md) | Full architecture and API details |
| [ARCHITECTURE_GUIDE.md](ARCHITECTURE_GUIDE.md) | System design overview |
| [API_INTEGRATION_GUIDE.md](API_INTEGRATION_GUIDE.md) | Integration patterns for auth and core modules |

---

## License

Add your license information here.
