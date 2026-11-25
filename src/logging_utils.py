"""Shared logging configuration for the executable scripts.

Pure reporting tools (serial_scan.py, probe_devices.py, device_scan.py)
keep using print() for the tabular output that is the script's whole
purpose. The other scripts (which drive hardware and have real
error/warning states) use logging."""
import logging


def setup_logging(verbose=False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
