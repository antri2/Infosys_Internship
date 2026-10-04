from services.skill_normalizer import (
    normalize_skill,
    normalize_skill_list,
    skill_comparison_key,
    split_skill_text,
)


def test_confirmed_aliases_are_normalized():
    assert normalize_skill("JS") == "JavaScript"
    assert normalize_skill("ML") == "Machine Learning"
    assert normalize_skill("React.js") == "React"
    assert normalize_skill("PostgreSQL") == "Postgres"


def test_alias_matching_is_case_and_whitespace_insensitive():
    assert normalize_skill("  react.JS  ") == "React"
    assert skill_comparison_key("JS") == skill_comparison_key("javascript")


def test_normalization_deduplicates_and_preserves_order():
    assert normalize_skill_list(
        ["JS", "JavaScript", " ML ", "Machine Learning", "React.js", "React"]
    ) == ["JavaScript", "Machine Learning", "React"]


def test_only_confirmed_aliases_are_applied():
    assert normalize_skill("NodeJS") == "NodeJS"
    assert normalize_skill("Amazon Web Services") == "Amazon Web Services"
    assert normalize_skill("K8S") == "K8S"


def test_split_skill_text_handles_empty_and_duplicates_only_at_normalization_stage():
    assert split_skill_text(" Python, SQL ,, ") == ["Python", "SQL"]
    assert split_skill_text(None) == []
