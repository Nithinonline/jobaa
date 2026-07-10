# Joba - Architecture & Components Deep Dive

## System Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────┐
│                     STREAMLIT FRONTEND                             │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Session Management (st.session_state)                      │  │
│  │  - user (User object)                                       │  │
│  │  - selected_jd_id (integer)                                 │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  UI Pages (Multipage Routing)                               │  │
│  │  ├─ Auth Screen    (login/signup)                           │  │
│  │  ├─ Profile Page   (form with 14 fields)                    │  │
│  │  ├─ Upload JD      (file upload + parsing)                  │  │
│  │  ├─ Match Score    (analysis & scoring)                     │  │
│  │  ├─ Resume Gen     (generation & export)                    │  │
│  │  └─ History        (version tracking)                       │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│                   APPLICATION SERVICES LAYER                       │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  AUTHENTICATION SERVICE (auth/auth_config.py)               │  │
│  │  ├─ hash_password()        [bcrypt hashing]                 │  │
│  │  ├─ ensure_user_exists()   [registration with validation]   │  │
│  │  ├─ authenticate_user()    [login verification]             │  │
│  │  └─ logout()               [session cleanup]                 │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  MATCHING SERVICE (core/matcher.py)                          │  │
│  │  ├─ tokenize()                [text → token extraction]     │  │
│  │  ├─ compute_match_score()    [semantic + keyword scoring]   │  │
│  │  └─ get_model()              [lazy-load transformer]        │  │
│  │                                                               │  │
│  │  Embedding Model:  all-MiniLM-L6-v2                         │  │
│  │  - 384-dim vectors                                           │  │
│  │  - Lightweight (~22 MB)                                      │  │
│  │  - Semantic similarity optimized                            │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  ATS SCORING SERVICE (core/ats_scorer.py)                   │  │
│  │  ├─ score_resume()          [calculate ATS compatibility]   │  │
│  │  ├─ keyword_extraction()    [JD term identification]        │  │
│  │  └─ section_detection()     [resume structure analysis]     │  │
│  │                                                               │  │
│  │  Scoring Components:                                         │  │
│  │  - Keyword Density:    50%                                   │  │
│  │  - Section Presence:   25%                                   │  │
│  │  - Qualitative (LLM):  25%                                   │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  LLM CLIENT SERVICE (core/llm_client.py)                    │  │
│  │  ├─ generate()              [unified LLM interface]         │  │
│  │  ├─ _generate_with_groq()   [Groq API calls]               │  │
│  │  └─ _generate_with_ollama() [Ollama HTTP calls]            │  │
│  │                                                               │  │
│  │  Configuration:                                              │  │
│  │  - Provider: groq (primary) | ollama (fallback)             │  │
│  │  - Temperature: 0.2 (deterministic)                         │  │
│  │  - Timeout: 120s (Ollama)                                   │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│                      DATABASE LAYER                                │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  ORM: SQLAlchemy 2.0 (db/models.py)                         │  │
│  │  Database: SQLite (file-based)                              │  │
│  │  Session: db/session.py (connection management)             │  │
│  │                                                               │  │
│  │  Tables:                                                     │  │
│  │  ├─ users           (authentication data)                    │  │
│  │  ├─ profiles        (user profile content)                   │  │
│  │  ├─ job_descriptions (parsed JD data)                       │  │
│  │  └─ resume_versions (generated resumes + scores)            │  │
│  │                                                               │  │
│  │  Storage: ./jobaa.db (grows with usage)                     │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│                   EXTERNAL SERVICES                                │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  LLM INFERENCE                                               │  │
│  │  ├─ Groq Cloud         [Fast: ~1s, Temperature: 0.2]        │  │
│  │  │  - Endpoint: Proprietary (via SDK)                       │  │
│  │  │  - Model: llama-3.1-8b-instant                           │  │
│  │  │  - Auth: GROQ_API_KEY environment variable              │  │
│  │  │  - Pricing: Pay-as-you-go (~$0.02/request)             │  │
│  │  │                                                           │  │
│  │  └─ Ollama Local       [Flexible: ~10-30s]                  │  │
│  │     - Endpoint: http://localhost:11434/api/generate         │  │
│  │     - Model: llama3.2 (configurable)                        │  │
│  │     - Auth: None (local)                                    │  │
│  │     - Cost: Free (hardware dependent)                       │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  FILE PROCESSING                                             │  │
│  │  ├─ pdfplumber      [PDF text extraction]                   │  │
│  │  │  - Method: Page-by-page extraction                       │  │
│  │  │  - Supports: Searchable PDFs                             │  │
│  │  │  - Temp storage: /tmp (auto-cleanup)                     │  │
│  │  │                                                           │  │
│  │  ├─ python-docx     [DOCX parsing]                          │  │
│  │  │  - Method: Paragraph-level extraction                    │  │
│  │  │  - Supports: .docx, .xlsx (via Document)                 │  │
│  │  │                                                           │  │
│  │  └─ weasyprint      [Resume PDF export]                     │  │
│  │     - Input: HTML (converted from Markdown)                 │  │
│  │     - Output: Styled PDF                                    │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  NLP EMBEDDING                                               │  │
│  │  └─ HuggingFace Sentence Transformers                        │  │
│  │     - Model: all-MiniLM-L6-v2 (lazy-loaded)                 │  │
│  │     - Size: ~300 MB (on first run)                          │  │
│  │     - Cache: ~/.cache/huggingface                           │  │
│  │     - Task: Semantic similarity scoring                     │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow Diagrams

