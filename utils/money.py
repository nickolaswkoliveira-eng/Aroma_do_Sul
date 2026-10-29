from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")


def money(value) -> Decimal:
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        decimal_value = value
    else:
        decimal_value = Decimal(str(value))
    return decimal_value.quantize(CENT, rounding=ROUND_HALF_UP)


def money_sum(values) -> Decimal:
    return money(sum((money(value) for value in values), Decimal("0")))


def money_float(value) -> float:
    return float(money(value))
