# Joba - API Reference & Integration Guide

## Table of Contents
1. [Core Module APIs](#core-module-apis)
2. [LLM Prompts & Templates](#llm-prompts--templates)
3. [Database Operations](#database-operations)
4. [File Processing APIs](#file-processing-apis)
5. [Integration Patterns](#integration-patterns)
6. [Common Use Cases](#common-use-cases)
7. [Extending Joba](#extending-joba)

---

## Core Module APIs

### auth/auth_config.py

#### `hash_password(password: str) -> str`
**Purpose**: Securely hash a password using bcrypt algorithm

**Parameters**:
- `password` (str): Plaintext password to hash

**Returns**:
- str: Hashed password (bcrypt format)

**Example**:
```python
from auth.auth_config import hash_password

hashed = hash_password("MyPassword123!")
# Returns: "$2b$12$R9h7cIPz0gi.URNNGHQ1m...."
```

**Error Handling**:
- No exceptions raised (wrapper around stauth)

---

#### `ensure_user_exists(username: str, email: str, password: str) -> User`
**Purpose**: Create a new user account with validation

**Parameters**:
- `username` (str): Unique username (alphanumeric, 3-80 chars)
- `email` (str): Unique email address (valid format)
- `password` (str): Plaintext password

**Returns**:
- User: Created User object with id, username, email, password_hash

**Raises**:
- ValueError: If username/email already exists

**Example**:
```python
from auth.auth_config import ensure_user_exists

try:
    user = ensure_user_exists("john_doe", "john@example.com", "secure123")
    print(f"User created: {user.id}")
except ValueError as e:
    print(f"Registration failed: {e}")
    # Error: "A user with that username or email already exists."
```

**Database Impact**:
- Inserts row into `users` table
- Commits automatically

---

#### `authenticate_user(username: str, password: str) -> User | None`
**Purpose**: Verify credentials and return authenticated user

**Parameters**:
- `username` (str): Username to authenticate
- `password` (str): Plaintext password to verify

**Returns**:
- User: Authenticated user object (if credentials valid)
- None: If username not found or password incorrect

**Example**:
```python
from auth.auth_config import authenticate_user

user = authenticate_user("john_doe", "secure123")
if user:
    print(f"Logged in as: {user.username}")
    # Use user.id for subsequent operations
else:
    print("Invalid credentials")
```

---

#### `logout() -> None`
**Purpose**: Clear user session and log out

**Implementation**:
```python
def logout() -> None:
    if "user" in st.session_state:
        del st.session_state["user"]
```

**Streamlit Integration**:
- Must be called as `on_click` callback of logout button
- Triggers page rerun to show auth screen

---

### core/matcher.py

#### `tokenize(text: str) -> List[str]`
**Purpose**: Extract alphanumeric tokens from text (case-insensitive)

**Parameters**:
- `text` (str): Input text to tokenize

**Returns**:
- List[str]: List of extracted tokens

**Regex Pattern**: `[a-zA-Z0-9+#.-]+`

**Example**:
```python
from core.matcher import tokenize

text = "Python, C++, Node.js (v18.0)"
tokens = tokenize(text)
# Returns: ['python', 'c', 'node', 's', 'v18', '0']
```

**Features**:
- Lowercase conversion
- Preserves: alphanumeric, +, #, ., -
- Removes: spaces, punctuation (except above)

---

#### `compute_match_score(profile_text: str, jd_text: str) -> float`
**Purpose**: Calculate profile-to-JD matching score (0-100%)

**Parameters**:
- `profile_text` (str): Concatenated profile data
- `jd_text` (str): Concatenated JD data

**Returns**:
- float: Match score (0.0 - 100.0), rounded to 1 decimal

**Algorithm**:
```
1. Tokenize both texts
2. Calculate keyword overlap %
   keyword_score = (overlap / total_jd_tokens) * 100
3. Generate embeddings using all-MiniLM-L6-v2
4. Calculate cosine similarity
   similarity_score = similarity * 100
5. Weighted combination
   final_score = (similarity_score × 0.7) + (keyword_score × 0.3)
```

**Example**:
```python
from core.matcher import compute_match_score

profile = "Python, Machine Learning, TensorFlow, 5 years"
jd = "Python developer, ML engineer, TensorFlow required"

score = compute_match_score(profile, jd)
print(f"Match: {score}%")  # Output: Match: 86.9%
```

**Performance**:
- First call: ~3-8 seconds (model loading)
- Subsequent calls: ~1-2 seconds (cached model)

**Note**: Model stored globally in `_model` variable (lazy-loaded)

---

#### `get_model() -> SentenceTransformer`
**Purpose**: Get or initialize sentence transformer model

**Returns**:
- SentenceTransformer: `all-MiniLM-L6-v2` model instance

**Implementation**:
```python
_model = None

def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model
```

**Model Details**:
- Name: all-MiniLM-L6-v2
- Dimensions: 384
- Size: ~22 MB
- First Load: ~300 MB (downloads from HuggingFace)
- Cache: ~/.cache/huggingface/

---

### core/ats_scorer.py

#### `score_resume(resume_text: str, jd_text: str) -> Tuple[float, str, List[str]]`
**Purpose**: Calculate ATS compatibility score and improvement suggestions

**Parameters**:
- `resume_text` (str): Full resume content
- `jd_text` (str): Full job description content

**Returns**:
- Tuple containing:
  1. float: ATS score (0-100)
  2. str: Qualitative summary (max 400 chars)
  3. List[str]: Top 10 missing keywords

**Scoring Formula**:
```
keyword_density = (matched_keywords / total_jd_keywords) × 100
section_presence = (sections_found × 25) [max 100, 4 sections]

ats_score = min(100.0, keyword_density + (section_presence × 0.5))

Sections checked: "experience", "skills", "education", "summary"
```

**Example**:
```python
from core.ats_scorer import score_resume

resume = """
JOHN DOE
Professional Summary: Experienced Python developer...
Skills: Python, Django, PostgreSQL, AWS
Experience: 5 years at Tech Corp...
Education: BS Computer Science
"""

jd = """
Python Backend Engineer
Required: Python, Django, PostgreSQL, Docker, Kubernetes
"""

score, summary, missing = score_resume(resume, jd)
print(f"ATS Score: {score}")
print(f"Summary: {summary}")
print(f"Missing: {missing}")
# Output:
# ATS Score: 78.5
# Summary: Resume covers core technologies...
# Missing: ['docker', 'kubernetes', 'rest', 'microservices']
```

**LLM Integration**:
- Uses `llm_client.generate()` for qualitative assessment
- Prompt template provided to LLM
- Temperature: 0.2 (deterministic)

**Missing Keywords**:
- Extracted from JD tokens not in resume
- Filtered to terms > 2 characters
- Limited to 10 keywords
- Sorted by relevance

---

### core/llm_client.py

#### `LLMClient` Class

**Initialization**:
```python
from core.llm_client import llm_client

# Singleton instance already created
# Configuration loaded from config.yaml
client = llm_client
```

---

#### `LLMClient.generate(prompt: str) -> str`
**Purpose**: Generate text response from LLM provider

**Parameters**:
- `prompt` (str): User prompt/instruction

**Returns**:
- str: Generated response

**Raises**:
- No exceptions, returns error message strings on failure

**Example**:
```python
from core.llm_client import llm_client

prompt = "Extract skills from this job description: ..."
response = llm_client.generate(prompt)
print(response)
```

**Provider Selection**:
```
If config.llm.provider == "groq":
    → calls _generate_with_groq()
Else if config.llm.provider == "ollama":
    → calls _generate_with_ollama()
Else:
    → defaults to Groq
```

---

#### `LLMClient._generate_with_groq(prompt: str) -> str`
**Purpose**: Generate using Groq Cloud API

**Configuration**:
- Model: `llama-3.1-8b-instant` (or configured value)
- API Key: `GROQ_API_KEY` environment variable
- Temperature: 0.2
- Role: "user"

**Implementation**:
```python
from groq import Groq

client = Groq(api_key=self.groq_api_key)
response = client.chat.completions.create(
    model=self.groq_model,
    messages=[{"role": "user", "content": prompt}],
    temperature=0.2,
)
return response.choices[0].message.content or ""
```

**Error Handling**:
- Returns "Groq API key is not configured." if key missing
- Returns "groq package is not installed." if import fails
- Returns empty string if no response

**Response Time**: ~100-500ms (typically)

---

#### `LLMClient._generate_with_ollama(prompt: str) -> str`
**Purpose**: Generate using local Ollama inference

**Configuration**:
- Model: `llama3.2` (or configured value)
- Base URL: `http://localhost:11434`
- Stream: false
- Timeout: 120 seconds

**HTTP Request**:
```python
import requests

response = requests.post(
    f"{self.ollama_base_url}/api/generate",
    json={
        "model": self.ollama_model,
        "prompt": prompt,
        "stream": False
    },
    timeout=120,
)
response.raise_for_status()
return response.json().get("response", "")
```

**Error Handling**:
- Returns "Ollama service is not available." on any exception
- Includes timeout handling

**Response Time**: 10-30 seconds (hardware dependent)

---

## LLM Prompts & Templates

### 1. Job Description Parsing

**Purpose**: Extract structured data from raw JD text

**Prompt Template**:
```python
prompt = f"""
You are extracting a structured job description. Use only the supplied text.
Return JSON with the fields: title, skills, preferred_skills, experience, 
technologies, responsibilities, keywords.
Text:
{raw_jd_text}
"""
```

**Expected Output Format**:
```json
{
  "title": "Senior Python Developer",
  "skills": "Python, Django, PostgreSQL, Redis",
  "preferred_skills": "Kubernetes, Docker, AWS",
  "experience": "5+ years backend development",
  "technologies": "Python, Django, PostgreSQL, Redis, Celery",
  "responsibilities": "Design and implement APIs, Code reviews, System architecture",
  "keywords": "Python, backend, API, microservices, REST"
}
```

**Stored In**: JobDescription table fields

---

### 2. Profile-JD Matching Analysis

**Purpose**: Compare profile against JD for gaps and strengths

**Prompt Template**:
```python
prompt = f"""
You are reviewing a resume profile against a job description.
Use only the provided profile data and job description text.
Return JSON with keys: strengths, missing_skills, missing_keywords, suggested_improvements.

Profile:
{profile_text}

Job Description:
{jd_text}
"""
```

**Expected Output Format**:
```json
{
  "strengths": [
    "Strong Python background with 5 years experience",
    "Database optimization expertise aligns with PostgreSQL requirement"
  ],
  "missing_skills": [
    "Kubernetes orchestration",
    "Docker containerization",
    "Microservices architecture"
  ],
  "missing_keywords": [
    "Kubernetes",
    "Docker",
    "microservices",
    "CI/CD"
  ],
  "suggested_improvements": [
    "Add Docker project experience to portfolio section",
    "Include Kubernetes certification",
    "Highlight any microservices work"
  ]
}
```

**Displayed In**: Match Score page

---

### 3. Resume Generation

**Purpose**: Create tailored resume for specific job

**Iteration 1 Prompt**:
```python
prompt = f"""
Generate a professional tailored resume based on:

Profile:
{profile_text}

Job Description:
{jd_text}

Return ONLY Markdown format with these sections:
# PROFESSIONAL SUMMARY
(2-3 sentences tailored to JD)

## SKILLS
(keywords from JD where applicable)

## PROFESSIONAL EXPERIENCE
(5-7 bullet points highlighting relevant accomplishments)

## PROJECTS
(2-3 projects related to JD requirements)

## EDUCATION
(degrees and relevant certifications)

## CERTIFICATIONS (if any)
"""
```

**Iteration N Prompt** (if ATS < 95):
```python
prompt = f"""
Improve the following resume to increase ATS compatibility and JD match:

Current Resume:
{current_resume_markdown}

Job Description:
{jd_text}

Focus on:
1. Including more JD keywords naturally
2. Strengthening relevance and match
3. Adding missing technologies mentioned in JD
4. Using action verbs and metrics

Return improved resume in Markdown format.
"""
```

**Output Format**: Markdown with headers (##, ###, ####)

---

### 4. ATS Qualitative Assessment

**Purpose**: Provide human-readable ATS feedback

**Prompt Template**:
```python
prompt = f"""
Review the candidate resume below against the job description. 
Use only the resume text and job description text supplied. 
Provide a short qualitative assessment and a list of missing keywords.

Resume:
{resume_text}

Job Description:
{jd_text}

Respond with:
1. Overall assessment (1-2 sentences)
2. Top 5 missing keywords
3. One suggestion for improvement
"""
```

**Expected Output**:
```
Resume demonstrates strong technical foundation with Python and Django 
experience. Lacks specific mention of Kubernetes and containerization 
technologies mentioned in the JD.

Missing Keywords: Kubernetes, Docker, microservices, CI/CD, Terraform

Suggestion: Add a project section highlighting containerization work or 
include Docker in the technologies section.
```

---

## Database Operations

### User Management

#### Create User
```python
from auth.auth_config import ensure_user_exists
from db.models import User

user = ensure_user_exists(
    username="john_doe",
    email="john@example.com",
    password="secure_password_123"
)
```

#### Authenticate User
```python
from auth.auth_config import authenticate_user

user = authenticate_user("john_doe", "secure_password_123")
if user:
    # Session management
    st.session_state.user = user
```

#### Query User
```python
from db.session import SessionLocal
from db.models import User

session = SessionLocal()
try:
    user = session.query(User).filter(User.id == 1).first()
    print(user.username, user.email)
finally:
    session.close()
```

---

### Profile Management

#### Get or Create Profile
```python
from db.session import SessionLocal
from db.models import Profile
import streamlit as st

session = SessionLocal()
try:
    profile = session.query(Profile)\
        .filter(Profile.user_id == st.session_state.user.id)\
        .first()
    
    if not profile:
        profile = Profile(user_id=st.session_state.user.id)
        session.add(profile)
        session.commit()
finally:
    session.close()
```

#### Update Profile
```python
profile.full_name = "John Doe"
profile.skills = "Python, JavaScript, React"
profile.experience = "5 years as senior developer"
session.commit()
```

#### Retrieve Profile
```python
profile = session.query(Profile)\
    .filter(Profile.user_id == user_id)\
    .first()

if profile:
    skills = profile.skills
    experience = profile.experience
```

---

### Job Description Management

#### Save Job Description
```python
from db.models import JobDescription
from core.llm_client import llm_client

# Parse JD with LLM
parse_prompt = f"Extract structured JD from: {raw_text}"
parsed_data = llm_client.generate(parse_prompt)

# Create record
jd = JobDescription(
    user_id=user_id,
    title="Senior Python Developer",
    raw_text=raw_text,
    skills=parsed_data['skills'],
    preferred_skills=parsed_data['preferred_skills'],
    experience=parsed_data['experience'],
    technologies=parsed_data['technologies'],
    responsibilities=parsed_data['responsibilities'],
    keywords=parsed_data['keywords']
)
session.add(jd)
session.commit()
```

#### Query Latest JD
```python
latest_jd = session.query(JobDescription)\
    .filter(JobDescription.user_id == user_id)\
    .order_by(JobDescription.id.desc())\
    .first()
```

#### List User's JDs
```python
jds = session.query(JobDescription)\
    .filter(JobDescription.user_id == user_id)\
    .all()

for jd in jds:
    print(f"{jd.title} - Created: {jd.created_at}")
```

---

### Resume Version Management

#### Save Resume Version
```python
from db.models import ResumeVersion

resume = ResumeVersion(
    user_id=user_id,
    job_description_id=jd_id,
    version_name="v1",
    markdown_content=generated_markdown,
    match_score=str(match_score),
    ats_score=str(ats_score),
    improvement_summary=summary,
    missing_keywords=",".join(missing_keywords)
)
session.add(resume)
session.commit()
```

#### Query Resume History
```python
resumes = session.query(ResumeVersion)\
    .filter(ResumeVersion.user_id == user_id)\
    .order_by(ResumeVersion.created_at.desc())\
    .all()

for r in resumes:
    print(f"v{r.version_name}: {r.ats_score}% ATS - {r.created_at}")
```

#### Get Best Resume
```python
best = session.query(ResumeVersion)\
    .filter(ResumeVersion.user_id == user_id)\
    .order_by(ResumeVersion.ats_score.desc())\
    .first()
```

---

## File Processing APIs

### PDF Processing

#### Extract Text from PDF
```python
import pdfplumber
import tempfile
from pathlib import Path

def extract_pdf_text(uploaded_file) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name
    
    try:
        with pdfplumber.open(tmp_path) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
            return "\n\n".join(pages)
    finally:
        os.unlink(tmp_path)

# Usage
pdf_text = extract_pdf_text(st.file_uploader())
```

**Features**:
- Handles multi-page PDFs
- Auto-cleans temp files
- Handles empty/corrupted pages
- Preserves page breaks

---

### DOCX Processing

#### Extract Text from DOCX
```python
from docx import Document
import tempfile

def extract_docx_text(uploaded_file) -> str:
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name
    
    try:
        doc = Document(tmp_path)
        return "\n".join(
            paragraph.text 
            for paragraph in doc.paragraphs 
            if paragraph.text
        )
    finally:
        os.unlink(tmp_path)

# Usage
docx_text = extract_docx_text(st.file_uploader())
```

---

### PDF Export (Resume to PDF)

#### Convert Markdown to PDF
```python
from weasyprint import HTML

def markdown_to_pdf_bytes(markdown_content: str) -> bytes:
    """Convert Markdown resume to PDF"""
    html = _markdown_to_html(markdown_content)
    return HTML(string=html).write_pdf()

# Usage
pdf_bytes = markdown_to_pdf_bytes(resume_markdown)
st.download_button(
    label="Download PDF",
    data=pdf_bytes,
    file_name="resume.pdf",
    mime="application/pdf"
)
```

---

### DOCX Export (Resume to DOCX)

#### Convert Markdown to DOCX
```python
from docx import Document
from io import BytesIO

def markdown_to_docx_bytes(markdown_content: str) -> bytes:
    """Convert Markdown resume to DOCX"""
    doc = Document()
    
    for line in markdown_content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            doc.add_heading(stripped[2:].strip(), level=1)
        elif stripped.startswith("## "):
            doc.add_heading(stripped[3:].strip(), level=2)
        elif stripped.startswith("### "):
            doc.add_heading(stripped[4:].strip(), level=3)
        elif stripped.startswith("- "):
            doc.add_paragraph(stripped[2:].strip(), style="List Bullet")
        elif stripped:
            doc.add_paragraph(stripped)
    
    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()

# Usage
docx_bytes = markdown_to_docx_bytes(resume_markdown)
st.download_button(
    label="Download DOCX",
    data=docx_bytes,
    file_name="resume.docx",
    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
```

---

## Integration Patterns

### Pattern 1: Custom Matching Algorithm

**Extend** core/matcher.py:
```python
def compute_advanced_match_score(profile, jd, weights=None):
    """Extended scoring with custom weights"""
    if weights is None:
        weights = {
            'semantic': 0.5,
            'keyword': 0.3,
            'domain': 0.2
        }
    
    # Calculate scores
    semantic = compute_semantic_score(profile, jd)
    keyword = compute_keyword_score(profile, jd)
    domain = compute_domain_score(profile, jd)
    
    # Weighted combination
    total = (semantic * weights['semantic'] + 
             keyword * weights['keyword'] + 
             domain * weights['domain'])
    
    return min(100, total)
```

---

### Pattern 2: Custom LLM Provider

**Create new provider** in core/llm_client.py:
```python
class LLMClient:
    def generate(self, prompt: str) -> str:
        if self.provider == "openai":
            return self._generate_with_openai(prompt)
        elif self.provider == "anthropic":
            return self._generate_with_anthropic(prompt)
        # ... existing providers
    
    def _generate_with_openai(self, prompt: str) -> str:
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )
        return response.choices[0].message.content or ""
```

---

### Pattern 3: Custom Page

**Add new page** in pages/custom_page.py:
```python
import streamlit as st
from db.session import SessionLocal
from db.models import User, Profile

def render_custom_page() -> None:
    st.title("Custom Feature")
    
    session = SessionLocal()
    try:
        # Your custom logic
        pass
    finally:
        session.close()

# In app.py, add to navigation:
elif page == "Custom":
    from pages.custom_page import render_custom_page
    render_custom_page()
```

---

## Common Use Cases

### Use Case 1: Single Resume Generation

```python
from core.matcher import compute_match_score
from core.ats_scorer import score_resume
from core.llm_client import llm_client
from db.session import SessionLocal
from db.models import Profile, JobDescription, ResumeVersion

# 1. Get profile and JD
session = SessionLocal()
profile = session.query(Profile).filter(...).first()
jd = session.query(JobDescription).filter(...).first()

# 2. Check match score
match = compute_match_score(profile_text, jd_text)
if match < 70:
    print("Profile too weak")
    return

# 3. Generate resume
resume_prompt = f"""Generate resume for:
Profile: {profile_text}
JD: {jd_text}"""
resume_md = llm_client.generate(resume_prompt)

# 4. Score resume
ats, summary, missing = score_resume(resume_md, jd_text)

# 5. Save version
version = ResumeVersion(
    user_id=user_id,
    job_description_id=jd.id,
    markdown_content=resume_md,
    ats_score=str(ats),
    improvement_summary=summary,
    missing_keywords=",".join(missing)
)
session.add(version)
session.commit()
```

---

### Use Case 2: Batch Resume Generation

```python
from db.session import SessionLocal
from db.models import JobDescription, ResumeVersion

session = SessionLocal()

# Get all JDs for user
jds = session.query(JobDescription)\
    .filter(JobDescription.user_id == user_id)\
    .all()

for jd in jds:
    # Generate for each JD
    resume_md = llm_client.generate(f"Generate for {jd.title}...")
    ats, summary, missing = score_resume(resume_md, jd.raw_text)
    
    # Save version
    version = ResumeVersion(...)
    session.add(version)
    
session.commit()
session.close()
```

---

### Use Case 3: Export Resume to Multiple Formats

```python
import streamlit as st
from pages.resume_gen import _markdown_to_pdf_bytes, _generate_docx_bytes

# Assuming resume_md is generated
resume_md = "# John Doe\n## Skills\n..."

# PDF
pdf_bytes = _markdown_to_pdf_bytes(resume_md)

# DOCX
docx_bytes = _generate_docx_bytes(resume_md)

# Markdown (raw)

# Download options
col1, col2, col3 = st.columns(3)
with col1:
    st.download_button("📄 PDF", pdf_bytes, "resume.pdf")
with col2:
    st.download_button("📝 DOCX", docx_bytes, "resume.docx")
with col3:
    st.download_button("✏️ Markdown", resume_md, "resume.md")
```

---

### Use Case 4: Analytics & Reporting

```python
from sqlalchemy import func
from db.session import SessionLocal
from db.models import User, ResumeVersion

session = SessionLocal()

# Total resumes generated
total_resumes = session.query(func.count(ResumeVersion.id)).scalar()

# Average ATS score
avg_ats = session.query(func.avg(ResumeVersion.ats_score)).scalar()

# Top JD
top_jd = session.query(JobDescription.title, func.count(ResumeVersion.id))\
    .join(ResumeVersion)\
    .group_by(JobDescription.id)\
    .order_by(func.count(ResumeVersion.id).desc())\
    .first()

print(f"Total Resumes: {total_resumes}")
print(f"Avg ATS Score: {avg_ats:.1f}")
print(f"Top JD: {top_jd[0]} ({top_jd[1]} resumes)")
```

---

## Extending Joba

### Feature: Interview Prep Module

**New file**: pages/interview_prep.py
```python
def render_interview_prep_page():
    st.title("Interview Preparation")
    
    session = SessionLocal()
    try:
        profile = session.query(Profile).filter(...).first()
        jd = session.query(JobDescription).filter(...).first()
        
        # Generate interview questions
        prompt = f"""
Generate 5 technical interview questions for {jd.title} role based on:
Profile: {profile.skills}
JD: {jd.raw_text}
"""
        questions = llm_client.generate(prompt)
        st.markdown(questions)
        
        # Generate answers
        if st.button("Generate Sample Answers"):
            answer_prompt = f"Generate answers for above questions..."
            answers = llm_client.generate(answer_prompt)
            st.markdown(answers)
    finally:
        session.close()

# Add to app.py navigation
```

---

### Feature: Cover Letter Generation

**New file**: pages/cover_letter.py
```python
def render_cover_letter_page():
    st.title("Cover Letter Generator")
    
    session = SessionLocal()
    try:
        profile = session.query(Profile).filter(...).first()
        jd = session.query(JobDescription).filter(...).first()
        
        if st.button("Generate Cover Letter"):
            prompt = f"""
Generate professional cover letter for {jd.title} position based on:
Profile: {profile.summary}
Company Requirements: {jd.raw_text}

Format: Formal business letter
"""
            cover_letter = llm_client.generate(prompt)
            st.markdown(cover_letter)
            
            # Export
            st.download_button(
                "Download Cover Letter",
                cover_letter.encode(),
                "cover_letter.txt"
            )
    finally:
        session.close()
```

---

### Feature: Skill Gap Analysis

**New file**: pages/skill_gap.py
```python
def render_skill_gap_page():
    st.title("Skill Gap Analysis")
    
    session = SessionLocal()
    try:
        profile = session.query(Profile).filter(...).first()
        jd = session.query(JobDescription).filter(...).first()
        
        # Analyze gaps
        prompt = f"""
Compare skills in profile vs JD requirements.
Return JSON with:
- have: skills user already has
- need: skills to acquire
- learning_resources: courses/resources for each
"""
        analysis = llm_client.generate(prompt)
        st.json(json.loads(analysis))
        
        # Learning recommendations
        if st.button("Get Learning Path"):
            learning_prompt = f"Create 3-month learning plan..."
            plan = llm_client.generate(learning_prompt)
            st.markdown(plan)
    finally:
        session.close()
```

---

**Version**: 1.0.0  
**Last Updated**: 2026-07-02  
**Status**: Complete API Reference