### 1. User Registration Flow
```
User Input
    │
    ├─ username ──┐
    ├─ email      ├──> ensure_user_exists()
    └─ password ──┤
                  └──> Validate (unique username/email)
                        │
                        ├─ NO ──> Error: Already exists
                        │
                        └─ YES ──> hash_password()
                                   │
                                   └──> Create User record
                                        │
                                        └──> Session.commit()
                                             │
                                             └──> Success Message
```

### 2. Profile-JD Matching Flow
```
Profile Text + JD Text
    │
    ├──────────────────────────────────┐
    │                                  │
    ▼                                  ▼
compute_keyword_score()        compute_semantic_score()
    │                                  │
    ├─ tokenize(profile)              ├─ Encode(profile)
    ├─ tokenize(jd)                   ├─ Encode(jd)
    └─ intersection / union           └─ Cosine Similarity
        │                                 │
        └─ % value (0-100)              └─ % value (0-100)
                                            │
Final Score = (semantic × 0.7) + (keyword × 0.3)
                │
                └──> 0-100% Match Score
```

### 3. Resume Generation Loop
```
User Triggers Generation
    │
    └──> Check Match Score ≥ 70%
        ├─ NO ──> BLOCKED
        │
        └─ YES ──> Iteration Loop (max 3)
                    │
                    ├─ i=1 ──> Generate resume v1
                    ├─ i=2 ──> Improve resume v2
                    └─ i=3 ──> Final tune resume v3
                        │
                        For each iteration:
                        ├─ LLM generation
                        ├─ Calculate ATS score
                        ├─ Store ResumeVersion
                        ├─ Check ATS ≥ 95?
                        │  ├─ YES ──> STOP
                        │  └─ NO ──> Continue
                        └─ Export (PDF/DOCX/Markdown)
```

### 4. File Upload & Parsing Flow
```
User Uploads File
    │
    ├─ PDF ──> pdfplumber
    │          │
    │          ├─ Create temp file
    │          ├─ Extract pages
    │          ├─ Join text
    │          └─ Delete temp file
    │
    ├─ DOCX ──> python-docx
    │          │
    │          ├─ Create temp file
    │          ├─ Load Document
    │          ├─ Extract paragraphs
    │          └─ Delete temp file
    │
    └─ TXT ──> Direct decode
               │
               └─ UTF-8 decode
                   │
                   └─ Store raw_text
                        │
                        ├─> LLM parse to structured fields
                        │   (skills, responsibilities, keywords)
                        │
                        └─> Create JobDescription record
```

---

## Component Interaction Matrix

| Component | Auth | Matcher | ATS Scorer | LLM Client | DB |
|-----------|------|---------|-----------|-----------|-----|
| **Auth** | - | ❌ | ❌ | ❌ | ✅ |
| **Matcher** | ❌ | - | ❌ | ❌ | ❌ |
| **ATS Scorer** | ❌ | ❌ | - | ✅ | ❌ |
| **LLM Client** | ❌ | ❌ | ✅ | - | ❌ |
| **Profile Page** | ✅ | ❌ | ❌ | ❌ | ✅ |
| **Upload JD** | ✅ | ❌ | ❌ | ✅ | ✅ |
| **Match Score** | ✅ | ✅ | ❌ | ✅ | ✅ |
| **Resume Gen** | ✅ | ❌ | ✅ | ✅ | ✅ |
| **History** | ✅ | ❌ | ❌ | ❌ | ✅ |

---

## Configuration Loading Order

