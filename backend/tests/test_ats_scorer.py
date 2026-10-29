from core.ats_scorer import validate_ats_format


def test_validate_ats_format_rejects_tables_and_multicolumn_layout() -> None:
    resume = """
# Candidate
| Skill | Level |
| --- | --- |
| Python | Expert |
"""
    is_valid, reasons = validate_ats_format(resume)
    assert is_valid is False
    assert any("table" in reason.lower() for reason in reasons)


def test_validate_ats_format_requires_standard_headings() -> None:
    resume = """
## Professional Summary
Experienced engineer.
## Skills
Python, SQL.
## Work Experience
### Engineer
Acme Corp, TX | January 2020 - Present
- Built APIs.
## Education
### B.S. Computer Science
State University, TX | May 2019
"""
    is_valid, reasons = validate_ats_format(resume)
    assert is_valid is True
    assert reasons == []


def test_validate_ats_format_rejects_bad_dates() -> None:
    resume = """
## Professional Summary
Summary text.
## Skills
Python.
## Work Experience
### Engineer
Acme Corp | Jan 2020 - Present
- Did work.
## Education
B.S. CS
"""
    is_valid, reasons = validate_ats_format(resume)
    assert is_valid is False
    assert any("date" in reason.lower() or "month" in reason.lower() for reason in reasons)


def test_validate_ats_format_accepts_aliases() -> None:
    resume = """
## Summary
Experienced engineer.
## Skills
Python, SQL.
## Experience
### Engineer
Acme Corp | January 2020 - Present
- Built APIs.
## Education
B.S. CS | May 2019
"""
    is_valid, reasons = validate_ats_format(resume)
    assert is_valid is True
