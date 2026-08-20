"""Borsa Istanbul executable-price and symbol rules.

All calculations use ``Decimal`` so a valid exchange price cannot acquire binary
floating-point residue before it reaches an API or execution engine.
"""

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from enum import StrEnum

D = Decimal

# Upper bound is exclusive. ``None`` is the unbounded final band.
BIST_EQUITY_TICK_TABLE: tuple[tuple[Decimal | None, Decimal], ...] = (
    (D("20"), D("0.01")),
    (D("50"), D("0.02")),
    (D("100"), D("0.05")),
    (D("250"), D("0.10")),
    (D("500"), D("0.25")),
    (D("1000"), D("0.50")),
    (D("2500"), D("1.00")),
    (None, D("2.50")),
)


class TickDirection(StrEnum):
    FLOOR = "floor"
    CEIL = "ceil"
    NEAREST = "nearest"


def as_decimal(value: Decimal | int | float | str) -> Decimal:
    result = value if isinstance(value, Decimal) else D(str(value))
    if not result.is_finite():
        raise ValueError("finite price required")
    return result


def get_tick_size(price: Decimal | int | float | str) -> Decimal:
    value = as_decimal(price)
    if value <= 0:
        raise ValueError("positive price required")
    for upper, tick in BIST_EQUITY_TICK_TABLE:
        if upper is None or value < upper:
            return tick
    raise AssertionError("unreachable tick band")


def round_to_tick(
    price: Decimal | int | float | str,
    direction: TickDirection | str = TickDirection.NEAREST,
) -> Decimal:
    """Round inside the price's band, rechecking when rounding crosses a boundary."""
    value = as_decimal(price)
    mode = TickDirection(direction)
    if value <= 0:
        raise ValueError("positive price required")
    rounding = {
        TickDirection.FLOOR: ROUND_FLOOR,
        TickDirection.CEIL: ROUND_CEILING,
        TickDirection.NEAREST: ROUND_HALF_UP,
    }[mode]
    tick = get_tick_size(value)
    rounded = (value / tick).to_integral_value(rounding=rounding) * tick
    # A boundary-crossing ceil can enter a band with a coarser grid.
    boundary_tick = get_tick_size(rounded)
    if rounded % boundary_tick:
        rounded = (rounded / boundary_tick).to_integral_value(rounding=rounding) * boundary_tick
    return rounded.quantize(boundary_tick)


def is_valid_bist_price(price: Decimal | int | float | str) -> bool:
    value = as_decimal(price)
    return value > 0 and value == round_to_tick(value)


def canonical_bist_symbol(symbol: object) -> str:
    """Map common provider forms (``BIST:SELEC``, ``SELEC.IS``) to ``SELEC``."""
    value = str(symbol or "").strip().upper()
    if value.startswith("BIST:"):
        value = value[5:]
    for suffix in (".IS", ".TI"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
    return value
