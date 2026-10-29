from core.resume_validator import validate_exported_resume


def test_validate_exported_resume_keyword_check() -> None:
    # validate_exported_resume expects file bytes; use a minimal valid PDF path via text checks
    from core.resume_validator import _check_keywords

    text = "Professional Summary Python expert. Skills Python, SQL."
    issues = _check_keywords(text, ["python", "sql", "aws", "docker"])
    assert issues
    assert any("keyword" in issue.lower() for issue in issues)
