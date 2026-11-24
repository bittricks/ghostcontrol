"""
Mapeamento absoluto direto para o monitor capturado da maquina alvo.

ATENCAO: este modulo e ESPECIFICO para o setup atual da maquina alvo. Se os
monitores mudarem de posicao/resolucao/quantidade, atualize MONITORS com a
saida de [System.Windows.Forms.Screen]::AllScreens rodada NA MAQUINA ALVO
(ou re-rode a recalibracao empirica descrita abaixo).

HISTORICO DE CALIBRACAO
========================
1) Calibracao original (3 monitores), via Screen.AllScreens na maquina alvo:
     DISPLAY1: X=468,  Y=-1093, 1280x720
     DISPLAY2: X=1920, Y=-13,   1920x1080   <- capturado (Excel)
     DISPLAY3: X=0,    Y=0,     1920x1080   <- primario
   bbox virtual resultante: 3840x2173, MON2 offset (1920,1080).

2) Essa calibracao ficou desatualizada (a maquina alvo passou a operar
   como se so houvesse UM monitor de 1920x1080 do ponto de vista do
   range absoluto do CH9329 — provavelmente os outros 2 monitores foram
   desconectados/desligados ou o arranjo de "estender" virou algo com
   largura virtual total de ~1920, sem mudar a resolucao do monitor
   capturado em si). Sintoma: todo clique/movimento caia comprimido no
   quadrante inferior-direito da tela, sempre com o MESMO erro para o
   mesmo alvo (ou seja, um erro sistematico de escala, nao imprecisao
   aleatoria nem outra pessoa mexendo no mouse).

   Recalibrado empiricamente em 2026-07-02 SEM abrir nenhuma janela na
   maquina alvo: mandamos "move" para varios pontos conhecidos (ex:
   (500,500), (960,540), (100,50)), capturamos o frame e medimos onde o
   cursor realmente apareceu. Ajuste linear:
     real_x = 0.5 * alvo_x + 958   (medido em 4 pontos, erro < 15px)
     real_y = 0.5 * alvo_y + 535
   Resolvendo para achar a geometria "efetiva" que produz essa relacao
   com o codigo antigo (MON2_X=1920, VIRTUAL_W=3840): da exatamente
   VIRTUAL_W_real ~= 1920, VIRTUAL_H_real ~= 1080, MON2_X_real ~= 0,
   MON2_Y_real ~= 0 — ou seja, o monitor capturado hoje EH a area
   inteira do range absoluto (mapeamento 1:1, sem deslocamento).

   Se um dia voltar a ter 3 monitores, restaure o bloco (1) acima em
   MONITORS e ajuste CAPTURED_MONITOR de volta.

O modo absoluto do CH9329 (comando 0x04) mapeia o range 0-4095 para o
retangulo que envolve TODOS os monitores (SM_XVIRTUALSCREEN /
SM_YVIRTUALSCREEN / SM_CXVIRTUALSCREEN / SM_CYVIRTUALSCREEN), nao so
para o monitor primario. Este modulo converte um ponto LOCAL do monitor
capturado (0,0 = canto superior-esquerdo) para os parametros que
build_mouse_absolute_frame espera, reaproveitando
CH9329Controller.move_absolute/click_absolute sem modifica-los.

Vantagem sobre o movimento relativo: relatorios HID absolutos nao sao
afetados pela opcao "Aprimorar precisao do ponteiro" do Windows (que
so altera relatorios relativos), entao o controle fica preciso sem
mexer na configuracao do sistema alvo.
"""

# geometria ATUAL (recalibrada 2026-07-02): um unico monitor efetivo de
# 1920x1080, sem deslocamento — ver HISTORICO DE CALIBRACAO acima.
MONITORS = {
    "DISPLAY2": {"x": 0, "y": 0, "w": 1920, "h": 1080},
}

CAPTURED_MONITOR = "DISPLAY2"


def compute_virtual_bbox(monitors):
    """Bounding box (min_x, min_y, largura, altura) da area de trabalho
    virtual do Windows que envolve todos os monitores informados.

    Aceita qualquer iteravel de dicts; a materializacao em list e
    necessaria porque iteramos mais de uma vez (min/max abaixo) e um
    gerador so pode ser percorrido uma vez."""
    monitors = list(monitors)
    min_x = min(m["x"] for m in monitors)
    min_y = min(m["y"] for m in monitors)
    max_x = max(m["x"] + m["w"] for m in monitors)
    max_y = max(m["y"] + m["h"] for m in monitors)
    return min_x, min_y, max_x - min_x, max_y - min_y


def monitor_offset_in_virtual(monitor, bbox):
    """Deslocamento do canto superior-esquerdo de um monitor dentro do
    bounding box (origem deslocada para 0,0)."""
    min_x, min_y = bbox[0], bbox[1]
    return monitor["x"] - min_x, monitor["y"] - min_y


_BBOX = compute_virtual_bbox(MONITORS.values())

# valores com a geometria ATUAL (monitor unico; com a geometria historica
# de 3 monitores eram 3840x2173 e offset 1920,1080)
VIRTUAL_W = _BBOX[2]   # 1920
VIRTUAL_H = _BBOX[3]   # 1080

_MON2 = MONITORS[CAPTURED_MONITOR]
MON2_X, MON2_Y = monitor_offset_in_virtual(_MON2, _BBOX)   # 0, 0
MON2_W = _MON2["w"]    # 1920
MON2_H = _MON2["h"]    # 1080


def to_virtual(rx, ry):
    """Converte (x,y) local do monitor 2 para (x,y) no espaco virtual que
    build_mouse_absolute_frame/scale_to_abs devem receber junto com
    screen_w=VIRTUAL_W, screen_h=VIRTUAL_H. Pontos fora do monitor sao
    presos na borda para nunca escapar para outro monitor."""
    rx = max(0, min(MON2_W - 1, rx))
    ry = max(0, min(MON2_H - 1, ry))
    return MON2_X + rx, MON2_Y + ry


def move_absolute_mon2(controller, rx, ry, buttons=0, wheel=0):
    vx, vy = to_virtual(rx, ry)
    controller.move_absolute(vx, vy, VIRTUAL_W, VIRTUAL_H, buttons=buttons, wheel=wheel)


def click_absolute_mon2(controller, rx, ry, button):
    vx, vy = to_virtual(rx, ry)
    controller.click_absolute(vx, vy, VIRTUAL_W, VIRTUAL_H, button=button)
