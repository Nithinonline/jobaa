import json
from unittest.mock import patch

from core.jd_parser import (
    ParsedJobDescription,
    _deserialize_list,
    _extract_json_object,
    _serialize_list,
    format_jd_for_prompt,
    get_priority_keywords,
    job_description_to_parsed,
    parse_job_description,
    parsed_to_db_fields,
)


def test_extract_json_object_from_fenced_response() -> None:
    text = """Here is the JSON:
```json
{"title": "Engineer", "required_skills": ["Python", "SQL"]}
```"""
    data = _extract_json_object(text)
    assert data["title"] == "Engineer"
    assert data["required_skills"] == ["Python", "SQL"]


def test_parsed_job_description_coerces_string_lists() -> None:
    parsed = ParsedJobDescription.model_validate({
        "title": "Dev",
        "required_skills": "Python, SQL, Docker",
        "keywords": '["AWS", "Kubernetes"]',
    })
    assert parsed.required_skills == ["Python", "SQL", "Docker"]
    assert parsed.keywords == ["AWS", "Kubernetes"]


def test_serialize_deserialize_roundtrip() -> None:
    values = ["Python", "SQL", "Docker"]
    serialized = _serialize_list(values)
    assert _deserialize_list(serialized) == values


def test_parsed_to_db_fields() -> None:
    parsed = ParsedJobDescription(
        title="Backend Engineer",
        required_skills=["Python"],
        preferred_skills=["Go"],
        experience_years="3+ years",
        technologies=["AWS"],
        responsibilities=["Build APIs"],
        keywords=["microservices"],
    )
    fields = parsed_to_db_fields(parsed)
    assert json.loads(fields["skills"]) == ["Python"]
    assert fields["experience"] == "3+ years"
    assert json.loads(fields["keywords"]) == ["microservices"]


def test_parse_job_description_fallback_on_invalid_json() -> None:
    with patch("core.jd_parser.llm_client.generate", return_value="not json at all"):
        parsed = parse_job_description("Some job description text")
    assert parsed.title == ""
    assert parsed.required_skills == []


def test_format_jd_for_prompt_prioritizes_keywords() -> None:
    class FakeJD:
        title = "Software Engineer"
        raw_text = "Full JD body"
        skills = json.dumps(["Python", "FastAPI"])
        preferred_skills = json.dumps(["GraphQL"])
        experience = "3+ years"
        technologies = json.dumps(["AWS", "Docker"])
        responsibilities = json.dumps(["Design APIs"])
        keywords = json.dumps(["microservices", "REST"])

    prompt = format_jd_for_prompt(FakeJD())
    assert "Required Skills: Python, FastAPI" in prompt
    assert "Priority Keywords: microservices, REST" in prompt
    assert "Full Job Description:" in prompt


def test_get_priority_keywords_deduplicates() -> None:
    class FakeJD:
        title = "Role"
        raw_text = ""
        skills = json.dumps(["Python"])
        preferred_skills = json.dumps(["python", "SQL"])
        experience = ""
        technologies = json.dumps(["AWS"])
        responsibilities = json.dumps([])
        keywords = json.dumps(["Python"])

    keywords = get_priority_keywords(FakeJD(), limit=5)
    assert keywords == ["Python", "AWS", "SQL"]


def test_job_description_to_parsed() -> None:
    class FakeJD:
        title = "Analyst"
        skills = json.dumps(["Excel"])
        preferred_skills = json.dumps([])
        experience = "2 years"
        technologies = json.dumps([])
        responsibilities = json.dumps([])
        keywords = json.dumps(["reporting"])

    parsed = job_description_to_parsed(FakeJD())
    assert parsed.title == "Analyst"
    assert parsed.required_skills == ["Excel"]
    assert parsed.keywords == ["reporting"]
