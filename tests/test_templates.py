import pytest

from app.agents import templates
from app.agents.templates import TEMPLATES, placeholders, render
from app.stubs import TOOL_RESULTS


def test_every_key_has_en_kn_hi():
    for key, texts in TEMPLATES.items():
        assert {"en", "kn", "hi"} <= set(texts), key
        assert all(t.strip() for t in texts.values()), key


def test_slots_match_across_languages():
    for key, texts in TEMPLATES.items():
        expected = placeholders(texts["en"])
        for lang, text in texts.items():
            assert placeholders(text) == expected, (key, lang)


def test_english_masters():
    assert TEMPLATES["cash_recorded"]["en"] == "Recorded ₹{amount} you paid for {item}. It has been repaid to you."
    assert TEMPLATES["sent_for_approval"]["en"] == "{household} will look at this and decide. We'll let you know."
    assert TEMPLATES["couldnt_hear"]["en"] == "Sorry, I couldn't hear that. Please send it again."
    assert TEMPLATES["please_send_voice"]["en"] == "Please send a voice note."
    assert TEMPLATES["insufficient_funds"]["en"] == "Your spending wallet doesn't have enough money for this."
    assert TEMPLATES["leave_exists"]["en"] == "Leave for those dates is already recorded."
    assert render("advance_approved", "en", amount=500, month_total=1500) == (
        "₹500 advance approved. This month's advances: ₹1,500. It will be adjusted in your salary."
    )


@pytest.mark.parametrize(
    ("value", "text"),
    [(8130, "8,130"), (100000, "1,00,000"), (12345678, "1,23,45,678"), (999, "999"), (2.0, "2"), (100.5, "100.50")],
)
def test_indian_grouping(value, text):
    assert render("spend_recorded", "en", amount=value, item="rice", wallet=0) == (
        f"Recorded ₹{text} for rice. Spending wallet: ₹0."
    )


def test_day_counts_and_balances():
    out = render("balances", "en", left=2.0, month_total=1500, payday="31 Oct", projected=8130)
    assert out == "Paid leave left: 2. Advances this month: ₹1,500. Next pay on 31 Oct: about ₹8,130."
    assert render("leave_approved", "en", dates="26 Oct", left=1.5).endswith("left this month: 1.5.")


def test_unknown_key_missing_slot_unknown_lang():
    with pytest.raises(KeyError):
        render("nope", "en")
    with pytest.raises(ValueError):
        render("advance_approved", "en", amount=500)
    assert render("not_understood", "ta") == TEMPLATES["not_understood"]["en"]
    assert render("not_understood", "kn") == TEMPLATES["not_understood"]["kn"]
    # extra slots (outcomes always carry household) are ignored
    assert render("advance_approved", "hi", household="X", amount=500, month_total=500).startswith("₹500")


def test_stub_outcomes_render_in_every_language():
    outcomes = [r["outcome"] for r in TOOL_RESULTS.values() if isinstance(r, dict) and "outcome" in r]
    outcomes += [
        {"template": "spend_recorded", "summary_slots": TOOL_RESULTS["record_grocery_spend"]["summary_slots"]},
        {"template": "balances", "summary_slots": TOOL_RESULTS["get_balances"]["summary_slots"]},
    ]
    for o in outcomes:
        for lang in ("en", "kn", "hi"):
            assert render(o["template"], lang, **o["summary_slots"])
    assert "8,130" in render("balances", "kn", **TOOL_RESULTS["get_balances"]["summary_slots"])


def test_indian_group_negative():
    assert templates.indian_group(-150000) == "-1,50,000"
