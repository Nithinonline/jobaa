# AGENTS.md — AI Agent Guidelines & Context for Joba

Welcome, AI Agent! This document outlines the project structure, development workflows, architecture principles, and guidelines for working with the **Joba** codebase.

---

## 1. Project Overview

**Joba** is an AI-powered Job finding app. It has features like resume tailoring, finding matching jobs and career management dashboard. It consists of a decoupled monorepo structure:

```text
jobaa/
├── backend/    # Python application: FastAPI REST API, Streamlit UI, CrewAI multi-agent tailoring engine, SQLite & Chroma DB
├── frontend/   # React + TypeScript + Vite career dashboard
├── docs/       # Project documentation and specifications
└── AGENTS.md   # Agent instructions and rules (this file)
```

---

## 2. Environment Setup & Quick Start

### Backend (Python 3.10–3.13)
> **Note:** CrewAI requires Python 3.10–3.13 (Python 3.14 is currently not supported).

1. **Activate Virtual Environment** (from repository root):
   ```powershell
   .\.venv\Scripts\Activate.ps1
   # Or on Unix: source .venv/bin/activate
   ```
2. **Navigate & Install Dependencies**:
   ```powershell
   Set-Location backend
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```
3. **Environment Configuration**:
   - Ensure `backend/.env` exists (copied from `backend/.env.example`).
   - Keys required:
     - `GROQ_API_KEY`: Groq API key for LLM inference (or configure Ollama in `config.yaml`).
     - `JOBAA_API_SECRET_KEY`: Signing key for API auth tokens.
     - `JOBAA_CORS_ORIGINS`: Allowed origins (default allows Vite dev server).

4. **Running Backend Services**:
   - **FastAPI API** (port 8000):
     ```powershell
     python -m api
     # Docs available at http://127.0.0.1:8000/docs
     ```
   - **Streamlit App** (port 8501):
     ```powershell
     streamlit run app.py
     ```

### Frontend (React + TypeScript + Vite)

1. **Setup & Run**:
   ```powershell
   Set-Location frontend
   npm install
   npm run dev
   # App runs at http://127.0.0.1:5173
   ```
2. **Build & Type Check**:
   ```powershell
   npm run build   # Runs 'tsc -b && vite build'
   ```

---

## 3. Core Architecture & Product Invariants

When implementing or modifying code, agents **must strictly adhere** to these architectural rules:

1. **Single Source of Truth**:
   - The user's structured master profile in SQLite (`db/models.py`) is the absolute source of truth.
   - Chroma vector store is a derived, rebuildable cache for semantic evidence retrieval. Never treat Chroma as the primary data store.

2. **Zero-Hallucination Resume Policy (Critical)**:
   - LLM agents (`Candidate Profiler`, `Resume Strategist`, etc.) must **never fabricate** facts, metrics, employers, or skills.
   - Agents return structured selection plans (indices of approved profile entries), not raw resume prose.
   - Markdown generation is deterministic (`core/resume_assembler.py`), constructed only from validated profile facts.

3. **Multi-Agent Pipeline (`backend/core/application_crew.py`)**:
   - **Job Posting Researcher**: Parses and extracts key requirements, tech stack, and seniority from the JD.
   - **Candidate Profiler**: Runs concurrently with Researcher; matches user profile evidence against JD requirements.
   - **Resume Strategist**: Runs sequentially after research and profiling; selects optimal profile items and bullets.
   - Every selection is validated by `core/resume_validator.py` before final assembly.

4. **Safe URL Fetching (`core/job_source.py`)**:
   - Public job URLs require HTTPS.
   - DNS validation must block private/internal IP ranges (SSRF defense).
   - Redirects capped at 3; response payload capped at 2 MB.

---

## 4. Key Directories & File Map

### Backend (`backend/`)
- `api/`: FastAPI route modules, JWT auth middleware, request/response models.
- `core/`:
  - `application_crew.py`: CrewAI agent definitions and execution pipeline for resume tailoring.
  - `job_discovery_crew.py`: CrewAI agent for automated job discovery.
  - `matcher.py`: Deterministic profile-to-JD fit scoring.
  - `ats_scorer.py`: ATS keyword analysis and diagnostic scoring.
  - `retriever.py`: Hybrid profile & Chroma evidence retrieval.
  - `resume_assembler.py`: Deterministic Markdown resume builder.
  - `pdf_exporter.py`: PDF generation from Markdown/HTML.
  - `profile_schema.py`: Pydantic data schemas for profiles and job data.
- `db/`: SQLAlchemy models (`models.py`), migration scripts (`migrate.py`), and SQLite session management (`session.py`).
- `tests/`: Pytest suite covering API, matcher, parsers, and services.

### Frontend (`frontend/src/`)
- `components/`: UI components (job cards, resume previewer, score meters, auth forms).
- `services/` or `api/`: Fetch client connecting to FastAPI endpoints.
- `App.tsx` & `main.tsx`: Root React dashboard setup.

---

## 5. Development & Testing Conventions

### Running Tests
Always run tests before concluding backend changes:
```powershell
Set-Location backend
pytest
# Or run a specific test file:
pytest tests/test_api.py -v
```

### Coding Standards
- **Python**:
  - Follow PEP 8 guidelines.
  - Use type hints on all function signatures.
  - Prefer Pydantic v2 models for schema validation.
  - Keep agent prompts structured and declare explicit output schemas (e.g., Pydantic models).
- **TypeScript / React**:
  - Keep TypeScript strict with no `any` types where possible.
  - Use modular React functional components with clean props interfaces.
  - Lucide icons (`lucide-react`) for UI iconography.
- **Git & Safety**:
  - Do not commit secrets, tokens, or local `.env` files.
  - Never defeat security validations, authentication barriers, or SSRF guards.

---

## 6. Sample Agent Task Checklist

When asked to implement a new feature or fix a bug:
1. [ ] Check existing models and schemas in `backend/core/profile_schema.py` or `backend/db/models.py`.
2. [ ] If updating backend logic, verify against `backend/tests/`.
3. [ ] If adding new API endpoints, register them under `backend/api/` and update CORS/auth settings if needed.
4. [ ] If modifying tailoring logic, ensure deterministic validation is preserved.
5. [ ] Run tests and verify both backend and frontend compile cleanly.
