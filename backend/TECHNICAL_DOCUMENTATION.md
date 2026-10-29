# Joba Technical Documentation

Joba is a Streamlit application for tailoring a resume to a job description using a saved, structured master profile. The current implementation is a single workflow: research the role and profile the candidate concurrently, create a verified selection plan, assemble a resume deterministically, score it, then save a version. There is no proposal-approval workflow, interview-preparation feature, or cover-letter generation.

The workspace also contains a React/TypeScript dashboard in `../frontend` and a FastAPI adapter in `api/`. The API reuses the same account database and service layer; the Streamlit UI remains available.

For the system diagram, module summary, data-integrity rules, and lifecycle see [ARCHITECTURE_GUIDE.md](ARCHITECTURE_GUIDE.md).

## Runtime requirements

- Python 3.10 through 3.13 (CrewAI does not currently support Python 3.14)
- Streamlit, SQLAlchemy, and Pydantic
- CrewAI and a configured Groq or Ollama model for tailoring
- SQLite for application data
- Chroma and Sentence Transformers for local profile evidence retrieval
- ReportLab, python-docx, and pdfplumber for document processing/export

Install runtime dependencies with `pip install -r requirements.txt`. Configure `GROQ_API_KEY` in `.env` when Groq is selected. Ollama requires a running local service and a model already pulled.

## Request lifecycle

### Input

The UI accepts a pasted job description, an uploaded PDF/DOCX/TXT posting, or a public HTTPS URL. Linked postings are fetched with redirects disabled at the HTTP layer and validated one hop at a time. Only port 443 and globally routable DNS addresses are accepted; the fetcher follows at most three redirects and reads no more than 2 MB. HTML is converted to text before any agent sees it.

### Agent outputs

`core/application_crew.py` defines Pydantic schemas:

- `JobResearchOutput` extends the parsed JD fields with a role summary.
- `CandidateProfileOutput` contains relevant skills and zero-based indices into profile collections.
- `ResumeStrategyOutput` contains profile skills and source entry/bullet selections.

Job research and candidate profiling execute concurrently with a shared configured CrewAI LLM. The resume strategist runs after those results are available. Outputs are validated before they are used. The profiler cannot select skills or indices absent from the source profile. The strategist cannot select entries outside the profiler's approved indices, duplicate entries, invalid bullet indices, or unsupported skills.

The resume strategist does not provide resume bullet text. `core/resume_assembler.py` renders the selected original profile values as Markdown using the saved section order. This keeps generated career claims out of the final resume.

### Persistence and progress

`core/services/tailoring_service.py` owns the operation and SQLAlchemy session. It creates a `TailoringSession`, commits progress updates, stores the generated Markdown and match score, then creates a `ResumeVersion`. A failure marks the session and currently running stage as failed; the exception is re-raised for the UI to display.

Agent progress is JSON stored in `tailoring_sessions.agent_progress_json`. Each task has a lifecycle status (`queued`, `running`, `completed`, or `failed`) and a detail string. The UI callback refreshes the per-agent status display during the synchronous run. No percentage is reported because the agent provider does not expose dependable fractional progress.

### Scores and exports

`core/matcher.py` calculates profile-to-JD fit from required and preferred skills, title, and experience. `core/ats_scorer.py` calculates the ATS-oriented score and missing-keyword list. The saved `ResumeVersion` is available in history and can be exported through the retained PDF, DOCX, and Markdown paths.

## Persistence schema

- `users`: local authentication identity.
- `profiles`: structured master profile, original resume text/name, and template configuration.
- `settings`: LLM provider/model and encrypted user API key.
- `job_descriptions`: raw normalized JD, source URL when supplied, content hash, and research fields.
- `tailoring_sessions`: run status, per-agent progress, generated Markdown, and match score.
- `resume_versions`: generated Markdown and associated scores/diagnostics.

`db/migrate.py` creates missing tables and adds columns needed by current code to existing SQLite databases. Old, now-unused columns may remain physically present in already-created databases; the current ORM and application do not read or write them.

## Configuration

`config.yaml` controls default model and embedding settings. User settings can override the LLM provider/model. `JOBAA_DB_PATH` selects a non-default SQLite path. Do not commit API keys, `.env`, database files, uploaded documents, or local Chroma data.

## Tests

Run the full suite from the repository root:

```powershell
pytest tests/ -v
```

Agent execution tests replace CrewAI calls with structured test outputs. URL-fetch tests mock DNS and HTTP responses, including private-address rejection. Database-backed service tests use an isolated SQLite database.
