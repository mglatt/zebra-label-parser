from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
def app():
    with patch.dict("os.environ", {"ZLP_ANTHROPIC_API_KEY": "", "ZLP_PRINTER_NAME": "Test"}):
        return create_app()


@pytest.mark.asyncio
async def test_health(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_printers_endpoint(app):
    with patch("app.routers.printers.get_available_printers") as mock_printers:
        mock_printers.return_value = [{"name": "Zebra", "info": "", "state": 3, "uri": ""}]
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/printers")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["printers"]) == 1


@pytest.mark.asyncio
async def test_print_no_printer(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Override settings to have no printer
        app.state.settings.printer_name = None
        resp = await client.post(
            "/api/labels/print",
            files={"file": ("test.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, "image/png")},
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_print_empty_file(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/labels/print",
            files={"file": ("test.png", b"", "image/png")},
            data={"printer": "Zebra"},
        )
        assert resp.status_code == 400
