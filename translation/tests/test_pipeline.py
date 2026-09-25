import json

import pytest

from conftest import SECRET_REASONING, FakeLLM, make_docx
from pipeline import Pipeline
from state import FAILED, FINAL, TRANSLATED, SourceChangedError


def run_all(settings, llm):
    p = Pipeline(settings, llm)
    p.run_bible()
    p.run_chunks()
    p.run_book_review()
    p.build()
    return p


def test_full_run_translates_reviews_and_builds(settings):
    llm = FakeLLM()
    p = run_all(settings, llm)

    assert p.all_final()
    assert settings.output_docx.exists()
    assert p.build()[-1].startswith("Check passed")
    finals = p.state.final_translations()
    assert finals["P0004"].startswith("REFINED:EN:")  # critic found an issue → refined

    # every chunk went translate → critic → refine, then one whole-book review
    assert llm.kinds()[0] == "bible" and llm.kinds()[-1] == "review"
    assert llm.kinds().count("review") == 1

    # prompt caching layout: the whole source book is in the first system block of every call
    for call in llm.calls:
        assert "O fluido do perispírito" in call["system"][0]["text"]
        assert call["system"][0]["cache_control"]["ttl"] == "1h"

    review_call = llm.calls[-1]
    assert "REFINED:EN:" in review_call["user"]          # it reads the whole English book
    assert SECRET_REASONING not in review_call["user"]   # independence from translator reasoning
    assert review_call["effort"] == "xhigh"

    entries = json.loads(settings.review_json.read_text())
    decisions = [e for e in entries if e["kind"] == "decision"]
    assert any(e["source"] == "bible" for e in decisions)
    assert all(e["reviewer"]["verdict"] == "disagree" for e in decisions)
    findings = [e for e in entries if e["kind"] == "finding"]
    assert findings[0]["paragraph_ids"] == ["P0008"] and findings[0]["chunks"]
    assert settings.book_review_md.exists()
    assert "Fit after revisions" in settings.book_review_md.read_text()
    assert "5/5" in settings.book_review_md.read_text()  # score clamped
    assert "Reviewer disagrees" in settings.review_md.read_text()


def test_resume_after_crash_does_not_repeat_work(settings):
    crashing = FakeLLM(fail_on="critic")
    p = Pipeline(settings, crashing)
    p.run_bible()
    with pytest.raises(RuntimeError, match="simulated crash"):
        p.run_chunks()
    first = p.state.chunk_ids()[0]
    assert p.state.chunk(first)["status"] == TRANSLATED

    fresh = FakeLLM()
    p2 = Pipeline(settings, fresh)
    p2.run_bible()
    p2.run_chunks()
    assert p2.all_final()
    assert "bible" not in fresh.kinds()
    assert fresh.kinds().count("translate") == len(p2.state.chunk_ids()) - 1
    # flags are not duplicated on resume
    entries = json.loads(settings.review_json.read_text())
    translator_keys = [e["origin_key"] for e in entries if e["source"] == "translator"]
    assert len(translator_keys) == len(set(translator_keys)) == len(p2.state.chunk_ids())


def test_refusal_marks_chunk_failed_and_retries_later(settings):
    p = Pipeline(settings, FakeLLM(refuse_on="critic"))
    p.run_chunks()
    statuses = {p.state.chunk(c)["status"] for c in p.state.chunk_ids()}
    assert statuses == {FAILED}
    p2 = Pipeline(settings, FakeLLM())
    p2.run_chunks()
    assert p2.all_final()


def test_source_change_is_detected(settings):
    Pipeline(settings, FakeLLM())
    make_docx(settings.source_docx)  # new file → different bytes (timestamps in docx metadata)
    settings.source_docx.write_bytes(settings.source_docx.read_bytes() + b" ")
    with pytest.raises(SourceChangedError):
        Pipeline(settings, FakeLLM())
    Pipeline(settings, FakeLLM(), reset=True)  # reset starts over


def test_apply_corrections_retranslates_and_revises(settings):
    run_all(settings, FakeLLM())
    entries = json.loads(settings.review_json.read_text())
    term = next(e for e in entries if e["kind"] == "decision" and e["original_term"] == "sintonia"
                and e["chunk"] is not None)
    term["correction"] = "resonance"
    finding = next(e for e in entries if e["kind"] == "finding")
    finding["review_status"] = "accept"
    settings.review_json.write_text(json.dumps(entries, ensure_ascii=False))

    llm = FakeLLM(critic_issue=False)
    p = Pipeline(settings, llm)
    terms, findings, affected = p.apply_corrections()
    assert (terms, findings) == (1, 1)

    sintonia_chunk = p.chunk_of_paragraph()["P0007"]
    assert sintonia_chunk in affected
    assert p.state.chunk(sintonia_chunk)["version"] == 2
    assert any(e.origin == "reviewer" and e.target == "resonance" for e in p.glossary)
    translate_prompts = [c["user"] for c in llm.calls if c["kind"] == "translate"]
    assert any("Translate 'sintonia' as 'resonance'" in u for u in translate_prompts)
    assert all("resonance" in c["system"][1]["text"] for c in llm.calls)
    assert p.all_final()

    after = json.loads(settings.review_json.read_text())
    assert next(e for e in after if e["id"] == term["id"])["review_status"] == "applied"
    assert next(e for e in after if e["id"] == finding["id"])["review_status"] == "applied"

    # re-review only the changed chapters, still with the whole book
    p.run_book_review(changed_only=True)
    review_user = llm.calls[-1]["user"]
    assert llm.kinds()[-1] == "review" and "re-review" in review_user
    assert p.run_book_review(changed_only=True) is None  # nothing changed since


def test_status_lines(settings):
    p = run_all(settings, FakeLLM())
    text = "\n".join(p.status_lines())
    assert FINAL in text and "Book review rounds: 1" in text and "≈ $" in text
