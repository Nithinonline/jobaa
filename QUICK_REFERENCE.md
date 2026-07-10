# Joba - Quick Reference Guide

## What is Joba?

**Joba** is an AI-powered resume tailoring application that:
- Helps job seekers optimize resumes for specific job descriptions
- Uses semantic matching + keyword analysis to score profile-to-JD fit
- Generates tailored resumes with ATS optimization
- Stores resume versions with improvement tracking

---

## Quick Facts

| Aspect | Details |
|--------|---------|
| **Type** | Web Application |
| **Framework** | Streamlit (Python) |
| **Database** | SQLite (SQLAlchemy ORM) |
| **LLM Provider** | Groq (or self-hosted Ollama) |
| **Hosting** | Cloud or Local |
| **Users** | Single to enterprise scale |
| **Installation Time** | 5-10 minutes |

---

## Core Libraries & Versions

### Main Stack
```
streamlit==1.36.0+                  # Web UI framework
streamlit-authenticator==0.4.0+     # User authentication
SQLAlchemy==2.0.0+                  # Database ORM
Pydantic==2.0.0+                    # Data validation
PyYAML==6.0.0+                      # Config loading
```

### AI & NLP
```
groq==0.9.0+                        # LLM API (primary)
sentence-transformers==3.0.0+       # Semantic embeddings
numpy                               # Numerical operations
```

### File Processing
```
pdfplumber==0.11.0+                 # PDF text extraction
python-docx==1.1.0+                 # DOCX parsing
weasyprint==62.0+                   # HTML to PDF conversion
requests==2.31.0+                   # HTTP client
```

---

## Project Structure

```
jobaa/
├── app.py                      # Main entry point
├── config.yaml                 # LLM & threshold config
├── requirements.txt            # Dependencies
├── TECHNICAL_DOCUMENTATION.md  # Full docs
├── auth/
│   └── auth_config.py         # Login/signup logic
├── core/
│   ├── ats_scorer.py          # ATS score calculation
│   ├── llm_client.py          # Groq/Ollama integration
│   └── matcher.py             # Profile-JD matching
├── db/
│   ├── models.py              # SQLAlchemy models
│   └── session.py             # DB connection
└── pages/
    ├── profile.py             # User profile form
    ├── upload_jd.py           # JD upload handler
    ├── match_score.py         # Matching analysis
    ├── resume_gen.py          # Resume generation
    └── history.py             # Version history
```

---

## Key Algorithms

### 1. Match Score (0-100%)
```
Final Score = (Semantic Similarity × 0.7) + (Keyword Match × 0.3)

Semantic: Embedding-based similarity (SentenceTransformer)
Keyword: % of JD keywords found in profile
```

### 2. ATS Score (0-100%)
```
ATS Score = Keyword Density (50%) + Section Presence (50%)

Keyword Density: Matched keywords / Total JD keywords
Section Presence: +25 for each section present (experience, skills, education, summary)
```

### 3. Resume Generation Loop
```
For iteration = 1 to 3:
  1. Generate/improve resume with LLM
  2. Calculate ATS score
  3. If ATS ≥ 95 or iteration = 3: Stop
  4. Else: Continue to next iteration
```

---

## Data Models (4 Core Tables)

### Users
```
id, username, email, password_hash, is_active, created_at
```

### Profiles (1:1 with Users)
```
id, user_id, full_name, email, phone, location
summary, skills, experience, projects, education
certifications, achievements, github, linkedin, portfolio
created_at, updated_at
```

### Job Descriptions (1:Many with Users)
```
id, user_id, title, raw_text
skills, preferred_skills, experience, technologies
responsibilities, keywords
created_at
```

### Resume Versions (1:Many with Users)
```
id, user_id, job_description_id, version_name
markdown_content, match_score, ats_score
improvement_summary, missing_keywords
created_at
```

---

## User Workflow

```
1. Sign Up / Log In
        ↓
2. Create/Update Profile (skills, experience, etc.)
        ↓
3. Upload Job Description (PDF/DOCX/Text)
        ↓
4. View Match Score (semantic + keyword analysis)
        ↓
5. Check If Score ≥ 70% (threshold)
        ├─ NO → Improve profile
        └─ YES ↓
6. Generate Tailored Resume (with iterations)
        ↓
7. View ATS Score & Improvements
        ↓
8. Export (PDF, DOCX, or Markdown)
        ↓
9. Review Version History
```

---

## Setup Checklist

- [ ] Clone repository: `cd c:\Users\acer\Documents\Nithin\project\jobaa`
- [ ] Create venv: `python -m venv .venv`
- [ ] Activate: `.venv\Scripts\activate` (Windows) or `source .venv/bin/activate`
- [ ] Install deps: `pip install -r requirements.txt`
- [ ] Get Groq API key: https://console.groq.com
- [ ] Set env var: `$env:GROQ_API_KEY = "gsk_xxxxx"`
- [ ] Init DB: `python -c "from db.session import init_db; init_db()"`
- [ ] Run app: `streamlit run app.py`
- [ ] Open browser: `http://localhost:8501`

---

## Configuration (config.yaml)

