import pytest

import ch9329
import hid_keycodes


def test_checksum_is_sum_mod_256():
    assert ch9329.checksum([0x57, 0xAB, 0x00, 0x02, 0x01, 0xFF]) == sum([0x57, 0xAB, 0x00, 0x02, 0x01, 0xFF]) % 256


def test_build_frame_layout_and_checksum():
    frame = ch9329.build_frame(cmd=0x02, data=[1, 2, 3], addr=0x00)
    body = [0x57, 0xAB, 0x00, 0x02, 3, 1, 2, 3]
    assert frame == bytes(body + [sum(body) % 256])


def test_clamp_signed_byte_roundtrips_full_range():
    assert ch9329.clamp_signed_byte(0) == 0
    assert ch9329.clamp_signed_byte(127) == 127
    assert ch9329.clamp_signed_byte(-127) == 256 - 127


def test_clamp_signed_byte_clamps_out_of_range():
    assert ch9329.clamp_signed_byte(200) == 127
    assert ch9329.clamp_signed_byte(-200) == 256 - 127


def test_scale_to_abs_negative_pixel_clamps_to_zero():
    # regressao: scale_to_abs nao deve mais "embrulhar" pixels negativos
    # para o lado oposto do range absoluto (bug corrigido)
    assert ch9329.scale_to_abs(-5, 1920) == 0
    assert ch9329.scale_to_abs(-1, 1920) == 0


def test_scale_to_abs_proportional_mapping():
    assert ch9329.scale_to_abs(0, 1920) == 0
    assert ch9329.scale_to_abs(960, 1920) == 2048


def test_scale_to_abs_clamps_upper_bound():
    assert ch9329.scale_to_abs(1919, 1920) == int((ch9329.ABS_RANGE * 1919) / 1920)
    assert ch9329.scale_to_abs(5000, 1920) == ch9329.ABS_RANGE - 1


def test_build_mouse_absolute_frame_marker_and_command():
    frame = ch9329.build_mouse_absolute_frame(100, 200, 1920, 1080, buttons=ch9329.BUTTON_LEFT)
    assert frame[3] == ch9329.CMD_MOUSE_ABS
    assert frame[5] == ch9329.ABS_MARKER
    assert frame[6] == ch9329.BUTTON_LEFT


def test_build_mouse_relative_frame_marker_and_command():
    frame = ch9329.build_mouse_relative_frame(10, -10, buttons=0)
    assert frame[3] == ch9329.CMD_MOUSE_REL
    assert frame[5] == ch9329.REL_MARKER
    assert frame[6] == 0  # buttons
    assert frame[7] == ch9329.clamp_signed_byte(10)
    assert frame[8] == ch9329.clamp_signed_byte(-10)


def test_build_keyboard_frame_pads_keys_to_six():
    frame = ch9329.build_keyboard_frame(modifier=ch9329.HEAD[0], keycodes=[0x04, 0x05])
    assert frame[3] == ch9329.CMD_KEYBOARD
    assert frame[4] == 8  # len(data): modifier + reservado + 6 keycodes
    keys = list(frame[7:13])
    assert keys == [0x04, 0x05, 0, 0, 0, 0]


def test_click_absolute_sends_button_down_then_up():
    controller = ch9329.CH9329Controller(port=None, dry_run=True)
    sent = []
    controller._send = sent.append

    controller.click_absolute(100, 100, 1920, 1080, button=ch9329.BUTTON_LEFT)

    assert len(sent) == 2
    assert sent[0][6] == ch9329.BUTTON_LEFT
    assert sent[1][6] == 0


def test_press_named_key_unknown_raises():
    controller = ch9329.CH9329Controller(port=None, dry_run=True)
    with pytest.raises(ValueError):
        controller.press_named_key("not-a-real-key")


def test_type_text_unmapped_char_raises():
    controller = ch9329.CH9329Controller(port=None, dry_run=True)
    with pytest.raises(ValueError):
        controller.type_text("€")  # nao esta no CHAR_TABLE


