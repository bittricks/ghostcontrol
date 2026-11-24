"""
Implementacao do protocolo serial do chip CH9329 (bridge UART -> USB HID
teclado/mouse). O modulo CH9329 e conectado ao PC controlador via um
adaptador USB-serial CH340 (aparece como porta COM) e ao PC alvo via USB,
onde se comporta como um teclado/mouse USB de verdade.

Especificacao do frame:
  [0x57] [0xAB] [ADDR] [CMD] [LEN] [DATA...] [SUM]
  SUM = soma de todos os bytes anteriores, mod 256

Comandos usados:
  0x02 -> teclado (relatorio HID boot de 8 bytes: mod, reservado, k0..k5)
  0x04 -> mouse absoluto (marcador 0x02, botoes, X 16bit LE, Y 16bit LE, wheel)
  0x05 -> mouse relativo (marcador 0x01, botoes, dx, dy, wheel)

Fonte: datasheet WCH CH9329 + implementacao de referencia kvm-serial
(docs/CH9329_PROTO.md, derivada de beijixiaohu/CH9329_COMM).
"""
import logging
import time

import serial

from hid_keycodes import char_to_usage, char_to_sequence, named_key_to_usage


class PartialTypeError(serial.SerialException):
    """Falha serial NO MEIO de um type_text.

    `typed` = quantos caracteres de `text` ja foram enviados com sucesso.
    Quem tratar deve reenviar apenas `text[typed:]`; reenviar a string
    inteira duplica o que ja esta no campo de destino.
    """

    def __init__(self, typed, text, original):
        super().__init__(str(original))
        self.typed = typed
        self.text = text
        self.original = original

    @property
    def remaining(self):
        """O trecho que ainda falta digitar."""
        return self.text[self.typed:]

logger = logging.getLogger(__name__)

HEAD = (0x57, 0xAB)

CMD_GET_INFO  = 0x01   # retorna info do dispositivo (lock keys, status USB)
CMD_KEYBOARD  = 0x02
CMD_MOUSE_ABS = 0x04
CMD_MOUSE_REL = 0x05
CMD_RESET     = 0x0F   # restaura configuracao padrao e reinicia o chip

# Frame de ACK: header(2)+addr(1)+(cmd|0x80)(1)+len(1)+status(1)+sum(1) = 7 bytes
# status 0x00 = OK; outros valores = erro (checksum invalido, cmd desconhecido...)
ACK_LEN = 7

ABS_MARKER = 0x02
REL_MARKER = 0x01

BUTTON_LEFT = 0x01
BUTTON_RIGHT = 0x02
BUTTON_MIDDLE = 0x04

ABS_RANGE = 4096

# Bits do byte de LEDs na resposta do CMD_GET_INFO. Sao as luzes REAIS
# que o Windows alvo mandou acender, entao e a unica forma honesta de
# saber o estado dos travamentos: o chip nao guarda isso, o alvo e quem
# manda. Importa porque Caps Lock preso NAO da erro em lugar nenhum --
# ele so troca a caixa de toda letra digitada, silenciosamente, e o
# sintoma aparece longe da causa (ex.: "senha incorreta").
LED_NUM_LOCK = 0x01
LED_CAPS_LOCK = 0x02
LED_SCROLL_LOCK = 0x04

# Posicoes dentro do frame de resposta do GET_INFO:
# 57 AB <addr> 81 <len> <versao> <status usb> <leds> ... <sum>
INFO_CMD_ECHO = 0x81
INFO_IDX_VERSAO = 5
INFO_IDX_USB = 6
INFO_IDX_LEDS = 7
INFO_MIN_LEN = 8


