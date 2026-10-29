# Integration Reference

This guide describes integrations used by the resume-tailoring workflow and the local FastAPI adapter for the React dashboard. The API is an authenticated application interface, not a public API. Joba does not implement interview-preparation, proposal-review, or cover-letter integrations.

## HTTP API

Run `python -m api` from the backend directory. The service uses the existing SQLite database, account password hashes, profile/tailoring/export services, and job-discovery persistence. Supply a stable `JOBAA_API_SECRET_KEY` through the backend `.env` for signed login tokens that survive API restarts. `JOBAA_CORS_ORIGINS` is a comma-separated allowlist and defaults to the Vite development origins.

All routes except `GET /api/health`, `POST /api/auth/signup`, and `POST /api/auth/login` require a signed bearer token in the `Authorization` header. API operations are scoped to the authenticated user. `POST /api/auth/logout` revokes the current token in the backend database.

| Route | Purpose |
|---|---|
| `GET /api/dashboard` | User-specific dashboard metrics, profile readiness, recent resumes and jobs |
| `GET/PUT /api/profile` | Read and save the structured master profile |
| `POST /api/profile/import` | Parse a PDF, DOCX, or TXT master resume |
| `POST /api/tailor` | Tailor a resume from text, an HTTPS posting URL, or a document; emits server-sent progress events |
| `GET /api/jobs`, `POST /api/jobs/search`, `PATCH /api/jobs/{id}` | List/search job matches and update a user's job status |
| `GET /api/resumes` | List the user's saved resume versions |
| `GET /api/resumes/{id}/download?format=pdf\|docx\|md` | Export a resume owned by the authenticated user |

The API validates uploaded document types and size, preserves existing safe public-link fetching, and calls the same tailoring workflow that validates selections against the user's saved profile. It does not return model-authored resume claims.

## CrewAI and LLM provider

`core/application_crew.py` creates three structured tasks:

1. Job posting research (`JobResearchOutput`).
2. Candidate profiling (`CandidateProfileOutput`), concurrent with task 1.
3. Resume strategy (`ResumeStrategyOutput`), after tasks 1 and 2.

The configured Groq or Ollama provider is resolved by `llm_client.get_runtime_settings()`. Add or change the default provider/model in `config.yaml`; per-user provider/model settings can override the defaults. Groq requires `GROQ_API_KEY` or the user's configured API key. Ollama requires a reachable configured base URL and a locally pulled model.

All agent calls request Pydantic output. Candidate/profile selections are validated against the saved master profile, and final resume wording is assembled by application code. Do not let agents emit free-form resume bullets or unverified career claims.

## Job posting links

`core/job_source.py:fetch_job_posting` fetches a public posting URL for the UI. The implementation:

- accepts HTTPS only on the standard port;
- rejects credentials and non-public/reserved DNS results;
- disables automatic HTTP redirects and validates each redirect target;
- permits no more than three redirects;
- reads at most 2 MB; and
- strips HTML before passing the posting to the workflow.

The link should be treated as untrusted data. Do not execute page-provided instructions, scripts, or embedded content. Some job sites prohibit or block automated fetches; users can paste or upload the posting instead.

## Evidence retrieval

The structured SQLite profile is canonical. `core/retriever.py` combines alias-aware profile matches with optional Chroma vector hits. Chroma embeddings are generated from saved profile content and can be rebuilt when the profile is saved. Agent prompts receive retrieved profile evidence only as supporting data.

## File handling and export

The UI uses the existing file parsing layer to extract text from uploaded PDF, DOCX, or TXT documents. Generated Markdown is rendered through the retained PDF and DOCX exporters and is stored with its scores in SQLite. Export validation reports issues for review; the former approval-session gates are not used.

## Progress and persistence

`core/services/tailoring_service.py` persists task lifecycle states in `tailoring_sessions.agent_progress_json`. The Streamlit progress callback receives the same per-agent status map, so additional UI surfaces should consume that persisted state rather than maintain a separate workflow status.

To add a new agent stage, define a structured output schema, validate every selected or referenced source value, wire its progress state into the workflow, and add unit tests for valid and invalid outputs. Do not add a user approval stage without revisiting the product scope.