def test_type_text_cedilla_now_mapped_abnt2():
    # regressao: "ç" passou a ser mapeado (usage 0x33 no layout ABNT2)
    controller = ch9329.CH9329Controller(port=None, dry_run=True)
    sent = []
    controller._send = sent.append

    controller.type_text("ç", char_delay=0)

    assert len(sent) == 2  # press + release
    assert sent[0][7] == 0x33  # primeiro keycode do relatorio


class TestPartialTypeError:
    """Falha serial no meio de type_text deve dizer onde parou.

    Regressao do bug que transformava uma senha certa em senha errada: o
    retry reenviava a string inteira e concatenava com o que ja estava no
    campo (ver docs/DESBLOQUEIO_TELA.md secao 4).
    """

    def _controller_que_falha_em(self, limite):
        import serial as _serial
        from ch9329 import CH9329Controller

        ctrl = CH9329Controller.__new__(CH9329Controller)
        ctrl.dry_run = False
        ctrl.addr = 0x00
        enviados = []

        def fake_send(frame):
            # conta so o keydown (keyup vem com modifier/keycode zerados)
            if frame[5] != 0x00 or frame[7] != 0x00:
                if len(enviados) >= limite:
                    raise _serial.SerialException("WriteFile failed")
                enviados.append(frame)

        ctrl._send = fake_send
        return ctrl, enviados

    def test_reporta_quantos_caracteres_sairam(self):
        from ch9329 import PartialTypeError

        ctrl, _ = self._controller_que_falha_em(3)
        with pytest.raises(PartialTypeError) as info:
            ctrl.type_text("abcdef", char_delay=0)
        assert info.value.typed == 3
        assert info.value.remaining == "def"

    def test_remaining_nao_reinclui_o_que_ja_foi_digitado(self):
        from ch9329 import PartialTypeError

        ctrl, _ = self._controller_que_falha_em(4)
        with pytest.raises(PartialTypeError) as info:
            ctrl.type_text("Senha@1234!", char_delay=0)
        # o retry deve mandar SO o restante; concatenar o todo era o bug
        assert info.value.text == "Senha@1234!"
        assert "Senha@1234!".startswith(
            "Senha@1234!"[: info.value.typed])
        assert info.value.remaining == "Senha@1234!"[info.value.typed:]
        assert info.value.remaining != "Senha@1234!"

    def test_acentuado_conta_como_um_caractere(self):
        from ch9329 import PartialTypeError

        # 'a' = 1 evento, 'á' = 2 eventos (tecla-morta + vogal)
        ctrl, _ = self._controller_que_falha_em(3)
        with pytest.raises(PartialTypeError) as info:
            ctrl.type_text("aáx", char_delay=0)
        # 'a'(1) + 'á'(2) = 3 eventos ok, falha ao comecar o 'x'
        assert info.value.typed == 2
        assert info.value.remaining == "x"


class TestReleaseAllKeys:
    """Tecla presa apos falha serial vira atalho acidental.

    Se a falha pega entre keydown e keyup, o chip segura a tecla. Um
    modificador preso (Ctrl/Win) faz as letras seguintes virarem atalhos --
    sintoma observado: a Busca do Windows abrindo sozinha no meio de um texto.
    """

    def test_envia_frame_de_teclado_vazio(self):
        from ch9329 import CH9329Controller, build_keyboard_frame

        ctrl = CH9329Controller.__new__(CH9329Controller)
        ctrl.dry_run = False
        ctrl.addr = 0x00
        enviados = []
        ctrl._send = enviados.append

        ctrl.release_all_keys()

        assert enviados == [build_keyboard_frame(0, [], 0x00)]
        # sem modificador e sem keycode
        assert enviados[0][5] == 0x00
        assert enviados[0][7] == 0x00


def test_type_text_recusa_caractere_nao_medido_antes_de_enviar(monkeypatch):
    """O portao tem que fechar na porta do type_text, nao depois.

    "[" estava no usage 0x2F, que no ABNT2 e o acento agudo: digitar
    "[A" produzia "Á" e o lote seguia reportando sucesso. Hoje o "["
    ja foi medido, entao ele e reinjetado como nao medido: o teste e
    do portao, nao da lista.
    """
    monkeypatch.setattr(hid_keycodes, "UNVERIFIED_CHARS", frozenset("["))
    controller = ch9329.CH9329Controller(port=None, dry_run=True)
    sent = []
    controller._send = sent.append

    with pytest.raises(hid_keycodes.UnverifiedMapping):
        controller.type_text("a[b", char_delay=0)

    # o "a" pode ter saido (a validacao e por caractere), mas nenhum
    # evento do caractere suspeito foi enviado
    assert len(sent) == 2  # so o press+release do "a"