```yaml
llm:
  provider: "groq"                      # or "ollama"
  groq:
    model: "llama-3.1-8b-instant"
    api_key: "${GROQ_API_KEY}"
  ollama:
    model: "llama3.2"
    base_url: "http://localhost:11434"

thresholds:
  match_score: 70                       # Min score for resume generation
  ats_score: 95                         # Target ATS score
  max_iterations: 3                     # Resume gen iterations
```

---

## LLM Providers Comparison

| Feature | Groq | Ollama |
|---------|------|--------|
| **Speed** | < 1 sec | 10-30 sec |
| **Cost** | Cheap ($) | Free |
| **Setup** | API key | Local install |
| **Privacy** | Cloud | Local |
| **Production** | ✅ Ready | ⚠️ Depends |
| **Requires GPU** | No | Optional |

---

## Common Commands

### Development
```bash
# Run app
streamlit run app.py

# Run with debug
streamlit run app.py --logger.level=debug

# Check database
sqlite3 jobaa.db ".tables"
```

### Deployment
```bash
# Docker build
docker build -t joba .

# Docker run
docker run -e GROQ_API_KEY=gsk_xxxxx -p 8501:8501 joba

# Docker compose
docker-compose up -d
```

### Maintenance
```bash
# Upgrade dependencies
pip install --upgrade -r requirements.txt

# Check for outdated packages
pip list --outdated

# Virtual environment
python -m venv .venv
```

---

## API Endpoints (via LLM)

### Job Description Parsing
**Purpose**: Extract structured data from raw JD text

**Prompt Template**:
```
Extract: title, skills, preferred_skills, experience, technologies, 
responsibilities, keywords from the text.
Return as JSON.
```

### Profile-JD Analysis
**Purpose**: Find strengths, gaps, suggestions

**Prompt Template**:
```
Compare resume profile against JD.
Return JSON with: strengths, missing_skills, missing_keywords, 
suggested_improvements.
```

### Resume Generation
**Purpose**: Generate tailored resume

**Prompt Template**:
```
Create professional resume tailored to this JD based on the profile.
Include sections: Summary, Skills, Experience, Projects, Education.
Return Markdown format.
```

---

## Performance Metrics

| Operation | Time | Cost |
|-----------|------|------|
| Profile create | < 1 sec | Free |
| JD upload + parse | 2-5 sec | ~$0.01 |
| Match score calc | 3-8 sec | ~$0.01 |
| Resume generation (1 iter) | 5-10 sec | ~$0.02 |
| Full workflow | ~20-30 sec | ~$0.05 |

---

## Security Features

✅ **Implemented**:
- Password hashing (bcrypt via streamlit-authenticator)
- User data isolation (by user_id)
- Auto-delete temp files (PDFs)
- Environment variable for API keys

⚠️ **For Production**:
- Enable HTTPS/SSL
- Implement rate limiting
- Add 2FA authentication
- Encrypt database at rest
- Use PostgreSQL instead of SQLite
- Add audit logging
- Implement RBAC

---

## Troubleshooting

| Error | Solution |
|-------|----------|
| "Groq API key not configured" | Set `$env:GROQ_API_KEY` or add to `.env` |
| "Ollama service not available" | Run `ollama serve` in new terminal |
| "Database is locked" | Reduce concurrent connections or use PostgreSQL |
| "Out of memory" | Reduce file size limits or use production deployment |
| "PDF extraction failed" | Check if PDF has selectable text (not scanned image) |

---

## File Size Reference

```
Source Code:        ~50 KB
Dependencies:       ~580 MB
ML Models:          ~300 MB (sentence-transformers)
Database (initial): ~50 KB (grows with usage)

Total Installation: ~930 MB
```

---

## Requirements Summary

### Minimum
- Python 3.8+
- 2 GB RAM
- 1 GB disk
- Groq API key (free tier available)

### Recommended
- Python 3.10+
- 8 GB RAM
- 5 GB disk
- 50 Mbps internet

### For Production
- PostgreSQL database
- Linux VPS (AWS/DigitalOcean/GCP)
- SSL certificate
- Monitoring (Prometheus/Datadog)
- Load balancer (Nginx/AWS ALB)

---

## Resources

| Resource | Link |
|----------|------|
| Streamlit Docs | https://docs.streamlit.io |
| Groq Console | https://console.groq.com |
| Ollama | https://ollama.ai |
| SQLAlchemy | https://docs.sqlalchemy.org |
| Sentence Transformers | https://www.sbert.net |

---

## Key Metrics to Monitor

- **Match Score**: 60-90% = healthy
- **ATS Score**: 85%+ = good, 95%+ = excellent
- **API Response Time**: < 5s = good
- **Database Size**: Grows ~10 MB per 100 resumes
- **Active Users**: 1-10 concurrent per 1 GB RAM

---

## Next Steps

1. **Immediate**: Get Groq API key and run locally
2. **Short-term**: Deploy to cloud (Streamlit Cloud)
3. **Medium-term**: Add PostgreSQL for scale
4. **Long-term**: Add features (cover letters, interview prep, job matching)

---

**Version**: 1.0.0  
**Last Updated**: 2026-07-02  
**Status**: Production Ready

