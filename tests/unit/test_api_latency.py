import asyncio

from starlette.requests import Request
from starlette.responses import Response

from app.api.main import (
    dashboard_latencies,
    dashboard_latency_endpoint,
    observe_dashboard_latency,
)


def test_dashboard_latency_observation_and_percentiles() -> None:
    dashboard_latencies.clear()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/dashboard/opportunities",
            "headers": [],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("test", 1),
            "scheme": "http",
        }
    )

    async def next_response(_: Request) -> Response:
        return Response(status_code=200)

    response = asyncio.run(observe_dashboard_latency(request, next_response))
    assert "app;dur=" in response.headers["Server-Timing"]
    for value in range(1, 101):
        dashboard_latencies["/dashboard/candidates"].append(float(value))
    report = dashboard_latency_endpoint()
    assert report["opportunities"]["count"] == 1
    assert report["candidates"] == {"count": 100, "p50_ms": 50.0, "p95_ms": 95.0}


def test_dashboard_latency_ignores_other_paths() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/health",
            "headers": [],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("test", 1),
            "scheme": "http",
        }
    )

    async def next_response(_: Request) -> Response:
        return Response(status_code=200)

    response = asyncio.run(observe_dashboard_latency(request, next_response))
    assert "Server-Timing" not in response.headers