```
1. app.py starts
    │
    └──> config.yaml parsed (PyYAML)
        │
        ├─ llm.provider = "groq" or "ollama"
        │
        ├─ llm.groq.model = "llama-3.1-8b-instant"
        ├─ llm.groq.api_key = ${GROQ_API_KEY} (env var)
        │
        ├─ llm.ollama.model = "llama3.2"
        ├─ llm.ollama.base_url = "http://localhost:11434"
        │
        └─ thresholds
            ├─ match_score = 70
            ├─ ats_score = 95
            └─ max_iterations = 3
```

---

## Request/Response Cycle: Resume Generation

### Phase 1: Request Preparation
```
User clicks "Generate Resume"
    │
    ├─ Fetch Profile (name, skills, experience, etc.)
    ├─ Fetch JobDescription (title, skills, requirements)
    ├─ Concatenate texts
    └─ Build prompt template
```

### Phase 2: LLM Call
```
Prompt sent to LLM
    │
    ├─ If Groq:
    │  ├─ Groq(api_key=GROQ_API_KEY)
    │  ├─ chat.completions.create()
    │  ├─ Temperature: 0.2
    │  └─ Response: < 1 second
    │
    └─ If Ollama:
       ├─ requests.post(http://localhost:11434/api/generate)
       ├─ stream: false
       ├─ Timeout: 120s
       └─ Response: 10-30 seconds
```

### Phase 3: Processing
```
Response received
    │
    ├─ Parse Markdown resume
    ├─ Calculate ATS score
    ├─ Extract missing keywords
    ├─ Create ResumeVersion record
    └─ Store in database
```

### Phase 4: Display
```
Results shown to user
    │
    ├─ Display resume preview
    ├─ Show ATS score
    ├─ List improvements
    └─ Export options (PDF, DOCX, Markdown)
```

---

## Performance Optimization Strategies

### 1. Caching
```
Sentence Transformer Model:
- Lazy loaded on first use
- Cached in memory (st.cache_resource)
- ~300 MB (one-time load)

LLM Responses:
- Not cached (varies by input)
- Consider implementing Redis for production

Database Queries:
- Use SQLAlchemy query optimization
- Index on: user_id, username, email
```

### 2. Async Operations
```
Current: Synchronous (one request at a time)

Potential improvements:
- Use asyncio for concurrent requests
- Queue system for resume generation
- Background jobs for PDF export
```

### 3. Resource Limits
```
File Upload: < 50 MB
PDF Pages: Process all (no limit)
Text Length: 50,000 characters max
Concurrent Users: Limited by server RAM
Resume Iterations: 3 max (cost control)
```

---

## Error Handling Strategy

```
Layer 1: User Input Validation
├─ Streamlit built-in validation
├─ Custom validation in form handlers
└─ Error messages to user

Layer 2: Authentication Errors
├─ Invalid credentials → "Incorrect username/password"
├─ Account exists → "Username already taken"
└─ DB errors → Generic error message

Layer 3: API Errors
├─ Groq key missing → "Groq API key not configured"
├─ Ollama offline → "Ollama service not available"
├─ Network timeout → "Request timed out, please try again"
└─ Malformed response → "Unexpected response format"

Layer 4: Database Errors
├─ Connection fail → "Database connection error"
├─ Lock timeout → "Database busy, try again"
└─ Data validation → "Invalid data, check input"

Layer 5: File Processing Errors
├─ PDF corrupted → "Cannot extract text from PDF"
├─ DOCX malformed → "Invalid Word document"
├─ File too large → "File exceeds size limit"
└─ Encoding issues → "Cannot decode file content"
```

---

## Security Implementation Details

### Password Security
```
User enters password
    │
    ├─> stauth.Hasher().hash(password)
    │   └─ bcrypt algorithm (salt + hash)
    │
    └─> Store password_hash in database
        (original password NEVER stored)
        │
        └─> On login: stauth.Hasher().check_pw(input, hash)
```

### Session Management
```
User logs in
    │
    ├─> authenticate_user() returns User object
    └─> st.session_state.user = user
        │
        └─> Available in all pages
            │
            └─> Protected by st.session_state checks
```

### API Key Management
```
Option 1: Environment Variable (Recommended)
    export GROQ_API_KEY=gsk_xxxxx
    (never commit to version control)

Option 2: .env File
    GROQ_API_KEY=gsk_xxxxx
    (add .env to .gitignore)

Option 3: config.yaml (Not recommended for production)
    llm.groq.api_key: "gsk_xxxxx"
    (visible in repo, security risk)
```

### File Handling Security
```
Upload file
    │
    ├─ Create temp file
    ├─ Validate file type (PDF, DOCX, TXT only)
    ├─ Validate file size (< 50 MB)
    ├─ Process content
    └─ Delete temp file immediately
       (no files left on disk)
```

