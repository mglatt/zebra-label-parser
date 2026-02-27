from unittest.mock import MagicMock, patch

from app.services.print_service import get_available_printers, print_zpl


@patch("app.services.print_service._HAS_PYCUPS", False)
def test_get_printers_fallback_no_lpstat():
    with patch("app.services.print_service.subprocess") as mock_sub:
        mock_sub.run.side_effect = FileNotFoundError("lpstat not found")
        result = get_available_printers()
        assert result == []


@patch("app.services.print_service._HAS_PYCUPS", False)
def test_get_printers_fallback_lpstat():
    with patch("app.services.print_service.subprocess") as mock_sub:
        mock_result = MagicMock()
        mock_result.stdout = "printer Zebra_ZD420 is idle.\nprinter HP_LaserJet is idle.\n"
        mock_sub.run.return_value = mock_result
        result = get_available_printers()
        assert len(result) == 2
        assert result[0]["name"] == "Zebra_ZD420"


@patch("app.services.print_service._HAS_PYCUPS", True)
def test_get_printers_pycups():
    with patch("app.services.print_service.cups", create=True) as mock_cups:
        mock_conn = MagicMock()
        mock_conn.getPrinters.return_value = {
            "Zebra": {"printer-info": "Zebra ZD420", "printer-state": 3, "device-uri": "usb://Zebra/ZD420"}
        }
        mock_cups.Connection.return_value = mock_conn
        result = get_available_printers()
        assert len(result) == 1
        assert result[0]["name"] == "Zebra"
        assert result[0]["info"] == "Zebra ZD420"


@patch("app.services.print_service._HAS_PYCUPS", True)
def test_print_zpl_pycups():
    with patch("app.services.print_service.cups", create=True) as mock_cups:
        mock_conn = MagicMock()
        mock_conn.printFile.return_value = 42
        mock_cups.Connection.return_value = mock_conn

        result = print_zpl("^XA^XZ", "Zebra")
        assert result["success"] is True
        assert result["job_id"] == 42


@patch("app.services.print_service._HAS_PYCUPS", False)
def test_print_zpl_lp_fallback():
    with patch("app.services.print_service.subprocess") as mock_sub:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "request id is Zebra-123"
        mock_sub.run.return_value = mock_result

        result = print_zpl("^XA^XZ", "Zebra")
        assert result["success"] is True
