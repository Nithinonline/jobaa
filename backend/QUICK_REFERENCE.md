# Joba Quick Reference

## Current workflow

Joba takes a saved master profile and a job description, then creates a tailored resume from verified existing profile facts.

```text
JD text / uploaded document / public HTTPS link
                      │
              ┌───────┴────────┐
              ▼                ▼
       Job Posting        Candidate Profiler
        Researcher         (parallel)
              └───────┬────────┘
                      ▼
              Resume Strategist
                      ▼
      Validate selections + assemble resume
                      ▼
       Scores → save version → export
```

## Agent progress

The tailoring screen shows each stage as `queued`, `running`, `completed`, or `failed`, with a detail message when available. Research and profiling run in parallel; strategy starts after both finish. No percentage is shown because provider APIs do not report reliable fractional completion.

## Input and output

- JD: paste text, upload PDF/DOCX/TXT, or provide a public HTTPS URL.
- URL safety: standard HTTPS port, public DNS addresses, validated redirect targets, maximum three redirects, maximum 2 MB.
- Output: ATS-oriented resume Markdown; export to PDF, DOCX, or Markdown.
- Retained product surfaces: account/profile, template settings, match and ATS scores, history, and export.
- Removed: proposal review/approval, match acknowledgement gate, interview preparation, and cover letters.

## Start the application

```powershell
# Use an installed Python 3.10–3.13 runtime.
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:GROQ_API_KEY = "your-key"
streamlit run app.py
```

Use Ollama by configuring `llm.provider: "ollama"` in `config.yaml`, installing/pulling the selected model, and starting `ollama serve`.

## Key modules

| Module | Purpose |
|---|---|
| `app.py` | Streamlit screens and live task progress |
| `core/application_crew.py` | Structured CrewAI tasks and verified profile selection |
| `core/services/tailoring_service.py` | Orchestration, progress persistence, scores, and resume-version save |
| `core/job_source.py` | Public posting URL fetch and HTML normalization |
| `core/retriever.py` | Chroma and profile-based evidence |
| `core/resume_assembler.py` | Deterministic resume Markdown |
| `core/matcher.py` | Profile-to-JD fit score |
| `core/ats_scorer.py` | ATS score and missing keywords |
| `core/services/export_service.py` | PDF and DOCX export validation |
| `db/models.py` | User, profile, JD, workflow, settings, and version tables |

## Configuration and validation

- LLM defaults and embedding settings: `config.yaml`
- Groq key: `.env` as `GROQ_API_KEY` or environment variable
- SQLite override: `JOBAA_DB_PATH`
- Tests: `pytest tests/ -v`
- Architecture details: `ARCHITECTURE_GUIDE.md`
