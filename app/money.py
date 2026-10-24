"""Display helpers. Storage and maths stay in integer paise."""


def rupees(paise: int) -> int | float:
    """Whole rupees when exact (for reply templates), else two decimals."""
    return paise // 100 if paise % 100 == 0 else round(paise / 100, 2)


def inr(paise: int) -> str:
    """₹ with Indian digit grouping: 1234567 paise -> '₹12,345.67'; 150000 -> '₹1,500'."""
    sign = "-" if paise < 0 else ""
    whole, fraction = divmod(abs(paise), 100)
    digits = str(whole)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups + [tail])
    return f"{sign}₹{digits}" + (f".{fraction:02d}" if fraction else "")


def count(value: float) -> int | float:
    """2.0 -> 2, 1.5 -> 1.5: day counts read naturally in replies."""
    return int(value) if float(value).is_integer() else value
