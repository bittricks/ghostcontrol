import json
import logging
import os

logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

DEFAULT_CONFIG = {
    "capture_index": 0,
    "capture_backend": "dshow",
    "requested_width": 1920,
    "requested_height": 1080,
    "requested_fps": 30,
}


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Nao foi possivel ler %s (%s). Usando configuracao padrao.", CONFIG_PATH, exc)
            return dict(DEFAULT_CONFIG)
        if not isinstance(data, dict):
            logger.warning("%s nao contem um objeto JSON valido. Usando configuracao padrao.", CONFIG_PATH)
            return dict(DEFAULT_CONFIG)
        merged = dict(DEFAULT_CONFIG)
        merged.update(data)
        return merged
    return dict(DEFAULT_CONFIG)


def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def queue_dir():
    """Diretorio da fila do daemon, FORA de uma pasta sincronizada (OneDrive, Dropbox, iCloud).

    Mesma razao da credencial: queue/frames/ guarda capturas da tela do
    alvo (conversas e dados privados de terceiros) e o resto do runtime;
    sob o Desktop (Known Folder Move) tudo isso subia para a nuvem em
    texto claro. O .gitignore protege o git, nao a pasta sincronizada. Ordem:

      1. VERIKVM_QUEUE_DIR -- override explicito (caminho completo);
      2. %LOCALAPPDATA%\\VeriKVM\\queue -- LOCALAPPDATA nao sincroniza;
      3. <projeto>/queue -- so compatibilidade (pode estar sincronizado).

    FONTE UNICA: daemon (consumidor) e wake_/keep_alive_* (produtores)
    resolvem por aqui. Se divergirem, requests caem num lugar e o daemon
    observa outro -- a fila para em silencio.
    """
    override = os.environ.get("VERIKVM_QUEUE_DIR")
    if override:
        return override
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return os.path.join(local, "VeriKVM", "queue")
    return os.path.join(os.path.dirname(__file__), "queue")
