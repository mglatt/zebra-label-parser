"""Submit ZPL print jobs to CUPS."""
from __future__ import annotations

import logging
import os
import subprocess
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
        time.sleep(1)  # brief wait for CUPS to process
        jobs = conn.getJobs(which_jobs="all")
        if job_id in jobs:
            job = jobs[job_id]
            logger.info("Job %d attributes: %s", job_id, dict(job))
            state = job.get("job-state", job.get("job_state", "?"))
            state_reasons = job.get("job-state-reasons",
                                    job.get("job_state_reasons", "none"))
            # CUPS job states: 3=pending, 4=held, 5=processing, 6=stopped,
            #                  7=canceled, 8=aborted, 9=completed
            state_names = {3: "pending", 4: "held", 5: "processing",
                           6: "stopped", 7: "canceled", 8: "aborted", 9: "completed"}
            logger.info("Job %d status: %s (%s), reasons: %s",
                        job_id, state_names.get(state, state), state, state_reasons)
        else:
            logger.warning("Job %d not found in CUPS job list (checked %d jobs)",
                           job_id, len(jobs))
    except Exception:
        logger.exception("Failed to check job %d status", job_id)


def _is_loopback_queue(printer_name: str) -> bool:
    """Detect if a CUPS queue uses the zebrahttp backend (loops back to us).

    Printing to such a queue from within the API would create a recursive
    loop: API → CUPS → zebrahttp backend → API → CUPS → …
    """
    if not _HAS_PYCUPS:
        return False
    try:
        conn = cups.Connection()
        printers = conn.getPrinters()
        info = printers.get(printer_name)
        if info and info.get("device-uri", "").startswith("zebrahttp://"):
            return True
    except Exception:
        pass
    return False


def print_zpl(
    zpl: str,
    printer_name: str,
    cups_server: Optional[str] = None,
) -> dict:
    """Send a ZPL string to a CUPS printer as a raw job."""
    _set_cups_server(cups_server)

    # Guard against printing to a virtual queue that would loop back to us
    if _is_loopback_queue(printer_name):
        msg = (
            f"Printer '{printer_name}' uses the zebrahttp backend which "
            f"loops back to this API. Set printer_name to the physical "
            f"printer (e.g. 'Zebra_LP2844'), not the virtual CUPS queue."
        )
        logger.error(msg)
        return {"success": False, "error": msg}

    logger.info("Printing ZPL (%d bytes) to %s via %s",
                len(zpl), printer_name, "pycups" if _HAS_PYCUPS else "lp")
    logger.info("ZPL preview (first 200 chars): %s", zpl[:200])

    zpl_bytes = zpl.encode("utf-8")

    if _HAS_PYCUPS:
        try:
            conn = cups.Connection()
            # Stream ZPL data directly over IPP instead of using printFile(),
            # which needs a local temp file that the CUPS daemon may not be
            # able to access (e.g. container filesystem isolation).
            job_id = conn.createJob(
                printer_name,
                "zebra-label",
                {"document-format": "application/vnd.cups-raw"},
            )
            conn.startDocument(
                printer_name,
                job_id,
                "zebra-label.zpl",
                "application/vnd.cups-raw",
                1,  # last_document=1 (this is the only document)
            )
            conn.writeRequestData(zpl_bytes, len(zpl_bytes))
            conn.finishDocument(printer_name)
            logger.info("CUPS job %d submitted to %s", job_id, printer_name)
            _check_job_status(conn, job_id, printer_name)
            return {"success": True, "job_id": job_id, "printer": printer_name}
        except Exception as e:
            logger.exception("CUPS print failed")
            return {"success": False, "error": str(e)}

    # Fallback: pipe ZPL via stdin to lp (avoids temp file issues).
    # CUPS_SERVER env var directs lp to the remote server automatically.
    try:
        result = subprocess.run(
            ["lp", "-d", printer_name, "-o", "raw"],
            input=zpl_bytes, capture_output=True, timeout=10,
        )
        if result.returncode != 0:
            logger.error("lp failed: %s", result.stderr.decode().strip())
            return {"success": False, "error": result.stderr.decode().strip()}
        logger.info("lp job submitted to %s: %s",
                     printer_name, result.stdout.decode().strip())
        return {"success": True, "job_id": -1, "printer": printer_name}
    except Exception as e:
        logger.exception("lp print failed")
        return {"success": False, "error": str(e)}
