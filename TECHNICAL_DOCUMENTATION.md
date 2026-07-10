# Joba - Technical Documentation

## Table of Contents
1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Technology Stack](#technology-stack)
4. [Core Modules](#core-modules)
5. [Data Models](#data-models)
6. [Workflow & User Flows](#workflow--user-flows)
7. [Key Algorithms](#key-algorithms)
8. [Configuration](#configuration)
9. [API Integration](#api-integration)
10. [Database Schema](#database-schema)
11. [Dependencies](#dependencies)
12. [Installation & Setup](#installation--setup)
13. [Deployment Considerations](#deployment-considerations)

---

## Overview

**Joba** is an AI-powered resume tailoring application designed to help job seekers optimize their resumes for specific job descriptions using advanced matching algorithms and LLM-based analysis.

### Key Features
- **User Authentication**: Secure login and signup with password hashing
- **Profile Management**: Store comprehensive candidate profile data (skills, experience, education, etc.)
- **Job Description Management**: Upload and parse JDs from multiple formats (PDF, DOCX, TXT)
- **Match Score Analysis**: AI-driven profile-to-JD matching with semantic similarity scoring
- **ATS Scoring**: Resume optimization for Applicant Tracking Systems
- **Resume Generation**: Automated resume tailoring with iterative improvement loop
- **Version History**: Track all resume variations and their scores

### Target Users
- Job seekers looking to optimize resumes
- Career changers seeking profile customization
- High-volume applicants needing efficiency

---

## Architecture

### High-Level Architecture
```
┌─────────────────────────────────────────────────────────────┐
│                    Streamlit UI (Frontend)                   │
│  ┌──────────────┬──────────────┬──────────────┬───────────┐  │
│  │   Profile    │  Upload JD   │ Match Score  │ Resume    │  │
│  │    Page      │    Page      │    Page      │ Gen Page  │  │
│  └──────────────┴──────────────┴──────────────┴───────────┘  │
└────────────┬─────────────────────────────────────────────────┘
             │
┌────────────▼─────────────────────────────────────────────────┐
│               Backend Services Layer                         │
│  ┌─────────────────────┬──────────────┬────────────────────┐ │
│  │   Core Modules      │  Auth        │   Database         │ │
│  │ - matcher.py        │ - auth_      │ - models.py        │ │
│  │ - ats_scorer.py     │   config.py  │ - session.py       │ │
│  │ - llm_client.py     │              │                    │ │
│  └─────────────────────┴──────────────┴────────────────────┘ │
└────────────┬─────────────────────────────────────────────────┘
             │
┌────────────▼──────────────────────────────────────────────────┐
│          External Services & Data Layer                       │
│  ┌──────────────────────┬──────────────┬──────────────────┐  │
│  │  LLM Providers       │   Database   │  File Processing │  │
│  │ - Groq API           │  - SQLite    │ - pdfplumber     │  │
│  │ - Ollama (local)     │  - SQLAlchemy│ - python-docx    │  │
│  │                      │              │ - WeasyPrint     │  │
│  └──────────────────────┴──────────────┴──────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Module Organization
```
jobaa/
├── app.py                      # Main Streamlit application entry point
├── config.yaml                 # Configuration file (LLM settings, thresholds)
├── requirements.txt            # Python dependencies
├── auth/
│   └── auth_config.py         # User authentication logic
├── core/
│   ├── ats_scorer.py          # ATS score calculation
│   ├── llm_client.py          # LLM API client (Groq/Ollama)
│   └── matcher.py             # Profile-JD matching algorithms
├── db/
│   ├── models.py              # SQLAlchemy data models
│   └── session.py             # Database session management
└── pages/
    ├── profile.py             # User profile management page
    ├── upload_jd.py           # Job description upload page
    ├── match_score.py         # Profile-JD matching analysis
    ├── resume_gen.py          # Resume generation and tailoring
    └── history.py             # Resume version history
```

---

## Technology Stack

### Frontend Framework
- **Streamlit** (v1.36.0+): Rapid Python web app framework for creating interactive UI
  - Built-in forms, file uploaders, metrics display
  - Session state management for user data persistence
  - Real-time rerun capability

### Backend Framework & Runtime
- **Python 3.8+**: Core programming language
- **SQLAlchemy** (v2.0.0+): ORM for database operations
- **Pydantic** (v2.0.0+): Data validation framework

### Authentication & Security
- **streamlit-authenticator** (v0.4.0+): Streamlit authentication extension
  - Password hashing using bcrypt-compatible algorithms
  - User session management

### LLM Integration
- **Groq SDK** (v0.9.0+): Groq Cloud API client
  - Primary LLM provider for production
  - Uses Llama 3.1 8B Instant model
  - Temperature-controlled responses (0.2)
- **Ollama** (optional local deployment)
  - Alternative for local, self-hosted LLM inference
  - Llama 3.2 model support
  - HTTP REST API

### NLP & Semantic Processing
- **Sentence Transformers** (v3.0.0+)
  - Model: `all-MiniLM-L6-v2` (lightweight embeddings)
  - Purpose: Semantic similarity scoring
  - Enables nuanced profile-to-JD matching beyond keyword matching

### File Processing
- **pdfplumber** (v0.11.0+): PDF parsing and text extraction
  - Page-by-page extraction for multi-page JDs
- **python-docx** (v1.1.0+): DOCX/Word document parsing
  - Paragraph-level extraction
- **WeasyPrint** (v62.0+): HTML-to-PDF conversion
  - Used for resume PDF export functionality

### Configuration & Environment
- **PyYAML** (v6.0.0+): YAML configuration file parsing
  - Loads LLM settings and thresholds
- **requests** (v2.31.0+): HTTP client for API calls
  - Ollama API communication

### Database
- **SQLite** (default, via SQLAlchemy)
  - File-based database (serverless)
  - No external DB server required
  - Good for single-user/small-scale deployments

---

## Core Modules

### 1. **auth/auth_config.py** - Authentication Module

**Purpose**: Handle user registration, login, and session management

**Key Functions**:
- `hash_password(password: str) -> str`: Securely hash passwords using bcrypt
- `ensure_user_exists(username, email, password)`: Register new users with validation
- `authenticate_user(username, password)`: Login validation and user retrieval
- `logout()`: Clear user session state

**Data Flow**:
```
User Input → Validation → Hash Generation → DB Write
    ↓
Password Check → Hasher Comparison → Session State Update
```

### 2. **core/llm_client.py** - LLM Integration

**Purpose**: Abstract LLM API interactions, support multiple providers

**Architecture**:
```python
class LLMClient:
    - Provider: Groq (primary) or Ollama (fallback)
    - Configuration: Loaded from config.yaml
    - Method: generate(prompt: str) -> str
```

**Supported Providers**:

| Provider | Model | Speed | Cost | Setup |
|----------|-------|-------|------|-------|
| Groq | Llama 3.1 8B Instant | Very Fast (< 1s) | Cheap | API Key Required |
| Ollama | Llama 3.2 | Depends on Hardware | Free | Local Installation |

**Key Implementations**:
- `_generate_with_groq()`: Uses Groq SDK for cloud inference
- `_generate_with_ollama()`: HTTP POST to Ollama endpoint
- Temperature: 0.2 (deterministic, focused responses)

**Error Handling**:
- Returns error message if API key missing
- Falls back gracefully if provider unavailable
- Timeout: 120 seconds for Ollama

### 3. **core/matcher.py** - Profile-JD Matching

**Purpose**: Calculate semantic and keyword-based matching between profiles and jobs

**Algorithms**:

#### A. Keyword-Based Matching
```python
def compute_match_score():
    # Tokenization: Extract alphanumeric terms
    tokens = re.findall(r"[a-zA-Z0-9+#.-]+", text.lower())
    
    # Overlap calculation
    keyword_score = (overlap / total_jd_tokens) * 100
    # Result: Percentage of JD keywords found in profile
```

#### B. Semantic Similarity (Weighted)
```python
# Embedding generation
embeddings = SentenceTransformer.encode([profile, jd])

# Cosine similarity
similarity = dot(embedding_profile, embedding_jd) / (norm(profile) * norm(jd))

# Normalization to 0-100 range
similarity_score = similarity * 100
```

#### C. Combined Score (Weighted Average)
```
Final Score = (semantic_score × 0.7) + (keyword_score × 0.3)
```

**Model Details**:
- **Sentence Transformer**: `all-MiniLM-L6-v2`
  - 384-dimensional embeddings
  - Lightweight (~22 MB)
  - Trained on semantic textual similarity tasks

**Output**: Float between 0.0 and 100.0

### 4. **core/ats_scorer.py** - ATS Optimization Scoring

**Purpose**: Evaluate resume ATS-friendliness and identify missing elements

**Scoring Components**:

| Component | Weight | Calculation |
|-----------|--------|-------------|
| Keyword Density | 50% | Matched JD keywords / Total JD keywords |
| Section Presence | 25% | +25 for each: experience, skills, education, summary |
| Qualitative Assessment | 25% | LLM evaluation of resume quality |

**Keyword Extraction**:
- Extracts > 2 character terms from JD
- Identifies missing keywords in resume
- Limited to 10 most critical missing keywords

**LLM Evaluation Prompt**:
```
"Review the candidate resume against job description.
Provide short qualitative assessment and list missing keywords."
```

**Outputs**:
- ATS Score (0-100)
- Qualitative Summary (first 400 chars)
- Missing Keywords (list)

---

## Data Models

### Entity Relationship Diagram
```
┌─────────┐
│  User   │ (Primary entity)
└────┬────┘
     │
     ├─── has_one ──────────┬──────────┐
     │                      ▼          │
     │              ┌────────────┐     │
     │              │  Profile   │     │
     │              └────────────┘     │
     │                                 │
     ├─── has_many ──────────┬──────────┐
     │                       ▼          │
     │              ┌──────────────────┐│
     │              │ JobDescription   ││
     │              └──────────────────┘│
     │                      │           │
     └─── has_many ──┬──────┴───────────┘
                     ▼
            ┌──────────────────┐
            │  ResumeVersion   │
            └──────────────────┘
```

### 1. User Model
```python
@dataclass
class User:
    - id: Primary Key (auto-increment)
    - username: String(80), Unique, Not Null
    - email: String(120), Unique, Not Null
    - password_hash: String(255) [bcrypt]
    - is_active: Boolean (default: True)
    - created_at: DateTime (UTC timestamp)
    - Relationships:
        - profile: One-to-One (back_populates)
        - job_descriptions: One-to-Many
        - resume_versions: One-to-Many
```

### 2. Profile Model
```python
@dataclass
class Profile:
    - id: Primary Key
    - user_id: Foreign Key → User
    - Personal Info:
        - full_name, email, phone, location
    - Content Fields:
        - summary: Professional summary (Text)
        - skills: Comma-separated/formatted (Text)
        - experience: Work history (Text)
        - projects: Project descriptions (Text)
        - education: Degrees and certifications (Text)
        - certifications: Detailed certifications (Text)
        - achievements: Key achievements (Text)
    - Links:
        - github, linkedin, portfolio (URLs)
    - Timestamps:
        - created_at, updated_at (auto-managed)
```

### 3. JobDescription Model
```python
@dataclass
class JobDescription:
    - id: Primary Key
    - user_id: Foreign Key → User (Not Null)
    - title: String(200) - Job title
    - raw_text: Full JD text (Text)
    - Extracted Fields (LLM-parsed):
        - skills: Required skills (Text)
        - preferred_skills: Nice-to-have skills
        - experience: Experience requirements
        - technologies: Tech stack required
        - responsibilities: Job responsibilities
        - keywords: Extracted keywords
    - created_at: DateTime
```

### 4. ResumeVersion Model
```python
@dataclass
class ResumeVersion:
    - id: Primary Key
    - user_id: Foreign Key → User
    - job_description_id: Foreign Key → JobDescription (Nullable)
    - version_name: String(100) - e.g., "v1", "v2"
    - markdown_content: Full resume in Markdown (Text)
    - Scores:
        - match_score: Float (0-100)
        - ats_score: Float (0-100)
    - Analysis:
        - improvement_summary: Key improvements (Text)
        - missing_keywords: JSON list
    - created_at: DateTime
```

---

## Workflow & User Flows

### User Journey: Resume Tailoring

#### Step 1: Authentication
```
User → Signup/Login
    ↓
Username + Password Validation
    ↓
Session State Updated
    ↓
Redirected to Main App
```

#### Step 2: Profile Creation
```
User navigates to "Profile" page
    ↓
Form displays 14 fields:
  - Contact info (name, email, phone, location)
  - Content sections (summary, skills, experience, projects, education, certifications, achievements)
  - Social links (GitHub, LinkedIn, Portfolio)
    ↓
User saves profile
    ↓
Profile persisted to Database
```

#### Step 3: Job Description Upload
```
User navigates to "Upload JD" page
    ↓
File upload (PDF/DOCX) OR paste text
    ↓
System parses file:
  - PDF: pdfplumber extracts all pages
  - DOCX: python-docx extracts paragraphs
  - TXT: Direct text input
    ↓
LLM parses JD into structured fields:
  - Skills, Preferred Skills, Experience, Technologies, Responsibilities, Keywords
    ↓
JobDescription record created in DB
    ↓
JD ID stored in session
```

#### Step 4: Matching & Analysis
```
User navigates to "Match Score" page
    ↓
System fetches:
  - Latest user profile
  - Latest job description
    ↓
Compute Match Score (matcher.py):
  - Combine profile sections into text
  - Combine JD sections into text
  - Calculate semantic + keyword scores
    ↓
Display Match Score as metric
    ↓
LLM analysis prompt:
  "Review resume vs JD. Return JSON with:
   - strengths
   - missing_skills
   - missing_keywords
   - suggested_improvements"
    ↓
Parse JSON and display results
    ↓
If score < threshold (70%): Block resume generation
Else: Allow resume generation
```

#### Step 5: Resume Generation (with Iterative Loop)
```
User navigates to "Resume Generation" page
    ↓
Match score must be ≥ threshold
    ↓
Initialize iteration loop (max_iterations = 3)
    ↓
Iteration 1:
  - Prompt: "Generate tailored resume based on profile and JD"
  - LLM generates Markdown resume
  - Resume stored in ResumeVersion table
  - ATS Score calculated (ats_scorer.py)
    ↓
Check ATS Score:
  If < 95 AND iterations < 3:
    - Suggest improvements
    - Prompt LLM for next iteration
    - Go back to iteration loop
  Else:
    - Store final version
    - Display for user
    ↓
Export Options:
  - PDF (via WeasyPrint)
  - DOCX (via python-docx)
  - Markdown (raw text)
```

#### Step 6: Version History
```
User navigates to "History" page
    ↓
Fetch all ResumeVersion records for user
    ↓
Display table with:
  - Job title
  - Version name
  - Match score
  - ATS score
  - Created date
    ↓
Click to view/download specific version
```

---

## Key Algorithms

### 1. Match Score Computation Algorithm

**Input**: Profile text, Job Description text

**Process**:
```python
# Step 1: Tokenization
profile_tokens = set(tokenize(profile_text))
jd_tokens = set(tokenize(jd_text))

# Step 2: Keyword Overlap Scoring
overlap = len(profile_tokens & jd_tokens)
total = max(len(jd_tokens), 1)
keyword_score = min(100.0, (overlap / total) * 100.0)

# Step 3: Semantic Similarity
model = SentenceTransformer("all-MiniLM-L6-v2")
embeddings = model.encode([profile_text, jd_text])
similarity = cosine_similarity(embeddings[0], embeddings[1])
similarity_score = max(0, min(1, similarity)) * 100.0

# Step 4: Weighted Combination
final_score = (similarity_score * 0.7) + (keyword_score * 0.3)
```

**Output**: Float (0.0 - 100.0)

**Example**:
```
Profile: "Python, Machine Learning, TensorFlow, 5 years experience"
JD: "Python developer, ML engineer, TensorFlow, Scikit-learn required"

Keyword Score = 3/4 * 100 = 75%
Semantic Score = 0.92 * 100 = 92%
Final Score = (92 * 0.7) + (75 * 0.3) = 64.4 + 22.5 = 86.9%
```

### 2. ATS Score Calculation

**Input**: Resume text, Job Description text

**Process**:
```python
# Component 1: Keyword Density
jd_terms = extract_terms(jd_text)  # terms > 2 chars
keyword_hits = [term for term in jd_terms if term in resume]
keyword_density = min(100, len(keyword_hits) / len(jd_terms) * 100)

# Component 2: Section Presence
section_score = 0
for section in ["experience", "skills", "education", "summary"]:
    if section in resume.lower():
        section_score += 25  # 4 sections = 100 max

# Component 3: Qualitative (LLM-based)
qualitative_score = 50  # Baseline

# Component 4: Final Score
ats_score = min(100, keyword_density + section_score * 0.5)

# Component 5: Missing Keywords
missing_keywords = [term for term in jd_terms if term not in resume][:10]
```

**Output**:
- ATS Score (0-100)
- Summary of findings
- Top 10 missing keywords

### 3. Resume Generation Iteration Algorithm

**Purpose**: Iteratively improve resume until ATS score ≥ 95%

**Max Iterations**: 3 (configurable)

**Iteration Logic**:
```python
iteration = 1
resume_content = None

while iteration <= MAX_ITERATIONS:
    if iteration == 1:
        prompt = f"""
Generate a professional tailored resume based on:
Profile: {profile_text}
Job Description: {jd_text}

Return Markdown format with sections: Summary, Skills, Experience, Projects, Education
"""
    else:
        prompt = f"""
Improve the following resume to increase ATS compatibility:
Current Resume: {resume_content}
Job Description: {jd_text}

Focus on: Including more JD keywords, Strengthening match, Adding missing technologies
"""
    
    # Generate resume
    resume_content = llm_client.generate(prompt)
    
    # Score resume
    ats_score, summary, missing_keywords = score_resume(resume_content, jd_text)
    
    # Store version
    save_resume_version(resume_content, ats_score, summary, missing_keywords)
    
    # Check termination
    if ats_score >= 95 or iteration >= MAX_ITERATIONS:
        break
    
    iteration += 1
```

---

## Configuration

### config.yaml Structure

```yaml
llm:
  provider: "groq"  # Options: "groq", "ollama"
  
  groq:
    model: "llama-3.1-8b-instant"
    api_key: "${GROQ_API_KEY}"  # Load from environment variable
  
  ollama:
    model: "llama3.2"
    base_url: "http://localhost:11434"

thresholds:
  match_score: 70          # Minimum score to enable resume generation
  ats_score: 95            # Target ATS score for iterations
  max_iterations: 3        # Maximum resume generation iterations
```

### Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `GROQ_API_KEY` | Yes (if using Groq) | Authentication for Groq API |
| `DATABASE_URL` | No | Override default SQLite path |

### Threshold Configuration

- **match_score (70)**: If user profile doesn't match JD well enough, block resume generation to prevent poor results
- **ats_score (95)**: Target for resume optimization; if achieved, stop iterating
- **max_iterations (3)**: Prevent excessive API calls and ensure reasonable generation time

---

## API Integration

### Groq API Integration

**Endpoint**: Proprietary (via SDK)

**SDK**: `groq>=0.9.0`

**Configuration**:
```python
from groq import Groq

client = Groq(api_key=GROQ_API_KEY)
response = client.chat.completions.create(
    model="llama-3.1-8b-instant",
    messages=[{"role": "user", "content": prompt}],
    temperature=0.2
)
```

**Advantages**:
- Fast inference (< 1 second typical)
- Cost-effective pricing
- No local resource requirements
- Production-ready reliability

**Pricing Estimate**: ~$0.01-0.05 per resume generation (3 iterations)

### Ollama Integration (Optional)

**Endpoint**: `http://localhost:11434/api/generate`

**Request Format**:
```json
POST /api/generate
{
  "model": "llama3.2",
  "prompt": "...",
  "stream": false
}
```

**Response**: `{ "response": "..." }`

**Setup**:
```bash
# Install Ollama
# Download model: ollama pull llama3.2
# Run server: ollama serve
```

**Advantages**:
- No API costs
- Runs locally (privacy-friendly)
- Customizable models

**Disadvantages**:
- Requires local GPU/resources
- Slower than Groq (~10-30 seconds)

---

## Database Schema

### SQLite Schema (Auto-generated by SQLAlchemy)

```sql
-- Users Table
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(80) UNIQUE NOT NULL,
    email VARCHAR(120) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Profiles Table
CREATE TABLE profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER UNIQUE NOT NULL,
    full_name VARCHAR(200),
    email VARCHAR(200),
    phone VARCHAR(50),
    location VARCHAR(200),
    summary TEXT,
    skills TEXT,
    experience TEXT,
    projects TEXT,
    education TEXT,
    certifications TEXT,
    achievements TEXT,
    github VARCHAR(300),
    linkedin VARCHAR(300),
    portfolio VARCHAR(300),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Job Descriptions Table
CREATE TABLE job_descriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title VARCHAR(200),
    raw_text TEXT,
    skills TEXT,
    preferred_skills TEXT,
    experience TEXT,
    technologies TEXT,
    responsibilities TEXT,
    keywords TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Resume Versions Table
CREATE TABLE resume_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    job_description_id INTEGER,
    version_name VARCHAR(100),
    markdown_content TEXT,
    match_score VARCHAR(20),
    ats_score VARCHAR(20),
    improvement_summary TEXT,
    missing_keywords TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (job_description_id) REFERENCES job_descriptions(id)
);

-- Indexes for optimization
CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_profiles_user_id ON profiles(user_id);
CREATE INDEX idx_jd_user_id ON job_descriptions(user_id);
CREATE INDEX idx_resume_user_id ON resume_versions(user_id);
CREATE INDEX idx_resume_jd_id ON resume_versions(job_description_id);
```

### Data Volume Estimates

| Table | Typical Records | Storage |
|-------|-----------------|---------|
| users | 10-1000 | < 1 MB |
| profiles | 10-1000 | 1-10 MB |
| job_descriptions | 50-5000 | 10-50 MB |
| resume_versions | 100-10000 | 20-100 MB |
| **Total** | - | **30-160 MB** |

---

## Dependencies

### Core Dependencies

| Package | Version | Purpose | Size |
|---------|---------|---------|------|
| streamlit | ≥1.36.0 | Web framework | ~150 MB |
| streamlit-authenticator | ≥0.4.0 | Auth UI | ~2 MB |
| SQLAlchemy | ≥2.0.0 | ORM | ~3 MB |
| Pydantic | ≥2.0.0 | Data validation | ~2 MB |
| PyYAML | ≥6.0.0 | Config parsing | ~1 MB |
| sentence-transformers | ≥3.0.0 | Embeddings | ~300 MB |
| pdfplumber | ≥0.11.0 | PDF parsing | ~5 MB |
| python-docx | ≥1.1.0 | DOCX handling | ~3 MB |
| weasyprint | ≥62.0 | PDF generation | ~10 MB |
| requests | ≥2.31.0 | HTTP client | ~3 MB |
| groq | ≥0.9.0 | Groq SDK | ~2 MB |
| numpy | (transitive) | Numerical ops | ~100 MB |
| **Total** | - | - | **~580 MB** |

### Optional Dependencies

- **ollama**: For local LLM inference (requires separate installation)
- **torch**: Required by sentence-transformers (auto-installed, ~500 MB)

### System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| Python | 3.8+ | 3.10+ |
| RAM | 2 GB | 8 GB |
| Disk | 1 GB | 5 GB |
| OS | Windows/Mac/Linux | Linux |
| GPU | Not required | NVIDIA (CUDA) for Ollama |

---

## Installation & Setup

### Quick Start

#### 1. Clone Repository
```bash
cd c:\Users\acer\Documents\Nithin\project\jobaa
```

#### 2. Create Virtual Environment
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Mac/Linux
source .venv/bin/activate
```

#### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

#### 4. Configure Environment

Create `.env` file:
```
GROQ_API_KEY=your_groq_api_key_here
```

Or set system environment variable:
```bash
# Windows (PowerShell)
$env:GROQ_API_KEY = "your_key_here"

# Linux/Mac
export GROQ_API_KEY="your_key_here"
```

#### 5. Get Groq API Key
1. Visit https://console.groq.com
2. Sign up / Log in
3. Create API key
4. Copy and paste into `.env`

#### 6. Initialize Database
```bash
python -c "from db.session import init_db; init_db()"
```

#### 7. Run Application
```bash
streamlit run app.py
```

The app will be available at `http://localhost:8501`

### Advanced Setup: Using Ollama (Optional)

#### Install Ollama
1. Download from https://ollama.ai
2. Install and run: `ollama serve`

#### Pull Model
```bash
ollama pull llama3.2
```

#### Update config.yaml
```yaml
llm:
  provider: "ollama"  # Change from "groq"
  ollama:
    model: "llama3.2"
    base_url: "http://localhost:11434"
```

---

## Deployment Considerations

### Development Deployment (Local)
```
Hardware: Laptop/Desktop
Database: SQLite (file-based)
LLM: Groq Cloud API (free tier available)
Users: Single user / small team
Setup Time: 5-10 minutes
Cost: Free (with Groq free tier)
```

### Production Deployment (Small Scale)
```
Hosting: Streamlit Cloud / Heroku / AWS EC2
Database: PostgreSQL (upgrade from SQLite)
LLM: Groq API (paid tier) or self-hosted Ollama
Users: 10-100 concurrent users
Setup Time: 30-60 minutes
Cost: $20-100/month
```

### Production Deployment (Large Scale)
```
Hosting: Kubernetes / Docker Swarm
Database: PostgreSQL (with replication)
LLM: Self-hosted Ollama (multi-GPU) + Groq API (fallback)
Users: 100+ concurrent users
Setup Time: 1-2 weeks
Cost: $100-1000/month
Load Balancing: Nginx / AWS ALB
Caching: Redis for sessions
Monitoring: Prometheus + Grafana
```

### Docker Deployment Example

**Dockerfile**:
```dockerfile
FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501"]
```

**docker-compose.yml**:
```yaml
version: '3.8'
services:
  joba:
    build: .
    ports:
      - "8501:8501"
    environment:
      GROQ_API_KEY: ${GROQ_API_KEY}
    volumes:
      - ./db:/app/db
```

### Performance Optimization

| Bottleneck | Solution |
|------------|----------|
| Slow embedding calculation | Use GPU for sentence-transformers |
| LLM latency | Cache common prompts, use Groq |
| Database queries | Add indexes, use connection pooling |
| Large file uploads | Implement chunked uploads |
| Memory usage | Limit concurrent session size |

### Security Considerations

1. **Authentication**: 
   - ✅ Passwords hashed (bcrypt)
   - ✅ Session-based with Streamlit
   - ⚠️ Consider 2FA for production

2. **Data Privacy**:
   - ✅ User data isolated by user_id
   - ⚠️ Encrypt database at rest
   - ⚠️ Use HTTPS for API calls

3. **API Security**:
   - ✅ API keys in environment variables
   - ⚠️ Implement rate limiting
   - ⚠️ Use VPN for Ollama local access

4. **File Uploads**:
   - ✅ Temp files auto-deleted
   - ⚠️ Validate file types/sizes
   - ⚠️ Scan for malware

---

## Troubleshooting Guide

### Common Issues

#### 1. Groq API Key Error
**Problem**: "Groq API key is not configured"
**Solution**:
```bash
# Verify key is set
echo $GROQ_API_KEY

# Or add to .env file
GROQ_API_KEY=gsk_xxxxx
```

#### 2. Ollama Connection Refused
**Problem**: "Ollama service is not available"
**Solution**:
```bash
# Start Ollama service
ollama serve

# Verify in new terminal
curl http://localhost:11434/api/generate -X POST
```

#### 3. Database Locked Error
**Problem**: "database is locked"
**Solution**:
```python
# Multiple concurrent writes in SQLite
# Use PostgreSQL for production
# Or set timeout: engine = create_engine("sqlite:///jobaa.db?timeout=20")
```

#### 4. Out of Memory
**Problem**: Slow responses or crashes with large files
**Solution**:
- Limit file upload size
- Process PDFs in chunks
- Use smaller embedding model

#### 5. PDF Extraction Failed
**Problem**: "Cannot extract text from PDF"
**Solution**:
- Verify PDF is not scanned image
- Try pdfplumber settings: `pages=[0]` for first page only

---

## Future Enhancements

1. **Multi-Resume Comparison**: Compare multiple resumes side-by-side
2. **Job Market Insights**: Analytics on trending skills by role
3. **Interview Prep**: Generate interview questions based on resume + JD
4. **Cover Letter Generation**: Auto-generate tailored cover letters
5. **Collaborative Editing**: Team-based resume refinement
6. **Real-time Collaboration**: WebSocket support for live editing
7. **CV Export Formats**: LaTeX, JSON, XML support
8. **AI-Powered Feedback**: Real-time suggestions while editing profile
9. **Job Matching Engine**: Recommend jobs based on profile
10. **Analytics Dashboard**: User insights and usage statistics

---

## API Reference

### Key Functions by Module

#### auth_config.py
```python
hash_password(password: str) -> str
ensure_user_exists(username: str, email: str, password: str) -> User
authenticate_user(username: str, password: str) -> User | None
logout() -> None
```

#### matcher.py
```python
tokenize(text: str) -> List[str]
compute_match_score(profile_text: str, jd_text: str) -> float
get_model() -> SentenceTransformer
```

#### ats_scorer.py
```python
score_resume(resume_text: str, jd_text: str) -> Tuple[float, str, List[str]]
# Returns: (ats_score, summary, missing_keywords)
```

#### llm_client.py
```python
LLMClient.generate(prompt: str) -> str
LLMClient._generate_with_groq(prompt: str) -> str
LLMClient._generate_with_ollama(prompt: str) -> str
```

---

## Contributing Guidelines

### Code Style
- Python 3.8+
- Type hints for all functions
- PEP 8 compliance
- Docstrings for modules and functions

### Testing
```bash
pytest tests/ -v
pytest tests/test_matcher.py --cov
```

### Commit Messages
```
format: type(module): brief description

Types: feat, fix, docs, style, refactor, test, chore
Example: feat(matcher): add semantic similarity scoring
```

---

## License & Credits

**Project**: Joba - AI Resume Tailoring Tool
**Version**: 1.0.0
**Status**: Active Development

**Key Libraries**: Streamlit, SQLAlchemy, Sentence Transformers, Groq, pdfplumber

---

## Support & Contact

For issues, feature requests, or questions:
- Create an issue on GitHub
- Email: support@joba.ai
- Documentation: /docs

---

## Changelog

### v1.0.0 (Current)
- ✅ Basic authentication system
- ✅ Profile management
- ✅ Job description upload + parsing
- ✅ Semantic matching algorithm
- ✅ ATS scoring
- ✅ Resume generation with iteration
- ✅ Multi-format export (PDF, DOCX, Markdown)
- ✅ Version history tracking

### Future Versions
- v1.1.0: Interview prep module
- v1.2.0: Collaborative features
- v2.0.0: Job recommendation engine

---

## Appendix

### A. Glossary
- **ATS**: Applicant Tracking System
- **JD**: Job Description
- **LLM**: Large Language Model
- **ORM**: Object-Relational Mapping
- **Embedding**: Numerical vector representation of text
- **Semantic Similarity**: Meaning-based text comparison
- **Groq**: Cloud inference platform for LLMs

### B. Quick Reference Commands

```bash
# Development
streamlit run app.py

# Production
streamlit run app.py --logger.level=error

# Testing database
sqlite3 jobaa.db ".tables"
sqlite3 jobaa.db "SELECT COUNT(*) FROM users;"

# Environment setup
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

# API Testing
curl -X POST http://localhost:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{"model": "llama3.2", "prompt": "Hello", "stream": false}'
```

### C. File Size Reference

| Component | Size |
|-----------|------|
| Application Code | ~50 KB |
| Dependencies | ~580 MB |
| Sentence Transformer Model | ~300 MB |
| Sample Database (1000 users) | ~50 MB |
| **Total Installation** | **~930 MB** |

---

**Last Updated**: 2026-07-02
**Documentation Version**: 1.0.0

