import pytest

from hook_loop.evaluator import FakeEvaluator, Verdict, parse_verdict


def test_parse_pass_verdict():
    verdict = parse_verdict("PASS\nEvidence matched every criterion.")

    assert verdict.status == "PASS"
    assert verdict.details == "Evidence matched every criterion."


def test_parse_needs_work_verdict():
    verdict = parse_verdict("NEEDS_WORK\n- Screenshot missing")

    assert verdict.status == "NEEDS_WORK"
    assert "Screenshot missing" in verdict.details


def test_rejects_unparseable_verdict():
    with pytest.raises(ValueError, match="verdict must start"):
        parse_verdict("looks fine")


def test_fake_evaluator_returns_configured_verdicts_in_order():
    evaluator = FakeEvaluator(
        [
            Verdict(status="NEEDS_WORK", details="- first finding"),
            Verdict(status="PASS", details="all good"),
        ]
    )

    assert evaluator.evaluate({}).status == "NEEDS_WORK"
    assert evaluator.evaluate({}).status == "PASS"
