from decimal import Decimal

import pytest

from app.market.bist import (
    TickDirection,
    canonical_bist_symbol,
    get_tick_size,
    is_valid_bist_price,
    round_to_tick,
)


@pytest.mark.parametrize(
    ("price", "tick"),
    [
        ("0.01", "0.01"),
        ("19.99", "0.01"),
        ("20.00", "0.02"),
        ("49.99", "0.02"),
        ("50.00", "0.05"),
        ("99.99", "0.05"),
        ("100.00", "0.10"),
        ("249.99", "0.10"),
        ("250.00", "0.25"),
        ("499.99", "0.25"),
        ("500.00", "0.50"),
        ("999.99", "0.50"),
        ("1000.00", "1.00"),
        ("2499.99", "1.00"),
        ("2500.00", "2.50"),
    ],
)
def test_tick_band_boundaries(price: str, tick: str) -> None:
    assert get_tick_size(price) == Decimal(tick)


@pytest.mark.parametrize(
    ("raw", "floor", "ceil", "nearest"),
    [
        ("34.27", "34.26", "34.28", "34.28"),
        ("22.13", "22.12", "22.14", "22.14"),
        ("26.87", "26.86", "26.88", "26.88"),
        ("255.12", "255.00", "255.25", "255.00"),
        ("1966.85", "1966.00", "1967.00", "1967.00"),
    ],
)
def test_directional_examples(raw: str, floor: str, ceil: str, nearest: str) -> None:
    assert round_to_tick(raw, TickDirection.FLOOR) == Decimal(floor)
    assert round_to_tick(raw, TickDirection.CEIL) == Decimal(ceil)
    result = round_to_tick(raw)
    assert result == Decimal(nearest)
    assert is_valid_bist_price(result)


def test_symbol_canonicalization() -> None:
    assert {canonical_bist_symbol(x) for x in ("SELEC", "selec.is", "BIST:SELEC")} == {"SELEC"}