def parse_info(frame):
    """Interpreta a resposta do CMD_GET_INFO.

    Separado de get_info() de proposito: o parser e testavel sem porta
    serial, que e onde moram os erros de indice e de bit.

    Devolve dict com versao, usb_conectado, num/caps/scroll e o byte cru.
    Levanta ValueError se o frame nao for uma resposta de GET_INFO --
    frame curto, cabecalho errado ou eco de comando diferente. Nunca
    devolve "tudo desligado" para entrada invalida: um falso "Caps Lock
    desligado" e pior que um erro, porque passa por diagnostico.
    """
    if not frame:
        raise ValueError("GET_INFO nao respondeu (None ou vazio)")
    b = bytes(frame)
    if len(b) < INFO_MIN_LEN:
        raise ValueError(
            "resposta de GET_INFO curta demais: %d bytes (%s)" % (len(b), b.hex(" ")))
    if b[0] != HEAD[0] or b[1] != HEAD[1]:
        raise ValueError("cabecalho inesperado em GET_INFO: %s" % b.hex(" "))
    if b[3] != INFO_CMD_ECHO:
        raise ValueError(
            "eco de comando 0x%02X, esperado 0x%02X: %s"
            % (b[3], INFO_CMD_ECHO, b.hex(" ")))
    leds = b[INFO_IDX_LEDS]
    return {
        "versao": b[INFO_IDX_VERSAO],
        "usb_conectado": bool(b[INFO_IDX_USB]),
        "leds": leds,
        "num_lock": bool(leds & LED_NUM_LOCK),
        "caps_lock": bool(leds & LED_CAPS_LOCK),
        "scroll_lock": bool(leds & LED_SCROLL_LOCK),
        "raw": b.hex(" "),
    }


def checksum(bytes_so_far):
    return sum(bytes_so_far) % 256


def build_frame(cmd, data, addr=0x00):
    body = [HEAD[0], HEAD[1], addr, cmd, len(data)] + list(data)
    body.append(checksum(body))
    return bytes(body)


def clamp_signed_byte(value):
    # & 0xFF ja produz o complemento-de-dois para negativos em Python
    # (-1 & 0xFF == 255), entao um unico caminho cobre os dois sinais
    return max(-127, min(127, int(value))) & 0xFF


def scale_to_abs(pixel, dimension):
    dimension = max(1, dimension)
    scaled = int((ABS_RANGE * pixel) / dimension)
    return max(0, min(ABS_RANGE - 1, scaled))


def build_mouse_absolute_frame(x, y, screen_w, screen_h, buttons=0, wheel=0, addr=0x00):
    abs_x = scale_to_abs(x, screen_w)
    abs_y = scale_to_abs(y, screen_h)
    data = [
        ABS_MARKER,
        buttons & 0xFF,
        abs_x & 0xFF,
        (abs_x >> 8) & 0xFF,
        abs_y & 0xFF,
        (abs_y >> 8) & 0xFF,
        clamp_signed_byte(wheel),
    ]
    return build_frame(CMD_MOUSE_ABS, data, addr=addr)


def build_mouse_relative_frame(dx, dy, buttons=0, wheel=0, addr=0x00):
    data = [
        REL_MARKER,
        buttons & 0xFF,
        clamp_signed_byte(dx),
        clamp_signed_byte(dy),
        clamp_signed_byte(wheel),
    ]
    return build_frame(CMD_MOUSE_REL, data, addr=addr)


def build_keyboard_frame(modifier=0, keycodes=(), addr=0x00):
    # relatorio boot exige exatamente 6 keycodes: trunca e preenche com 0
    keys = list(keycodes)[:6]
    keys += [0] * (6 - len(keys))
    data = [modifier & 0xFF, 0x00] + keys
    return build_frame(CMD_KEYBOARD, data, addr=addr)


