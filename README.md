# Joba

Joba is organized as one workspace with separate backend and frontend applications:

```text
jobaa/
├── backend/   Python / Streamlit application and FastAPI integration
└── frontend/  React, TypeScript, and Vite career dashboard
```

## Start the backend

Use Python 3.10–3.13 (CrewAI does not support Python 3.14). From this workspace root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
Set-Location backend
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `GROQ_API_KEY` in `backend\.env` (or configure Ollama in `backend\config.yaml`). Set `JOBAA_API_SECRET_KEY` to a long random value to keep API login tokens valid between restarts. For local development only, the API generates a temporary signing key when it is unset; this invalidates sessions when the API restarts.

Run the backend API and existing Streamlit interface from `backend`:

```powershell
python -m api
# In another terminal, with the same virtual environment:
streamlit run app.py
```

The API is available at http://127.0.0.1:8000, with interactive OpenAPI documentation at http://127.0.0.1:8000/docs.

## Start the frontend

From the workspace root:

```powershell
Set-Location frontend
Copy-Item .env.example .env
npm install
npm run dev
```

Open http://127.0.0.1:5173. `VITE_API_URL` selects the backend origin. The API defaults to allowing only the Vite localhost origins; override `JOBAA_CORS_ORIGINS` with an explicit comma-separated list when hosting the UI elsewhere.

## Existing backend documentation

- [Backend setup and product guide](./backend/README.md)
- [System architecture](./backend/ARCHITECTURE_GUIDE.md)
- [API and integration reference](./backend/API_INTEGRATION_GUIDE.md)
- [Technical documentation](./backend/TECHNICAL_DOCUMENTATION.md)
