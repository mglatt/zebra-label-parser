"""Submit ZPL print jobs to CUPS."""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import time
from typing import Optional

logger = logging.getLogger(__name__)

# pycups is optional — requires libcups2-dev at build time
try:
    import cups

    _HAS_PYCUPS = True
except ImportError:
    _HAS_PYCUPS = False
    logger.info("pycups not available, will use lp command as fallback")


def _set_cups_server(server: Optional[str]) -> None:
    """Point both pycups and libcups at a remote CUPS server."""
    if not server:
        return
    # Environment variable is read by the underlying libcups C library and
    # by command-line tools (lpstat, lp).  cups.setServer() sets the same
    # value through the pycups binding.
    os.environ["CUPS_SERVER"] = server
    if _HAS_PYCUPS:
        cups.setServer(server)
    logger.info("CUPS server set to %s", server)


def get_available_printers(cups_server: Optional[str] = None) -> list[dict]:
    """List printers from CUPS."""
    _set_cups_server(cups_server)

    if _HAS_PYCUPS:
        try:
            conn = cups.Connection()
            raw = conn.getPrinters()
            return [
                {
                    "name": name,
                    "info": info.get("printer-info", ""),
                    "state": info.get("printer-state", 0),
                    "uri": info.get("device-uri", ""),
                }
                for name, info in raw.items()
            ]
        except Exception:
            logger.exception("Failed to list printers from CUPS server %s", cups_server)
            return []

    # Fallback: parse lpstat output (CUPS_SERVER env var directs lpstat
    # to the remote server automatically).
    try:
        result = subprocess.run(
            ["lpstat", "-p", "-d"],
            capture_output=True, text=True, timeout=5,
        )
        printers = []
        for line in result.stdout.splitlines():
            if line.startswith("printer "):
                parts = line.split()
                name = parts[1] if len(parts) > 1 else "unknown"
                printers.append({"name": name, "info": "", "state": 3, "uri": ""})
        return printers
    except Exception:
        logger.exception("Failed to list printers via lpstat")
        return []


def _check_job_status(conn, job_id: int, printer_name: str) -> None:
    """Log the status of a submitted CUPS job."""
    try:
        time.sleep(0.5)  # brief wait for CUPS to process
        jobs = conn.getJobs(which_jobs="all")
        if job_id in jobs:
            job = jobs[job_id]
            state = job.get("job-state", "?")
            state_reasons = job.get("job-state-reasons", "none")
            # CUPS job states: 3=pending, 4=held, 5=processing, 6=stopped,
            #                  7=canceled, 8=aborted, 9=completed
            state_names = {3: "pending", 4: "held", 5: "processing",
                           6: "stopped", 7: "canceled", 8: "aborted", 9: "completed"}
            logger.info("Job %d status: %s (%s), reasons: %s",
                        job_id, state_names.get(state, state), state, state_reasons)
        else:
            logger.warning("Job %d not found in CUPS job list", job_id)
    except Exception:
        logger.exception("Failed to check job %d status", job_id)


def print_zpl(
    zpl: str,
    printer_name: str,
    cups_server: Optional[str] = None,
) -> dict:
    """Send a ZPL string to a CUPS printer as a raw job."""
    _set_cups_server(cups_server)

    logger.info("Printing ZPL (%d bytes) to %s via %s",
                len(zpl), printer_name, "pycups" if _HAS_PYCUPS else "lp")
    logger.info("ZPL preview (first 200 chars): %s", zpl[:200])

    # Write ZPL to a temp file (both pycups and lp need a file path)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".zpl", delete=False) as f:
        f.write(zpl)
        zpl_path = f.name

    if _HAS_PYCUPS:
        try:
            conn = cups.Connection()
            # Force raw mode by setting the document MIME type so CUPS
            # bypasses its filter chain (driver).  This is more reliable
            # than the PPD option {"raw": ""}.
            job_id = conn.printFile(
                printer_name,
                zpl_path,
                "zebra-label",
                {"document-format": "application/vnd.cups-raw"},
            )
            logger.info("CUPS job %d submitted to %s", job_id, printer_name)
            _check_job_status(conn, job_id, printer_name)
            return {"success": True, "job_id": job_id, "printer": printer_name}
        except Exception as e:
            logger.exception("CUPS print failed")
            return {"success": False, "error": str(e)}

    # Fallback: lp command (CUPS_SERVER env var directs lp to the remote server)
    try:
        result = subprocess.run(
            ["lp", "-d", printer_name, "-o", "raw", zpl_path],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            logger.error("lp failed: %s", result.stderr.strip())
            return {"success": False, "error": result.stderr.strip()}
        logger.info("lp job submitted to %s: %s", printer_name, result.stdout.strip())
        return {"success": True, "job_id": -1, "printer": printer_name}
    except Exception as e:
        logger.exception("lp print failed")
        return {"success": False, "error": str(e)}
