from engram.models import DraftRequest
from engram.router import (
    build_system_prompt,
    build_user_prompt,
    default_note_format,
    template_drafts,
)


def make_request(**overrides) -> DraftRequest:
    base = dict(
        knowledge_type="concept",
        selected_text="Interleaving improves discrimination between categories.",
        user_note="test the boundary case",
        window_title="Learning notes - Chrome",
        app_class="browser",
        max_cards=2,
    )
    base.update(overrides)
    return DraftRequest(**base)


def test_system_prompt_contains_limits_and_zero_card_rule():
    prompt = build_system_prompt(max_cards=2, cloze_max_deletions=2)
    assert "0 to 2 cards" in prompt
    assert "ZERO IS SOMETIMES BEST" in prompt
    assert "reject_reason" in prompt


def test_system_prompt_demands_omission_transparency():
    prompt = build_system_prompt(2, 2)
    assert "NO SILENT OMISSION" in prompt
    assert "omitted_targets" in prompt


def test_system_prompt_states_trust_hierarchy():
    prompt = build_system_prompt(2, 2)
    assert "TRUST HIERARCHY" in prompt
    assert "untrusted" in prompt
    assert "ignore previous instructions" in prompt  # named as an example to ignore


def test_user_prompt_contains_text_note_and_context():
    req = make_request()
    prompt = build_user_prompt(req)
    assert req.selected_text in prompt
    assert req.user_note in prompt
    assert req.window_title in prompt
    assert "BEGIN CAPTURED TEXT" in prompt


def test_each_knowledge_type_gets_its_directive():
    assert "boundary case" in build_user_prompt(make_request(knowledge_type="concept"))
    assert "retrieval cues" in build_user_prompt(make_request(knowledge_type="procedure"))
    assert "meaning-bearing" in build_user_prompt(make_request(knowledge_type="cloze"))


def test_auto_mode_asks_model_to_classify():
    prompt = build_user_prompt(make_request(knowledge_type="auto"))
    assert "AUTO mode" in prompt
    assert "classify" in prompt


def test_auto_template_gets_concrete_type():
    drafts = template_drafts(make_request(knowledge_type="auto"))
    assert drafts[0].knowledge_type == "concept"


def test_system_prompt_encodes_card_craft():
    prompt = build_system_prompt(2, 2)
    assert "MINIMUM INFORMATION" in prompt
    assert "yes/no" in prompt


def test_formula_single_card_prefers_applicability():
    single = build_user_prompt(make_request(knowledge_type="formula", max_cards=1))
    double = build_user_prompt(make_request(knowledge_type="formula", max_cards=2))
    assert "prefer the applicability" in single
    assert "prefer the applicability" not in double


def test_custom_mode_embeds_user_instruction_as_directive():
    prompt = build_user_prompt(make_request(knowledge_type="custom", user_note="make one cloze about dates"))
    assert "CUSTOM mode" in prompt
    assert "make one cloze about dates" in prompt


def test_default_note_format():
    assert default_note_format("fact") == "basic"
    assert default_note_format("cloze") == "cloze"
    assert default_note_format("formula") == "cloze"


def test_template_drafts_manual_mode():
    drafts = template_drafts(make_request(knowledge_type="procedure"))
    assert len(drafts) == 1
    assert drafts[0].note_format == "basic"
    assert "When do I use" in drafts[0].front

    cloze = template_drafts(make_request(knowledge_type="cloze"))
    assert cloze[0].note_format == "cloze"
