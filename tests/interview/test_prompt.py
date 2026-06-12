"""Tests for interview.prompt.build_system_prompt directive content."""

from __future__ import annotations

from interview.prompt import DISCLAIMER_SENTENCE, build_system_prompt

DISCLAIMER = (
    "This is a screening estimate, not an eligibility determination. "
    "Only your county DSS can determine eligibility. "
    "Apply online at https://epass.nc.gov."
)


def test_disclaimer_sentence_exact():
    assert DISCLAIMER_SENTENCE == DISCLAIMER


def test_prompt_addresses_caseworker():
    prompt = build_system_prompt("SUMMARY")
    assert "caseworker" in prompt.lower()


def test_prompt_directs_immediate_fact_extraction():
    prompt = build_system_prompt("SUMMARY")
    assert "update_household" in prompt
    assert "never re-ask" in prompt.lower() or "never re-ask a fact" in prompt.lower()


def test_prompt_forbids_eligibility_conclusions():
    prompt = build_system_prompt("SUMMARY")
    lower = prompt.lower()
    assert "never" in lower
    assert "eligibility" in lower
    assert "relay" in lower


def test_prompt_one_question_per_turn_plain_language():
    prompt = build_system_prompt("SUMMARY")
    assert "ONE question" in prompt or "one question" in prompt.lower()
    assert "8th-grade" in prompt or "8th grade" in prompt.lower()


def test_prompt_no_ssn_no_immigration_docs():
    prompt = build_system_prompt("SUMMARY").lower()
    assert "ssn" in prompt or "social security number" in prompt
    assert "immigration document" in prompt or "immigration documents" in prompt


def test_prompt_completion_includes_exact_disclaimer():
    prompt = build_system_prompt("SUMMARY")
    assert DISCLAIMER in prompt
    assert "action plan" in prompt.lower()


def test_prompt_embeds_screening_summary():
    prompt = build_system_prompt("MY_UNIQUE_SUMMARY_TOKEN")
    assert "MY_UNIQUE_SUMMARY_TOKEN" in prompt
