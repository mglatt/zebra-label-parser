import base64
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

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


# --- Webhook endpoint tests ---


def _make_png_bytes() -> bytes:
    """Create a small valid PNG in memory."""
    import io
    img = Image.new("RGB", (100, 150), (0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_webhook_file_path(app):
    """Webhook accepts a file_path and prints."""
    png_bytes = _make_png_bytes()
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(png_bytes)
        tmp_path = f.name

    with patch("app.services.pipeline.print_zpl") as mock_print:
        mock_print.return_value = {"success": True, "job_id": 1, "printer": "Test"}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/labels/webhook",
                json={"file_path": tmp_path, "printer": "Test"},
            )
            assert resp.status_code == 200
            assert resp.json()["success"] is True

    Path(tmp_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_webhook_base64(app):
    """Webhook accepts base64-encoded file data and prints."""
    png_bytes = _make_png_bytes()
    b64 = base64.b64encode(png_bytes).decode()

    with patch("app.services.pipeline.print_zpl") as mock_print:
        mock_print.return_value = {"success": True, "job_id": 2, "printer": "Test"}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/labels/webhook",
                json={"file_base64": b64, "filename": "label.png", "printer": "Test"},
            )
            assert resp.status_code == 200
            assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_webhook_missing_file(app):
    """Webhook returns 400 when file_path points to a missing file."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/labels/webhook",
            json={"file_path": "/nonexistent/label.pdf", "printer": "Test"},
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_webhook_no_input(app):
    """Webhook returns 400 when neither file_path nor file_base64 is provided."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/labels/webhook",
            json={"printer": "Test"},
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_webhook_no_printer(app):
    """Webhook returns 400 when no printer is specified."""
    app.state.settings.printer_name = None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/labels/webhook",
            json={"file_base64": base64.b64encode(b"fake").decode()},
        )
        assert resp.status_code == 400
