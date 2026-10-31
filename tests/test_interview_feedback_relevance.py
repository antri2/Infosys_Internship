"""Mock-interview feedback must be grounded in the exact question and answer.

The reported symptom was feedback about an unrelated subject, such as churn
prediction, when the question concerned something else. These tests pin the
drift detection, the bounded retry, and the question-specific fallback.
"""
import json

import pytest

from services import interview_agent as I


QUESTION = "Explain how a decision tree chooses a split point."
ANSWER = ("It picks the feature and threshold that give the largest reduction "
          "in impurity, usually measured by Gini impurity or entropy.")
ROLE = "Data Analyst"


def _reference():
    return I._evaluation_reference_terms(QUESTION, ANSWER, ROLE)


# --------------------------------------------------------------- drift check ---

@pytest.mark.parametrize("feedback", [
    "Your answer missed the churn prediction model entirely. Add more detail "
    "on customer retention and logistic regression.",
    "A strong answer would describe churn prediction, customer retention and "
    "the logistic regression pipeline.",
    "You should have explained gradient boosted trees for churn prediction.",
])
def test_feedback_on_a_different_subject_is_rejected(feedback):
    """The exact symptom: churn feedback for a decision-tree question."""
    assert I._is_feedback_relevant(feedback, _reference()) is False


@pytest.mark.parametrize("feedback", [
    "You correctly identified impurity reduction using Gini impurity.",
    "You described impurity reduction well. Mention how thresholds are "
    "evaluated for continuous features.",
    "You defined the concept clearly.",
])
def test_on_topic_feedback_is_accepted(feedback):
    assert I._is_feedback_relevant(feedback, _reference()) is True


def test_generic_critique_is_not_treated_as_drift():
    """Terse, correct feedback is made of generic critique words only."""
    feedback = ("You attempted the question. Add a concrete example and close "
                "with a practical use case.")
    assert I._is_feedback_relevant(feedback, _reference()) is True


def test_a_question_about_ml_rejects_decision_tree_feedback():
    """Relevance is judged against the question that was actually asked."""
    reference = I._evaluation_reference_terms(
        "Explain supervised versus unsupervised learning.",
        "Supervised uses labelled data.",
        "AI Engineer",
    )
    tree_feedback = "You correctly identified impurity reduction using Gini impurity."
    assert I._is_feedback_relevant(tree_feedback, reference) is False


def test_drift_terms_can_be_inspected():
    drift = I._feedback_drift_terms(
        "Your answer missed the churn prediction model entirely.", _reference())
    assert "churn" in drift
    assert "prediction" in drift


# ------------------------------------------------------------- retry + safe ---

def _candidate():
    return {"name": "Anchal Tripathi", "skills": ["Python", "SQL"],
            "projects": [], "experience": [], "certifications": [],
            "education": []}


def test_drift_is_retried_then_the_question_specific_fallback_is_used(monkeypatch):
    """A drifting model reply is retried once, then replaced safely."""
    calls = []

    def always_drifted(prompt, **kwargs):
        calls.append(prompt)
        return json.dumps({
            "did_well": ["Your answer missed the churn prediction model entirely "
                         "and should have covered customer retention."],
            "improve": ["Describe logistic regression for churn prediction."],
            "suggested_answer": "Churn prediction uses logistic regression.",
            "how_to_improve": "1. Churn. 2. Retention.",
            "score": 30,
        })

    monkeypatch.setattr(I, "generate", always_drifted)
    result = I.evaluate_interview_answer(
        _candidate(), None, None, ROLE, QUESTION, ANSWER,
        category="technical", difficulty="medium")

    assert len(calls) == I.EVALUATION_MAX_ATTEMPTS, "the drift was not retried"
    assert result["used_fallback"] is True
    # The fallback must not mention the drifted topic at all.
    blob = " ".join([*result["did_well"], *result["improve"],
                     result["suggested_answer"], result["how_to_improve"]]).lower()
    assert "churn" not in blob and "retention" not in blob


def test_a_retry_that_recovers_is_used(monkeypatch):
    """The retry is not wasted: a corrected reply is accepted."""
    replies = [
        json.dumps({"did_well": ["Your answer missed the churn prediction model "
                                 "entirely and ignored customer retention."],
                    "improve": ["Cover logistic regression for churn."],
                    "suggested_answer": "Churn prediction.", "score": 20}),
        json.dumps({"did_well": ["You correctly described impurity reduction "
                                 "using Gini impurity."],
                    "improve": ["Explain threshold evaluation."],
                    "suggested_answer": "A split minimises weighted impurity.",
                    "how_to_improve": "1. Define. 2. Example.",
                    "score": 80}),
    ]
    monkeypatch.setattr(I, "generate", lambda prompt, **k: replies.pop(0))

    result = I.evaluate_interview_answer(
        _candidate(), None, None, ROLE, QUESTION, ANSWER,
        category="technical", difficulty="medium")
    assert result["used_fallback"] is False
    assert "Gini" in " ".join(result["did_well"])


def test_guidance_returned_as_a_list_is_still_used(monkeypatch):
    """Models often return guidance as a list; it used to be discarded."""
    monkeypatch.setattr(I, "generate", lambda prompt, **k: json.dumps({
        "did_well": ["You correctly described impurity reduction."],
        "improve": [],
        "suggested_answer": "A split minimises impurity.",
        "how_to_improve": ["Define impurity.", "Give a numeric example."],
        "score": 70,
    }))
    result = I.evaluate_interview_answer(
        _candidate(), None, None, ROLE, QUESTION, ANSWER,
        category="technical", difficulty="medium")
    assert result["used_fallback"] is False
    assert "Define impurity" in result["how_to_improve"]


def test_model_failure_falls_back_without_raising(monkeypatch):
    def boom(prompt, **kwargs):
        raise RuntimeError("model down")

    monkeypatch.setattr(I, "generate", boom)
    result = I.evaluate_interview_answer(
        _candidate(), None, None, ROLE, QUESTION, ANSWER,
        category="technical", difficulty="medium")
    assert result["used_fallback"] is True
    assert result["did_well"] and result["improve"]


def test_empty_feedback_is_retried_then_falls_back(monkeypatch):
    monkeypatch.setattr(I, "generate", lambda prompt, **k: json.dumps({
        "did_well": [], "improve": [], "suggested_answer": "",
        "how_to_improve": "", "score": 0,
    }))
    result = I.evaluate_interview_answer(
        _candidate(), None, None, ROLE, QUESTION, ANSWER,
        category="technical", difficulty="medium")
    assert result["used_fallback"] is True


def test_retries_are_bounded(monkeypatch):
    """The user must never be made to wait through unbounded model calls."""
    calls = []
    monkeypatch.setattr(I, "generate", lambda prompt, **k: (calls.append(1),
                                                           "not json")[1])
    I.evaluate_interview_answer(
        _candidate(), None, None, ROLE, QUESTION, ANSWER,
        category="technical", difficulty="medium")
    assert len(calls) <= I.EVALUATION_MAX_ATTEMPTS
    assert I.EVALUATION_MAX_ATTEMPTS <= 3


def test_evaluation_budget_leaves_room_for_the_payload():
    assert I.EVALUATION_MAX_TOKENS >= 4000


def test_question_and_answer_are_required():
    with pytest.raises(ValueError):
        I.evaluate_interview_answer(_candidate(), None, None, ROLE, "", "answer")
    with pytest.raises(ValueError):
        I.evaluate_interview_answer(_candidate(), None, None, ROLE, "q", "  ")