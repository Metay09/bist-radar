from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.universe.service import KapMarketUniverseSource, UniverseRepository

PAYLOAD = """
<table><tr><th>Sıra</th><th>Kod</th><th>Şirket / Fon Adı</th></tr>
<tr><td>YILDIZ PAZAR 2 Şirket / Fon Bulundu</td></tr>
<tr><td>1</td><td>THYAO</td><td>TÜRK HAVA YOLLARI A.Ş.</td></tr>
<tr><td>2</td><td>NEWCO</td><td>YENİ ŞİRKET A.Ş.</td></tr>
<tr><td>YAPILANDIRILMIŞ ÜRÜNLER VE FON PAZARI 1 Şirket / Fon Bulundu</td></tr>
<tr><td>1</td><td>ETFXX</td><td>ÖRNEK BORSA YATIRIM FONU</td></tr>
<tr><td>GİRİŞİM SERMAYESİ PAZARI 1 Şirket / Fon Bulundu</td></tr>
<tr><td>1</td><td>FUNDX</td><td>ÖRNEK GİRİŞİM SERMAYESİ YATIRIM FONU</td></tr></table>
"""


def sessions():  # type: ignore[no-untyped-def]
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_equity_only_discovery_and_exact_mapping() -> None:
    result = KapMarketUniverseSource.parse(PAYLOAD, datetime(2026, 8, 13, tzinfo=UTC))
    assert [item.symbol for item in result.equities] == ["NEWCO", "THYAO"]
    excluded = {
        item.symbol: item.instrument_type for item in result.instruments if not item.accepted
    }
    assert excluded == {"ETFXX": "STRUCTURED_OR_FUND", "FUNDX": "FUND"}
    assert len(result.snapshot_id) == 64


def test_refresh_new_inactive_and_history_retention() -> None:
    factory = sessions()
    repository = UniverseRepository(factory)
    first = KapMarketUniverseSource.parse(PAYLOAD, datetime(2026, 8, 13, tzinfo=UTC))
    assert repository.save(first) == {"new": 2, "inactive": 0, "active": 2}
    changed = KapMarketUniverseSource.parse(
        PAYLOAD.replace("<tr><td>2</td><td>NEWCO</td><td>YENİ ŞİRKET A.Ş.</td></tr>", ""),
        datetime(2026, 8, 14, tzinfo=UTC),
    )
    assert repository.save(changed)["inactive"] == 1
    assert repository.active_symbols() == ["THYAO"]
    # Repeating an identical snapshot is idempotent.
    assert repository.save(changed)["new"] == 0


def test_coverage_math_and_provider_failure_status() -> None:
    factory = sessions()
    repository = UniverseRepository(factory)
    discovery = KapMarketUniverseSource.parse(PAYLOAD, datetime.now(UTC))
    repository.save(discovery)
    quality = type("Quality", (), {"last_timestamp": datetime.now(UTC)})()
    result = type("Download", (), {"quality": quality})()
    repository.record_provider_results(
        {"THYAO": result}, {"NEWCO": "SYMBOL_DATA_UNAVAILABLE"}, datetime.now(UTC)
    )
    summary = repository.summary()
    assert summary["total_active_equities"] == 2
    assert summary["provider_available"] == 1
    assert summary["provider_unavailable"] == 1
    assert repository.active_symbols(available_only=True) == ["THYAO"]


def test_empty_universe_fails_closed() -> None:
    import pytest

    with pytest.raises(ValueError, match="EMPTY_OFFICIAL_UNIVERSE"):
        KapMarketUniverseSource.parse("<html></html>", datetime.now(UTC))


def test_fetch_uses_injected_client_and_propagates_provider_failure() -> None:
    import pytest

    class Response:
        text = PAYLOAD

        def raise_for_status(self) -> None:
            return None

    class Client:
        def get(self, url: str) -> Response:
            assert url.endswith("/Pazarlar")
            return Response()

    assert len(KapMarketUniverseSource(Client()).fetch().equities) == 2

    class FailedResponse(Response):
        def raise_for_status(self) -> None:
            raise RuntimeError("temporary source failure")

    class FailedClient(Client):
        def get(self, url: str) -> FailedResponse:
            return FailedResponse()

    with pytest.raises(RuntimeError, match="temporary"):
        KapMarketUniverseSource(FailedClient()).fetch()


def test_hundreds_of_symbols_are_unique_and_deterministic() -> None:
    rows = "".join(
        f"<tr><td>{index}</td><td>S{index:04d}</td><td>ŞİRKET {index}</td></tr>"
        for index in range(500)
    )
    payload = f"<table><tr><td>YILDIZ PAZAR 500 Şirket / Fon Bulundu</td></tr>{rows}</table>"
    result = KapMarketUniverseSource.parse(payload, datetime.now(UTC))
    assert len(result.equities) == 500
    assert result.equities[0].symbol == "S0000"
    assert result.equities[-1].symbol == "S0499"