def test_type_text_allow_unverified_libera_para_o_probe(monkeypatch):
    # "^" ja foi medido (probe de 2026-11-07), entao o nao medido e
    # injetado: o que este teste prende e a flag, nao a lista.
    monkeypatch.setattr(hid_keycodes, "UNVERIFIED_CHARS", frozenset("^"))
    controller = ch9329.CH9329Controller(port=None, dry_run=True)
    sent = []
    controller._send = sent.append

    controller.type_text("^", char_delay=0, allow_unverified=True)

    # tecla morta + espaco = 2 eventos = 4 frames
    assert len(sent) == 4


# ---------------------------------------------------------------------
# parse_info: leitura das luzes do teclado no alvo.
#
# Existe porque em 2026-11-07 uma senha correta foi recusada pelo
# Windows e nao havia NENHUMA forma de ver o estado do Caps Lock: o
# chip aceita a tecla, o alvo acende a luz, e nada disso aparecia no
# response. Caps Lock preso nao gera erro -- so troca a caixa de toda
# letra, e o sintoma ("senha incorreta") aparece longe da causa.
# ---------------------------------------------------------------------

def _frame_info(leds, versao=0x30, usb=0x01, cmd=0x81, addr=0x00):
    corpo = [0x57, 0xAB, addr, cmd, 0x08, versao, usb, leds, 0, 0, 0, 0, 0]
    corpo.append(sum(corpo) % 256)
    return bytes(corpo)


def test_parse_info_le_caps_lock_ligado():
    info = ch9329.parse_info(_frame_info(ch9329.LED_CAPS_LOCK))
    assert info["caps_lock"] is True
    assert info["num_lock"] is False
    assert info["scroll_lock"] is False


def test_parse_info_separa_as_tres_luzes():
    """Cada bit tem que ser lido no seu proprio lugar. Um parser que
    troque num por caps passa num teste de uma luz so."""
    casos = [
        (ch9329.LED_NUM_LOCK, "num_lock"),
        (ch9329.LED_CAPS_LOCK, "caps_lock"),
        (ch9329.LED_SCROLL_LOCK, "scroll_lock"),
    ]
    for bit, nome in casos:
        info = ch9329.parse_info(_frame_info(bit))
        ligadas = [k for k in ("num_lock", "caps_lock", "scroll_lock") if info[k]]
        assert ligadas == [nome], "bit 0x%02X acendeu %s" % (bit, ligadas)


def test_parse_info_le_as_tres_juntas():
    info = ch9329.parse_info(_frame_info(0x07))
    assert (info["num_lock"], info["caps_lock"], info["scroll_lock"]) == (True, True, True)


def test_parse_info_nenhuma_luz():
    info = ch9329.parse_info(_frame_info(0x00))
    assert not any(info[k] for k in ("num_lock", "caps_lock", "scroll_lock"))


def test_parse_info_le_usb_e_versao():
    info = ch9329.parse_info(_frame_info(0x00, versao=0x31, usb=0x00))
    assert info["versao"] == 0x31
    assert info["usb_conectado"] is False


@pytest.mark.parametrize("ruim, motivo", [
    (None, "resposta ausente"),
    (b"", "resposta vazia"),
    (b"\x57\xAB\x00\x81", "curta demais"),
    (b"\x00\x00\x00\x81\x08\x30\x01\x02\x00", "cabecalho errado"),
    (b"\x57\xAB\x00\x82\x08\x30\x01\x02\x00", "eco de outro comando"),
])
def test_parse_info_recusa_resposta_invalida(ruim, motivo):
    """Entrada invalida tem que LEVANTAR, nunca devolver tudo desligado.

    Um falso "caps_lock: False" e pior que um erro: ele passa por
    diagnostico e inocenta justamente a causa que se foi investigar."""
    with pytest.raises(ValueError):
        ch9329.parse_info(ruim)