---

## Deployment Architecture Patterns

### Pattern 1: Single Instance (Development)
```
┌─────────────────────────┐
│   Streamlit App         │
│  + SQLite Database      │
│  + Local Config         │
└────────┬────────────────┘
         │
         └──> Groq API (Cloud)
              (or Ollama localhost)
```

### Pattern 2: Cloud Deployment (Small Scale)
```
┌─────────────────────────────────────────┐
│        Streamlit Cloud                  │
│    ┌──────────────────┐                 │
│    │  Joba Container  │                 │
│    └────────┬─────────┘                 │
│             │                            │
│  ┌──────────▼──────────┐                │
│  │ SQLite / PostgreSQL │                │
│  └────────┬────────────┘                │
│           │                              │
└───────────┼──────────────────────────────┘
            │
            ├──> Groq API
            ├──> Ollama (optional)
            └──> HuggingFace Models
```

### Pattern 3: Enterprise (Large Scale)
```
┌──────────────────────────────────────────────────┐
│              Load Balancer (Nginx)               │
└─────────────┬──────────────────────┬─────────────┘
              │                      │
    ┌─────────▼────────┐   ┌────────▼──────────┐
    │  Joba Pod 1      │   │  Joba Pod N       │
    │  (Kubernetes)    │   │  (Kubernetes)     │
    └─────────┬────────┘   └────────┬──────────┘
              │                      │
    ┌─────────▼────────────────────┐│
    │   PostgreSQL (Primary)       ││
    │   Replication               ││
    │   Backup                    ││
    └─────────┬────────────────────┘│
              │                      │
    ┌─────────▼──────────┐  ┌──────▼────────────┐
    │  Redis Cache       │  │  Ollama Cluster  │
    │  Session Store     │  │  (Multi-GPU)     │
    └────────────────────┘  └──────────────────┘
              │
              ├──> Groq API (Primary)
              ├──> Self-hosted Ollama (Fallback)
              ├──> Monitoring (Prometheus)
              ├──> Logging (ELK Stack)
              └──> CDN (static assets)
```

---

## Module Dependencies Graph

```
app.py
├─ auth/auth_config.py
│  └─ streamlit_authenticator
├─ db/session.py
│  └─ SQLAlchemy
├─ pages/profile.py
│  └─ db/session.py
├─ pages/upload_jd.py
│  ├─ pdfplumber
│  ├─ python-docx
│  ├─ core/llm_client.py
│  └─ db/session.py
├─ pages/match_score.py
│  ├─ core/matcher.py
│  ├─ core/llm_client.py
│  └─ db/session.py
├─ pages/resume_gen.py
│  ├─ core/ats_scorer.py
│  ├─ core/llm_client.py
│  ├─ python-docx
│  ├─ weasyprint
│  └─ db/session.py
└─ pages/history.py
   └─ db/session.py

core/matcher.py
├─ sentence_transformers
├─ numpy
└─ re (standard lib)

core/ats_scorer.py
├─ core/llm_client.py
├─ re (standard lib)
└─ typing

core/llm_client.py
├─ groq (conditional)
├─ requests
├─ yaml
└─ os (standard lib)

db/models.py
├─ SQLAlchemy
└─ datetime (standard lib)

db/session.py
└─ SQLAlchemy
```

---

## Key Design Patterns

### 1. Singleton Pattern (Global LLM Client)
```python
# core/llm_client.py
llm_client = LLMClient()  # Created once, reused everywhere
# Usage in multiple modules
from core.llm_client import llm_client
```

### 2. Factory Pattern (Model Initialization)
```python
# core/matcher.py
def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model
# Lazy-loads model only when needed
```

### 3. Strategy Pattern (LLM Providers)
```python
# core/llm_client.py
class LLMClient:
    def generate(self, prompt):
        if self.provider == "ollama":
            return self._generate_with_ollama(prompt)
        return self._generate_with_groq(prompt)
# Swappable implementations
```

### 4. Template Method Pattern (Page Rendering)
```python
# pages/*.py
def render_*_page():
    # Consistent structure across pages
    st.title(...)
    st.caption(...)
    session = SessionLocal()
    try:
        # Page-specific logic
    finally:
        session.close()
```

### 5. Repository Pattern (Database Access)
```python
# db/models.py + pages/*.py
session = SessionLocal()
user = session.query(User).filter(...).first()
# Centralized data access through ORM
```

---

**Version**: 1.0.0  
**Last Updated**: 2026-07-02  
**Document Type**: Architecture Reference

