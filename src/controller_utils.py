"""Conexao ao CH9329: resolucao da porta serial (auto-deteccao do CH340),
compartilhada entre remote_control.py e auto_calibrate.py."""
import logging

from ch9329 import CH9329Controller
from serial_scan import find_ch340_port

logger = logging.getLogger(__name__)


def resolve_controller(port=None, baud=9600, dry_run=False, fallback_dry_run=True):
    """Cria um CH9329Controller resolvendo a porta serial.

    - port=None       -> tenta auto-detectar o adaptador CH340.
    - dry_run=True    -> nunca abre porta; so loga os frames que enviaria.
    - fallback_dry_run: quando nenhum CH340 e encontrado, True cai para
      dry-run com aviso (util no remote_control.py, que ainda serve como
      visualizador); False retorna None (auto_calibrate.py nao faz
      sentido sem hardware de verdade).
    """
    if dry_run:
        return CH9329Controller(port=None, dry_run=True)

    resolved = port or find_ch340_port()
    if resolved is None:
        if fallback_dry_run:
            logger.warning("Nenhum CH340 encontrado. Rodando em dry-run (so exibe os frames, nao envia nada).")
            return CH9329Controller(port=None, dry_run=True)
        logger.error("Nenhum CH340 encontrado. Conecte o hardware ou informe --port.")
        return None

    logger.info("Conectando ao CH9329 via %s @ %s bps", resolved, baud)
    return CH9329Controller(port=resolved, baudrate=baud, dry_run=False)
