"""Reply texts. Replies are built in code from tool outcomes; numbers always come from the database.

English is the master. Every "kn" (Kannada) and "hi" (Hindi) text below is a MACHINE DRAFT that a native speaker
must check before it goes to real helpers. Unknown languages fall back to English.

Slots arrive ready to print (rupees, not paise). Money slots (MONEY_SLOTS) get Indian digit grouping
(8130 -> "8,130", 100000 -> "1,00,000"); whole floats print without ".0" (2.0 -> "2")."""

import string

MONEY_SLOTS = frozenset({"amount", "month_total", "wallet", "projected"})
DEFAULT_LANG = "en"

TEMPLATES: dict[str, dict[str, str]] = {
    "consent_prompt": {
        "en": "Namaste {name}! {household} uses Roz Roz to record your leave, advances and pay. "
        'They can see what you send. Reply "yes" to agree.',
        "kn": "ನಮಸ್ತೆ {name}! ನಿಮ್ಮ ರಜೆ, ಮುಂಗಡ ಮತ್ತು ಸಂಬಳ ದಾಖಲಿಸಲು {household} Roz Roz ಬಳಸುತ್ತಾರೆ. "
        'ನೀವು ಕಳುಹಿಸುವುದನ್ನು ಅವರು ನೋಡಬಹುದು. ಒಪ್ಪಿಗೆ ಇದ್ದರೆ "yes" ಎಂದು ಉತ್ತರಿಸಿ.',
        "hi": "नमस्ते {name}! {household} आपकी छुट्टी, एडवांस और तनख्वाह दर्ज करने के लिए Roz Roz का "
        'इस्तेमाल करते हैं। आप जो भेजेंगे, वे देख सकते हैं। सहमत हों तो "yes" लिखें।',
    },
    "consent_ok": {
        "en": "Thank you. Send a voice note any time for leave, an advance or grocery money.",
        "kn": "ಧನ್ಯವಾದಗಳು. ರಜೆ, ಮುಂಗಡ ಅಥವಾ ದಿನಸಿ ಹಣಕ್ಕಾಗಿ ಯಾವಾಗ ಬೇಕಾದರೂ ವಾಯ್ಸ್ ನೋಟ್ ಕಳುಹಿಸಿ.",
        "hi": "धन्यवाद। छुट्टी, एडवांस या राशन के पैसों के लिए कभी भी वॉइस नोट भेजें।",
    },
    "leave_approved": {
        "en": "Leave on {dates} is recorded as paid. Paid leave left this month: {left}.",
        "kn": "{dates} ರಜೆ ಸಂಬಳ ಸಹಿತ ಎಂದು ದಾಖಲಾಗಿದೆ. ಈ ತಿಂಗಳು ಉಳಿದ ಸಂಬಳ ಸಹಿತ ರಜೆ: {left}.",
        "hi": "{dates} की छुट्टी सवेतन दर्ज हो गई है। इस महीने बची सवेतन छुट्टी: {left}।",
    },
    "leave_needs_vote": {
        "en": "Leave on {dates} has gone to {household} for approval. It would be unpaid.",
        "kn": "{dates} ರಜೆ ಅನುಮೋದನೆಗಾಗಿ {household} ಅವರಿಗೆ ಹೋಗಿದೆ. ಇದು ಸಂಬಳ ರಹಿತ ರಜೆ ಆಗುತ್ತದೆ.",
        "hi": "{dates} की छुट्टी मंज़ूरी के लिए {household} को भेजी गई है। यह बिना वेतन की होगी।",
    },
    "advance_approved": {
        "en": "₹{amount} advance approved. This month's advances: ₹{month_total}. It will be adjusted in your salary.",
        "kn": "₹{amount} ಮುಂಗಡ ಮಂಜೂರಾಗಿದೆ. ಈ ತಿಂಗಳ ಮುಂಗಡ: ₹{month_total}. ಇದನ್ನು ನಿಮ್ಮ ಸಂಬಳದಲ್ಲಿ ಹೊಂದಿಸಲಾಗುತ್ತದೆ.",
        "hi": "₹{amount} एडवांस मंज़ूर हुआ। इस महीने के एडवांस: ₹{month_total}। यह आपकी तनख्वाह में से कटेगा।",
    },
    "advance_needs_vote": {
        "en": "₹{amount} advance has gone to {household} for approval.",
        "kn": "₹{amount} ಮುಂಗಡ ಅನುಮೋದನೆಗಾಗಿ {household} ಅವರಿಗೆ ಹೋಗಿದೆ.",
        "hi": "₹{amount} एडवांस मंज़ूरी के लिए {household} को भेजा गया है।",
    },
    "grocery_approved": {
        "en": "₹{amount} for groceries is in your spending wallet. Balance: ₹{wallet}.",
        "kn": "ದಿನಸಿಗಾಗಿ ₹{amount} ನಿಮ್ಮ ಖರ್ಚು ವ್ಯಾಲೆಟ್‌ಗೆ ಬಂದಿದೆ. ಬ್ಯಾಲೆನ್ಸ್: ₹{wallet}.",
        "hi": "राशन के लिए ₹{amount} आपके खर्च वॉलेट में आ गए हैं। बैलेंस: ₹{wallet}।",
    },
    "grocery_needs_vote": {
        "en": "₹{amount} for groceries has gone to {household} for approval.",
        "kn": "ದಿನಸಿಗಾಗಿ ₹{amount} ಕೋರಿಕೆ ಅನುಮೋದನೆಗಾಗಿ {household} ಅವರಿಗೆ ಹೋಗಿದೆ.",
        "hi": "राशन के लिए ₹{amount} की मांग मंज़ूरी के लिए {household} को भेजी गई है।",
    },
    "spend_recorded": {
        "en": "Recorded ₹{amount} for {item}. Spending wallet: ₹{wallet}.",
        "kn": "{item}ಗಾಗಿ ₹{amount} ದಾಖಲಿಸಲಾಗಿದೆ. ಖರ್ಚು ವ್ಯಾಲೆಟ್: ₹{wallet}.",
        "hi": "{item} के लिए ₹{amount} दर्ज किए गए। खर्च वॉलेट: ₹{wallet}।",
    },
    "cash_recorded": {
        "en": "Recorded ₹{amount} you paid for {item}. It has been repaid to you.",
        "kn": "{item}ಗಾಗಿ ನೀವು ಕೊಟ್ಟ ₹{amount} ದಾಖಲಿಸಲಾಗಿದೆ. ಅದನ್ನು ನಿಮಗೆ ಹಿಂತಿರುಗಿಸಲಾಗಿದೆ.",
        "hi": "{item} के लिए आपके दिए ₹{amount} दर्ज किए गए। यह पैसा आपको लौटा दिया गया है।",
    },
    "sent_for_approval": {
        "en": "{household} will look at this and decide. We'll let you know.",
        "kn": "{household} ಇದನ್ನು ನೋಡಿ ನಿರ್ಧರಿಸುತ್ತಾರೆ. ನಾವು ನಿಮಗೆ ತಿಳಿಸುತ್ತೇವೆ.",
        "hi": "{household} इसे देखकर फ़ैसला करेंगे। हम आपको बता देंगे।",
    },
    "needs_topup": {
        "en": "{household} needs to add money first. We have told them.",
        "kn": "{household} ಮೊದಲು ಹಣ ಸೇರಿಸಬೇಕು. ನಾವು ಅವರಿಗೆ ತಿಳಿಸಿದ್ದೇವೆ.",
        "hi": "{household} को पहले पैसे डालने होंगे। हमने उन्हें बता दिया है।",
    },
    "balances": {
        "en": "Paid leave left: {left}. Advances this month: ₹{month_total}. Next pay on {payday}: about ₹{projected}.",
        "kn": "ಉಳಿದ ಸಂಬಳ ಸಹಿತ ರಜೆ: {left}. ಈ ತಿಂಗಳ ಮುಂಗಡ: ₹{month_total}. ಮುಂದಿನ ಸಂಬಳ {payday} ರಂದು: ಸುಮಾರು ₹{projected}.",
        "hi": "बची सवेतन छुट्टी: {left}। इस महीने के एडवांस: ₹{month_total}। अगली तनख्वाह {payday} को: लगभग ₹{projected}।",
    },
    "rejected": {
        "en": "{household} did not approve this. Please talk to them.",
        "kn": "{household} ಇದನ್ನು ಅನುಮೋದಿಸಲಿಲ್ಲ. ದಯವಿಟ್ಟು ಅವರೊಂದಿಗೆ ಮಾತನಾಡಿ.",
        "hi": "{household} ने इसे मंज़ूर नहीं किया। कृपया उनसे बात करें।",
    },
    "not_understood": {
        "en": "Sorry, I didn't catch that. Please send the voice note again.",
        "kn": "ಕ್ಷಮಿಸಿ, ನನಗೆ ಅರ್ಥವಾಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ವಾಯ್ಸ್ ನೋಟ್ ಮತ್ತೆ ಕಳುಹಿಸಿ.",
        "hi": "माफ़ कीजिए, मैं समझ नहीं पाया। कृपया वॉइस नोट फिर से भेजें।",
    },
    "not_registered": {
        "en": "This number isn't set up with Roz Roz yet. Please ask your employer to add you.",
        "kn": "ಈ ಸಂಖ್ಯೆ ಇನ್ನೂ Roz Roz ನಲ್ಲಿ ಸೇರಿಲ್ಲ. ದಯವಿಟ್ಟು ನಿಮ್ಮನ್ನು ಸೇರಿಸಲು ನಿಮ್ಮ ಮಾಲೀಕರನ್ನು ಕೇಳಿ.",
        "hi": "यह नंबर अभी Roz Roz पर जुड़ा नहीं है। कृपया अपने मालिक से आपको जोड़ने को कहें।",
    },
    "couldnt_hear": {
        "en": "Sorry, I couldn't hear that. Please send it again.",
        "kn": "ಕ್ಷಮಿಸಿ, ನನಗೆ ಕೇಳಿಸಲಿಲ್ಲ. ದಯವಿಟ್ಟು ಮತ್ತೆ ಕಳುಹಿಸಿ.",
        "hi": "माफ़ कीजिए, मुझे सुनाई नहीं दिया। कृपया फिर से भेजें।",
    },
    "please_send_voice": {
        "en": "Please send a voice note.",
        "kn": "ದಯವಿಟ್ಟು ವಾಯ್ಸ್ ನೋಟ್ ಕಳುಹಿಸಿ.",
        "hi": "कृपया वॉइस नोट भेजें।",
    },
    "insufficient_funds": {
        "en": "Your spending wallet doesn't have enough money for this.",
        "kn": "ಇದಕ್ಕೆ ನಿಮ್ಮ ಖರ್ಚು ವ್ಯಾಲೆಟ್‌ನಲ್ಲಿ ಸಾಕಷ್ಟು ಹಣವಿಲ್ಲ.",
        "hi": "इसके लिए आपके खर्च वॉलेट में पर्याप्त पैसे नहीं हैं।",
    },
    "leave_exists": {
        "en": "Leave for those dates is already recorded.",
        "kn": "ಆ ದಿನಗಳ ರಜೆ ಈಗಾಗಲೇ ದಾಖಲಾಗಿದೆ.",
        "hi": "उन तारीखों की छुट्टी पहले से दर्ज है।",
    },
}