class CH9329Controller:
    """Controlador de alto nivel sobre a porta serial do CH340/CH9329."""

    def __init__(self, port, baudrate=9600, addr=0x00, dry_run=False, timeout=1):
        self.addr = addr
        self.dry_run = dry_run
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._serial = None
        if not dry_run:
            self._serial = serial.Serial(port, baudrate=baudrate, timeout=timeout)

    def close(self):
        if self._serial is not None:
            self._serial.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def reconnect(self):
        """Fecha e reabre a porta serial. Util apos SerialException."""
        if self.dry_run:
            return
        try:
            if self._serial and self._serial.is_open:
                self._serial.close()
        except Exception:
            pass
        self._serial = serial.Serial(self._port, baudrate=self._baudrate,
                                     timeout=self._timeout)
        # Se a falha anterior pegou entre o keydown e o keyup, o chip ficou
        # com tecla (possivelmente modificadora) presa -- e um Ctrl/Win preso
        # transforma as letras seguintes em atalhos. Solta tudo ao reconectar.
        self.release_all_keys()
        logger.info("reconectado a %s @ %d bps", self._port, self._baudrate)

    def _send(self, frame):
        if self.dry_run:
            # nivel INFO (nao DEBUG): e o proposito do dry-run mostrar
            # os frames que seriam enviados, deve aparecer por padrao
            logger.info("[dry-run] -> %s", frame.hex(" "))
            return
        self._serial.write(frame)

    def _read_ack(self, cmd, ack_timeout=0.15):
        """Le o frame de ACK gerado pelo chip apos qualquer comando.
        Retorna True se status == 0x00 (OK), False em timeout ou erro."""
        if self._serial is None:
            return False
        old_timeout = self._serial.timeout
        self._serial.timeout = ack_timeout
        try:
            resp = self._serial.read(ACK_LEN)
        finally:
            self._serial.timeout = old_timeout
        if len(resp) < ACK_LEN:
            logger.debug("ACK timeout para cmd 0x%02x (%d bytes)", cmd, len(resp))
            return False
        expected = (cmd | 0x80) & 0xFF
        if resp[0] != 0x57 or resp[1] != 0xAB or resp[3] != expected:
            logger.debug("ACK inesperado: %s", resp.hex(" "))
            return False
        return resp[5] == 0x00

    def send_with_ack(self, frame, retries=2, ack_timeout=0.15):
        """Envia frame e aguarda ACK; tenta ate `retries` vezes.

        Use para operacoes criticas (chip_reset, comandos de configuracao).
        Para type_text em loop, continue usando _send (fire-and-forget) para
        nao introduzir ~150ms de latencia por tecla.

        Retorna True se o chip confirmou OK.
        """
        if self.dry_run:
            logger.info("[dry-run] -> %s", frame.hex(" "))
            return True
        cmd = frame[3]
        for attempt in range(retries):
            self._serial.reset_input_buffer()
            self._serial.write(frame)
            if self._read_ack(cmd, ack_timeout=ack_timeout):
                return True
            logger.warning("ACK ausente para cmd 0x%02x (tentativa %d/%d)",
                           cmd, attempt + 1, retries)
        return False

    def chip_reset(self):
        """Envia CMD_RESET (0x0F): restaura configuracao padrao do chip."""
        frame = build_frame(CMD_RESET, [], addr=self.addr)
        if self.dry_run:
            logger.info("[dry-run] chip_reset -> %s", frame.hex(" "))
            return
        self._serial.reset_input_buffer()
        self._serial.write(frame)
        time.sleep(0.1)  # aguarda o chip reinicializar
        self._serial.reset_input_buffer()
        logger.info("chip_reset enviado")

    def get_info(self):
        """Envia CMD_GET_INFO (0x01) e retorna o frame de resposta bruto.
        Retorna bytes ou None em dry-run/timeout."""
        frame = build_frame(CMD_GET_INFO, [], addr=self.addr)
        if self.dry_run:
            logger.info("[dry-run] get_info -> %s", frame.hex(" "))
            return None
        self._serial.reset_input_buffer()
        self._serial.write(frame)
        old_timeout = self._serial.timeout
        self._serial.timeout = 0.5
        try:
            resp = self._serial.read(64)
        finally:
            self._serial.timeout = old_timeout
        return resp if resp else None

    def lock_state(self):
        """Estado das luzes do teclado no ALVO (num/caps/scroll).

        Em dry-run devolve None. Fora dele, qualquer resposta invalida
        levanta ValueError via parse_info -- ver o porque la."""
        resp = self.get_info()
        if resp is None and self.dry_run:
            return None
        return parse_info(resp)

    def move_absolute(self, x, y, screen_w, screen_h, buttons=0, wheel=0):
        self._send(build_mouse_absolute_frame(x, y, screen_w, screen_h, buttons, wheel, self.addr))

    def move_relative(self, dx, dy, buttons=0, wheel=0):
        self._send(build_mouse_relative_frame(dx, dy, buttons, wheel, self.addr))

    def click_absolute(self, x, y, screen_w, screen_h, button=BUTTON_LEFT):
        self.move_absolute(x, y, screen_w, screen_h, buttons=button)
        self.move_absolute(x, y, screen_w, screen_h, buttons=0)

    def release_all_keys(self):
        """Envia um frame de teclado vazio: solta qualquer tecla/modificador.

        Idempotente e barato. Use apos reconectar ou ao suspeitar de tecla
        presa (sintoma classico: letras digitadas viram atalhos, p.ex. a
        Busca do Windows abrindo sozinha no meio de um texto por `Win+s`).
        """
        self._send(build_keyboard_frame(0, [], self.addr))

    def key_press(self, keycode, modifier=0, hold_seconds=0.0):
        self._send(build_keyboard_frame(modifier, [keycode], self.addr))
        if hold_seconds > 0:
            time.sleep(hold_seconds)
        self._send(build_keyboard_frame(0, [], self.addr))

    def press_named_key(self, name, modifier=0):
        usage_id = named_key_to_usage(name)
        if usage_id is None:
            raise ValueError(f"tecla nomeada desconhecida: {name}")
        self.key_press(usage_id, modifier)

    def type_text(self, text, char_delay=0.03, allow_unverified=False):
        """Digita `text` tecla por tecla.

        char_delay default 0.03s = o piso util desta ligacao. Cada evento de
        tecla sao 2 frames de 14 bytes; a 9600 8N1 isso da ~29ms de linha
        serial, entao pedir menos nao acelera e na pratica desacelera (o
        buffer do driver enche e o write bloqueia). Acima do piso o delay
        manda: 0.05 pedido mede 49.8ms/evento, 0.15 mede 148.8ms/evento.
        Use valores altos (~0.15) so onde ha antideteccao de bot a
        considerar, como em apps de mensageria.

        `allow_unverified` libera os caracteres de
        hid_keycodes.UNVERIFIED_CHARS, cujo usage e deduzido do layout
        ABNT2 mas nunca foi lido de volta na tela. Existe para o probe
        (probe_punctuation.py): num lote de verdade, digitar um usage
        nao medido corrompe em silencio.
        """
        for index, char in enumerate(text):
            seq = char_to_sequence(char, allow_unverified=allow_unverified)
            if seq is None:
                raise ValueError(f"caractere sem mapeamento HID: {char!r}")
            # Acentuado = 2 eventos (tecla-morta + vogal), e tecla morta
            # literal = tecla-morta + espaco. O char_delay entre eles e
            # essencial: sem o intervalo a tecla-morta nao "arma".
            try:
                for usage_id, modifier in seq:
                    self.key_press(usage_id, modifier)
                    if char_delay > 0:
                        time.sleep(char_delay)
            except serial.SerialException as exc:
                # Informa QUANTOS caracteres ja sairam, para quem for tentar de
                # novo reenviar apenas o restante. Reenviar a string inteira
                # concatena com o que ja esta no campo -- foi o que ja
                # transformou uma senha certa em senha errada.
                raise PartialTypeError(index, text, exc) from exc
