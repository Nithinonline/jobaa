import json
from unittest.mock import patch

from core.resume_generator import _build_refinement_prompt, generate_resume


VALID_RESUME = """## Professional Summary
Experienced engineer.
## Skills
Python, SQL.
## Work Experience
### Engineer
Acme Corp, TX | January 2020 - Present
- Built APIs at Acme.
## Education
### B.S. Computer Science
State University, TX | May 2019
"""


def test_refinement_prompt_includes_missing_keywords() -> None:
    prompt = _build_refinement_prompt(
        markdown_content=VALID_RESUME,
        jd_prompt_text="JD text here",
        iteration=2,
        max_iterations=3,
        missing_keywords=["kubernetes", "docker"],
        format_issues=[],
        priority_keywords=["Python", "AWS"],
    )
    assert "kubernetes" in prompt
    assert "docker" in prompt
    assert "Priority skills" in prompt or "priority skills" in prompt.lower()
    assert "Iteration 2/3" in prompt


def test_refinement_prompt_includes_format_issues() -> None:
    prompt = _build_refinement_prompt(
        markdown_content=VALID_RESUME,
        jd_prompt_text="JD",
        iteration=2,
        max_iterations=3,
        missing_keywords=[],
        format_issues=["Missing standard heading(s): education"],
        priority_keywords=[],
    )
    assert "Missing standard heading(s): education" in prompt


def test_generate_resume_stops_at_target_score() -> None:
    call_count = {"n": 0}

    def fake_generate(prompt: str) -> str:
        call_count["n"] += 1
        return VALID_RESUME

    def fake_score(resume_text: str, jd_text: str, jd=None):
        return 96.0, "Good match", []

    with patch("core.resume_generator.llm_client.generate", side_effect=fake_generate), patch(
        "core.resume_generator.score_resume", side_effect=fake_score
    ), patch("core.resume_generator.get_thresholds", return_value={"ats_score": 95, "max_iterations": 3}):
        result = generate_resume("profile", "jd text", max_iterations=3)

    assert result["ats_score"] == 96.0
    assert call_count["n"] == 1


def test_generate_resume_refinement_uses_missing_keywords() -> None:
    prompts: list[str] = []
    score_calls = {"n": 0}

    def fake_generate(prompt: str) -> str:
        prompts.append(prompt)
        return VALID_RESUME

    def fake_score(resume_text: str, jd_text: str, jd=None):
        score_calls["n"] += 1
        if score_calls["n"] == 1:
            return 70.0, "Needs work", ["kubernetes", "terraform"]
        return 96.0, "Improved", []

    class FakeJD:
        title = "Engineer"
        raw_text = "Need kubernetes and terraform"
        skills = json.dumps(["kubernetes"])
        preferred_skills = json.dumps([])
        experience = ""
        technologies = json.dumps(["terraform"])
        responsibilities = json.dumps([])
        keywords = json.dumps(["kubernetes", "terraform"])

    with patch("core.resume_generator.llm_client.generate", side_effect=fake_generate), patch(
        "core.resume_generator.score_resume", side_effect=fake_score
    ), patch("core.resume_generator.get_thresholds", return_value={"ats_score": 95, "max_iterations": 3}):
        result = generate_resume("profile", "jd text", max_iterations=3, jd=FakeJD())

    assert len(prompts) >= 2
    assert "kubernetes" in prompts[1]
    assert "terraform" in prompts[1]
    assert result["ats_score"] == 96.0