_FORMATTER = string.Formatter()


def placeholders(text: str) -> set[str]:
    return {field for _, field, _, _ in _FORMATTER.parse(text) if field}


def indian_group(n: int) -> str:
    """1234567 -> '12,34,567'."""
    sign, digits = ("-", str(-n)) if n < 0 else ("", str(n))
    if len(digits) <= 3:
        return sign + digits
    head, tail = digits[:-3], digits[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return sign + ",".join([*groups, tail])


def _format(name: str, value) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if name in MONEY_SLOTS:
        if isinstance(value, int):
            return indian_group(value)
        if isinstance(value, float):
            whole, frac = f"{abs(value):.2f}".split(".")
            return ("-" if value < 0 else "") + indian_group(int(whole)) + "." + frac
    return str(value)


def render(key: str, lang: str, **slots) -> str:
    """Render template `key` in `lang` (English if that language is missing).

    KeyError for an unknown key; ValueError for a missing slot. Extra slots are ignored."""
    texts = TEMPLATES[key]
    text = texts.get(lang) or texts[DEFAULT_LANG]
    values = {}
    for name in placeholders(text):
        if slots.get(name) is None:
            raise ValueError(f"template {key!r} needs slot {name!r}")
        values[name] = _format(name, slots[name])
    return text.format(**values)
