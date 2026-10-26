# Joba

Joba tailors a resume to a job description using evidence from the user's saved master profile. AI agents research the role, identify relevant profile facts, and create a resume selection plan. The application validates those selections and assembles the resume deterministically; the model does not author new career claims.

## What it does

- Local account authentication and master-profile management.
- Master resume import from PDF, DOCX, or text, with structured profile editing.
- JD input as pasted text, a public HTTPS job-posting link, or an uploaded document.
- Three CrewAI stages: job research and candidate profiling run concurrently, followed by resume strategy.
- Live per-agent queued, running, completed, or failed status in the tailoring UI.
- Deterministic profile-to-JD match and ATS scoring.
- PDF, DOCX, and Markdown resume exports, plus saved resume history.

Interview preparation, resume proposal review, cover letters, and the former multi-step approval workflow are not part of the current application.

## Requirements

- Python 3.10 through 3.13 (CrewAI currently does not support Python 3.14)
- A Groq API key, or an Ollama service and locally available model
- Git and pip

## Setup

```powershell
git clone <repository-url>
cd jobaa
# Use an installed Python 3.10–3.13 runtime; 3.11 is a good default.
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
GROQ_API_KEY=your_groq_api_key
```

The key is required when using Groq. To use Ollama instead, install Ollama, pull a supported model (for example `ollama pull llama3.2`), start its service, and set `llm.provider` to `ollama` in `config.yaml`.

Initialize the database if needed, then start the UI:

```powershell
python -c "from db.session import init_db; init_db()"
streamlit run app.py
```

Open http://localhost:8501.

## Tailoring flow

1. Create an account and add or import a master resume.
2. Provide a job description as text, a public HTTPS posting URL, or a PDF/DOCX/TXT file.
3. Start tailoring once. Joba stores task progress and displays each agent's state:
   - **Job Posting Researcher** extracts the role requirements.
   - **Candidate Profiler** identifies relevant existing skills and source entries. It runs in parallel with job research.
   - **Resume Strategist** selects and orders verified facts from the profile.
4. Joba validates the selections, assembles the resume, scores the result, and saves a version.
5. Export the result or retrieve it later from history.

The researcher and profiler receive the supplied JD and profile as data, not instructions. Resume content is assembled from selected source facts; invalid or unsupported skill and profile-entry selections fail the task instead of being accepted.

Job posting links must use HTTPS on the standard port and resolve only to public IP addresses. The fetcher follows at most three validated redirects and limits downloaded content to 2 MB. Some job sites block automated requests; paste the job description or upload a document in that case.

## Configuration

Edit `config.yaml` for the model provider, model names, embedding model, and local Chroma paths. User-level provider/model/API settings can override the defaults.

```yaml
llm:
  provider: "groq" # or "ollama"
  groq:
    model: "openai/gpt-oss-120b"
    api_key: "${GROQ_API_KEY}"
  ollama:
    model: "llama3.2"
    base_url: "http://localhost:11434"

embeddings:
  model: "all-MiniLM-L6-v2"
  chroma_path: "./chroma_data"
  collection: "master_resume_chunks"
  n_results: 5
```

`JOBAA_DB_PATH` optionally selects a SQLite database path. Keep `.env`, database files, Chroma data, and uploaded resume files out of source control.

## Tests

```powershell
pip install pytest
pytest tests/ -v
```

## Project layout

```text
app.py                    Streamlit UI and tailoring progress
core/application_crew.py  CrewAI stages, output validation, resume selection
core/job_source.py        JD normalization and safe public-link fetching
core/services/            Profile, tailoring, and export orchestration
core/resume_assembler.py  Deterministic resume Markdown assembly
core/matcher.py           Profile-to-JD match scoring
core/ats_scorer.py        ATS scoring
core/retriever.py         Hybrid profile evidence retrieval
db/                       SQLAlchemy models, sessions, and migrations
tests/                    Unit and workflow tests
```

## Troubleshooting

| Problem | Check |
|---|---|
| Missing Groq API key | Set `GROQ_API_KEY` in `.env`, or choose Ollama. |
| Ollama is unavailable | Start `ollama serve` and check the configured base URL/model. |
| Job link cannot be fetched | Use HTTPS on port 443; if the site blocks requests, paste or upload the JD. |
| Tailoring fails | Read the failed agent's progress detail and check provider settings/profile completeness. |
| PDF export fails | Ensure ReportLab is installed and the profile contains exportable content. |
| Database is locked | Close other processes using the SQLite database or select another `JOBAA_DB_PATH`. |
