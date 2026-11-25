"""CH9329 connection: serial-port resolution (CH340 auto-detection),
shared between remote_control.py and auto_calibrate.py."""
import logging

from ch9329 import CH9329Controller
from serial_scan import find_ch340_port

logger = logging.getLogger(__name__)


def resolve_controller(port=None, baud=9600, dry_run=False, fallback_dry_run=True):
    """Create a CH9329Controller, resolving the serial port.

    - port=None       -> try to auto-detect the CH340 adapter.
    - dry_run=True    -> never opens a port; only logs the frames it would send.
    - fallback_dry_run: when no CH340 is found, True falls back to dry-run
      with a warning (handy in remote_control.py, which also doubles as a
      viewer); False returns None (auto_calibrate.py makes no sense without
      real hardware).
    """
    if dry_run:
        return CH9329Controller(port=None, dry_run=True)

    resolved = port or find_ch340_port()
    if resolved is None:
        if fallback_dry_run:
            logger.warning("No CH340 found. Running in dry-run (frames are only shown, nothing is sent).")
            return CH9329Controller(port=None, dry_run=True)
        logger.error("No CH340 found. Connect the hardware or pass --port.")
        return None

    logger.info("Connecting to the CH9329 over %s @ %s bps", resolved, baud)
    return CH9329Controller(port=resolved, baudrate=baud, dry_run=False)
