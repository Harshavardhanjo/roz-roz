"""Reply texts. The model picks a template key; numbers always come from the database.
English is the master; add "kn" and "hi" (generated, then checked by a native speaker)."""

TEMPLATES: dict[str, dict[str, str]] = {
    "consent_prompt": {"en": "Namaste {name}! {household} uses Roz Roz to record your leave, advances and pay. "
                             "They can see what you send. Reply \"yes\" to agree."},
    "consent_ok": {"en": "Thank you. Send a voice note any time for leave, an advance or grocery money."},
    "leave_approved": {"en": "Leave on {dates} is recorded as paid. Paid leave left this month: {left}."},
    "leave_needs_vote": {"en": "Leave on {dates} has gone to {household} for approval. It would be unpaid."},
    "advance_approved": {"en": "₹{amount} advance approved. This month's advances: ₹{month_total}. "
                               "It will be adjusted in your salary."},
    "advance_needs_vote": {"en": "₹{amount} advance has gone to {household} for approval."},
    "grocery_approved": {"en": "₹{amount} for groceries is in your spending wallet. Balance: ₹{wallet}."},
    "grocery_needs_vote": {"en": "₹{amount} for groceries has gone to {household} for approval."},
    "spend_recorded": {"en": "Recorded ₹{amount} for {item}. Spending wallet: ₹{wallet}."},
    "cash_recorded": {"en": "Recorded ₹{amount} you paid for {item}. It will be repaid to you."},
    "needs_topup": {"en": "{household} needs to add money first. We have told them."},
    "balances": {"en": "Paid leave left: {left}. Advances this month: ₹{month_total}. "
                       "Next pay on {payday}: about ₹{projected}."},
    "rejected": {"en": "{household} did not approve this. Please talk to them."},
    "not_understood": {"en": "Sorry, I didn't catch that. Please send the voice note again."},
    "not_registered": {"en": "This number isn't set up with Roz Roz yet. Please ask your employer to add you."},
}


def render(key: str, lang: str, **slots) -> str:
    texts = TEMPLATES[key]
    return texts.get(lang, texts["en"]).format(**slots)
