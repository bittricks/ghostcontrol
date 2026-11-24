"""Configuracao de logging compartilhada pelos scripts executaveis.

Ferramentas de relatorio puro (serial_scan.py, probe_devices.py,
device_scan.py) continuam usando print() para a saida tabular que e
o proprio proposito do script. Os demais scripts (que controlam
hardware e tem estados de erro/aviso reais) usam logging."""
import logging


def setup_logging(verbose=False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
