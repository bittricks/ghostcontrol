"""Testes do classificador de estado da tela do alvo.

O teste que mais importa aqui e o que proibe UMA amostra: foi a leitura
unica que me fez afirmar duas vezes que a tela estava bloqueada quando
ela ja estava destravada (APRENDIZADOS item 35).
"""
import pytest

import target_state as ts

numpy = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")


def frame_preto(w=320, h=200):
    return numpy.zeros((h, w, 3), dtype=numpy.uint8)


def frame_barras(w=320, h=200):
    """Barras SMPTE sinteticas: colunas saturadas e uniformes na vertical."""
    cores = [(255, 255, 255), (0, 255, 255), (255, 255, 0), (0, 255, 0),
             (255, 0, 255), (0, 0, 255), (255, 0, 0), (0, 0, 0)]
    img = numpy.zeros((h, w, 3), dtype=numpy.uint8)
    largura = w // len(cores)
    for i, cor in enumerate(cores):
        img[:, i * largura:(i + 1) * largura] = cor
    return img


def frame_bloqueio(texto, w=960, h=540):
    """Tela de bloqueio: FOTO.

    O que faz dela uma foto para o classificador nao e a cor, e sim a
    AUSENCIA de cor chapada: gradiente mais ruido, de modo que nenhuma
    cor exata se repete muito. E assim que a foto do rig se comporta,
    inclusive a escura e dessaturada que derrubou a versao anterior.
    """
    rng = numpy.random.RandomState(3)
    # faixa estreita de luminancia: a foto nao pode partir a tela em
    # duas metades no limiar de Otsu, senao o OCR do teste falha por um
    # motivo que nao existe na tela real.
    gx = numpy.linspace(40, 115, w, dtype=numpy.float32)
    gy = numpy.linspace(0, 25, h, dtype=numpy.float32)
    base = gx[None, :] + gy[:, None]
    img = numpy.empty((h, w, 3), dtype=numpy.uint8)
    for c, peso in enumerate((1.0, 0.55, 0.25)):
        # ruido baixo de proposito: foto de verdade e LISA. O que a
        # derruba no portao nao e ser ruidosa, e nao repetir cor exata.
        canal = base * peso + rng.normal(0, 1.5, size=(h, w))
        img[:, :, c] = numpy.clip(canal, 0, 255).astype(numpy.uint8)
    # Caixa de campo atras do texto, como a do login do Windows. Clara
    # com texto escuro de proposito: o pipeline de OCR binariza por
    # Otsu e le escuro-sobre-claro, e nao e papel deste teste medir a
    # polaridade do Tesseract. Ela ocupa ~6% da tela, longe de virar
    # cor chapada.
    x0, y0 = w // 4 - 20, h // 2 - 40
    cv2.rectangle(img, (x0, y0 - 70), (x0 + w // 2, y0 + 60), (228, 230, 232), -1)
    # O nome do usuario acima do campo nao e enfeite: com --psm 6 o
    # Tesseract devolve VAZIO para uma palavra solta numa tela quase
    # vazia. A tela de login de verdade tem essa linha, e e por isso
    # que o marcador e achado nela.
    cv2.putText(img, "Usuario Local", (w // 4, h // 2 - 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (25, 25, 25), 2, cv2.LINE_AA)
    cv2.putText(img, texto, (w // 4, h // 2), cv2.FONT_HERSHEY_SIMPLEX,
                1.0, (25, 25, 25), 2, cv2.LINE_AA)
    return img


def frame_app(texto="Arquivo Inserir Dados", w=960, h=540):
    """Aplicativo: um fundo de COR EXATA cobrindo boa parte da tela."""
    img = numpy.full((h, w, 3), 240, dtype=numpy.uint8)
    for y in range(0, h, 9):          # linhas de grade
        img[y:y + 1, :] = 120
    for x in range(0, w, 60):
        img[:, x:x + 1] = 120
    cv2.putText(img, texto, (20, 30), cv2.FONT_HERSHEY_SIMPLEX,
                0.7, (20, 20, 20), 2, cv2.LINE_AA)
    return img


def precisa_ocr():
    import screen_utils
    if screen_utils.locate_tesseract() is None:
        pytest.skip("Tesseract nao instalado")


# ---------------------------------------------------------------------------
# a regra das duas amostras
# ---------------------------------------------------------------------------

def test_uma_amostra_nao_classifica():
    """O ponto do modulo. Um frame pode ser o velho, servido pelo buffer."""
    with pytest.raises(ValueError) as exc:
        ts.classify([frame_preto()])
    assert "2+ amostras" in str(exc.value)


def test_zero_amostras_tambem_e_erro():
    with pytest.raises(ValueError):
        ts.classify([])


def test_amostras_que_discordam_dao_indeterminado():
    """Transicao de sinal nao pode virar um veredito escolhido a esmo."""
    r = ts.classify([frame_preto(), frame_barras()])
    assert r["estado"] == ts.INDETERMINADO
    assert r["concorda"] is False
    assert set(r["por_frame"]) == {ts.PRETO, ts.SEM_SINAL}


def test_amostras_que_concordam_dao_o_estado():
    r = ts.classify([frame_preto(), frame_preto()])
    assert r["estado"] == ts.PRETO
    assert r["concorda"] is True


# ---------------------------------------------------------------------------
# os estados
# ---------------------------------------------------------------------------

def test_tela_preta():
    estado, st = ts.classify_frame(frame_preto())
    assert estado == ts.PRETO
    assert st["media"] <= ts.PRETO_MEDIA_MAX


def test_barras_de_cor_sao_falta_de_sinal():
    estado, st = ts.classify_frame(frame_barras())
    assert estado == ts.SEM_SINAL
    assert st["faixas"] >= ts.BARRAS_FAIXAS_MIN
    # o que distingue barras de uma tela real: a coluna e uniforme
    assert st["desvio_vertical"] <= ts.BARRAS_DESVIO_VERTICAL_MAX


def test_barras_nao_se_confundem_com_tela_colorida_de_verdade():
    """Uma tela real tem conteudo variando na vertical."""
    img = frame_barras()
    # risca horizontal escura: quebra a uniformidade vertical
    img[80:110, :] = 20
    estado, st = ts.classify_frame(img)
    assert st["desvio_vertical"] > ts.BARRAS_DESVIO_VERTICAL_MAX
    assert estado != ts.SEM_SINAL


def test_campo_de_senha_e_reconhecido():
    precisa_ocr()
    estado, st = ts.classify_frame(frame_bloqueio("Senha"))
    assert estado == ts.BLOQUEIO_SENHA
    assert st["marcador"] == "Senha"


def test_bloqueio_com_foto_e_reconhecido():
    precisa_ocr()
    estado, _ = ts.classify_frame(frame_bloqueio("Bloqueado"))
    assert estado == ts.BLOQUEIO_FOTO


def test_senha_ganha_de_bloqueado_quando_os_dois_aparecem():
    """Ordem importa: o campo de senha e o estado mais especifico, e a
    tela de bloqueio tambem mostra clima e relogio."""
    precisa_ocr()
    estado, _ = ts.classify_frame(frame_bloqueio("Bloqueado Senha"))
    assert estado == ts.BLOQUEIO_SENHA


def test_tela_sem_marcador_de_bloqueio_e_app():
    precisa_ocr()
    estado, _ = ts.classify_frame(frame_app())
    assert estado == ts.APP


# ---------------------------------------------------------------------------
# pode_digitar
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("estado,esperado", [
    (ts.APP, True),
    (ts.BLOQUEIO_SENHA, True),
    (ts.BLOQUEIO_FOTO, False),
    (ts.PRETO, False),
    (ts.SEM_SINAL, False),
])
def test_pode_digitar_so_nos_dois_estados_que_aceitam_teclado(estado, esperado):
    assert ts.pode_digitar({"estado": estado, "concorda": True}) is esperado


def test_indeterminado_nunca_pode_digitar():
    """Com as amostras discordando o sinal esta em transicao: um lote
    comecado agora pode cair na janela que aparecer no meio dele."""
    assert ts.pode_digitar({"estado": ts.APP, "concorda": False}) is False
    assert ts.pode_digitar({"estado": ts.INDETERMINADO, "concorda": False}) is False


def test_amostrar_captura_pelo_menos_duas_vezes():
    chamadas = []

    def captura():
        chamadas.append(1)
        return frame_preto()

    r = ts.amostrar(captura, amostras=1, intervalo=0)  # pede 1...
    assert len(chamadas) == 2                          # ...e leva 2
    assert r["estado"] == ts.PRETO


# ---------------------------------------------------------------------------
# o portao de pixel antes do OCR
# ---------------------------------------------------------------------------

def test_tela_de_app_com_a_palavra_senha_continua_sendo_app():
    """A regressao que os frames REAIS pegaram.

    A primeira versao procurava "Senha" na tela inteira e chamou a
    planilha do Excel de tela de login -- a palavra aparece em algum
    canto. Marcador curto em area grande acha qualquer coisa; por isso
    o OCR so roda depois do portao de pixel.
    """
    precisa_ocr()
    estado, st = ts.classify_frame(frame_app("Planilha Senha Arquivo"))
    assert st["parece_app"] is True
    assert estado == ts.APP


# numeros LIDOS dos 29 frames reais do rig, rotulados a olho em
# 2026-11-07. Os extremos sao o que importa: sao eles que decidem se o
# limiar ainda separa.
CHAPADA_BLOQUEIO = (0.0042, 0.0109, 0.1441, 0.1446)
CHAPADA_APP = (0.4195, 0.4347, 0.4999, 0.5455, 0.6302)

# Ainda em 2026-11-07, depois dos 29: varredura dos 114 frames que
# existem em queue/frames/. Nao e amostra escolhida por mim, e todo o
# material disponivel -- a regra que o limiar anterior violou.
#
# O caso adversario e a tela de BLOQUEIO_SENHA: ela tem painel de
# INTERFACE por cima da foto, entao e a unica que poderia forjar a
# prova de aplicativo e liberar o teclado num campo de senha. Medida
# nos tres frames reais que existem dela (411_unlock,
# 504_diag_login_step5, 505_diag_aviso_step2): o painel do Windows e
# acrilico desfocado, nao cor chapada, e nenhum dos tres chega perto.
CHAPADA_SENHA = (0.0043, 0.0043, 0.0043)

# Vizinhos mais proximos do limiar nos 114: nada cai entre os dois.
CHAPADA_MAIOR_BLOQUEIO = 0.1440      # 602_acorda2_step6.png
CHAPADA_MENOR_APP = 0.4071           # 608_olha_step1.png


def test_limiar_separa_os_frames_reais_medidos():
    for v in CHAPADA_BLOQUEIO:
        assert v < ts.APP_COR_CHAPADA_MIN
    for v in CHAPADA_APP:
        assert v >= ts.APP_COR_CHAPADA_MIN


def test_limiar_tem_folga_dos_dois_lados():
    """Encostar no limiar e tao ruim quanto passar dele: diz que a
    separacao sobreviveu por acaso. Exige-se pelo menos 1.5x de folga
    para cada lado do pior caso real."""
    assert max(CHAPADA_BLOQUEIO) * 1.5 <= ts.APP_COR_CHAPADA_MIN
    assert min(CHAPADA_APP) >= ts.APP_COR_CHAPADA_MIN * 1.5


def test_tela_de_senha_nao_forja_prova_de_aplicativo():
    """O caso adversario do portao, e o unico que importa de verdade.

    A tela de senha e o estado em que digitar as cegas custa caro: o
    orcamento e de 3 tentativas. E e o unico estado bloqueado que tem
    painel de interface na tela, entao e o candidato natural a forjar
    a mancha de cor chapada.

    Nao forja: o painel do Windows e acrilico desfocado -- cada pixel
    e uma cor ligeiramente diferente, que e o oposto de chapado."""
    for v in CHAPADA_SENHA:
        assert v < ts.APP_COR_CHAPADA_MIN
    # nao basta ficar do lado certo: tem que ficar MUITO longe, senao
    # um papel de parede diferente derruba a classificacao.
    assert max(CHAPADA_SENHA) * 10 < ts.APP_COR_CHAPADA_MIN


def test_nenhum_frame_real_cai_perto_do_limiar():
    """Varredura dos 114 frames em disco: a faixa 0.15-0.45 esta vazia.

    Um limiar cujos vizinhos mais proximos estao a 0.14 e 0.41 nao foi
    escolhido para passar na amostra -- ele cabe em qualquer ponto de
    um vao de 0.26 de largura."""
    assert CHAPADA_MAIOR_BLOQUEIO < ts.APP_COR_CHAPADA_MIN
    assert CHAPADA_MENOR_APP >= ts.APP_COR_CHAPADA_MIN
    vao = CHAPADA_MENOR_APP - CHAPADA_MAIOR_BLOQUEIO
    assert vao > 0.25, "o vao encolheu: remedir antes de confiar"


def test_os_contraexemplos_que_derrubaram_a_versao_anterior():
    """Os dois frames reais que refutaram saturacao e detalhe vertical.

    VS Code no tema escuro: saturacao 180 e detalhe 35 -- pelos eixos
    antigos, "foto". Tela de bloqueio com foto escura de asfalto:
    saturacao 26 e detalhe 46 -- pelos eixos antigos, "aplicativo", e
    esse era o erro caro, porque liberava o teclado na tela de senha.

    Pela cor chapada os dois sao classificados certo, e e isso que este
    teste prende."""
    vscode_escuro = 0.5455       # medido em 316_keepalive_step4.png
    bloqueio_escuro = 0.1446     # medido em 603_revela_step2.png
    assert vscode_escuro >= ts.APP_COR_CHAPADA_MIN
    assert bloqueio_escuro < ts.APP_COR_CHAPADA_MIN


def test_app_precisa_de_prova_e_nao_e_o_que_sobra():
    """A inversao que fez o conserto.

    Um frame sem nenhuma cor chapada -- ruido puro -- nao e nada que o
    classificador conheca. Ele NAO pode virar APP por eliminacao, senao
    a falta de evidencia vira permissao para digitar."""
    rng = numpy.random.RandomState(11)
    ruido = rng.randint(0, 256, size=(540, 960, 3)).astype(numpy.uint8)
    estado, st = ts.classify_frame(ruido)
    assert st["parece_app"] is False
    assert estado != ts.APP
    assert ts.pode_digitar({"estado": estado, "concorda": True}) is False


def test_cor_chapada_e_a_fracao_da_cor_exata_mais_comum():
    """Nao adianta o teste concordar consigo mesmo: aqui a conta e
    verificada contra um frame de resposta conhecida."""
    img = numpy.zeros((100, 100, 3), dtype=numpy.uint8)
    img[:30, :] = (7, 8, 9)          # 30% de uma cor exata
    img[30:, :, 0] = numpy.arange(70 * 100).reshape(70, 100) % 251
    assert abs(ts._cor_chapada(img, passo=1) - 0.30) < 0.01


def test_subamostrar_nao_muda_o_veredito():
    """O passo existe por custo (27ms -> 7ms no frame cheio). Se ele
    mudasse a conta, a economia estaria saindo da medida."""
    for frame in (frame_bloqueio("x"), frame_app()):
        cheio = ts._cor_chapada(frame, passo=1)
        amostrado = ts._cor_chapada(frame, passo=ts.COR_CHAPADA_PASSO)
        assert abs(cheio - amostrado) < 0.05
        assert ((cheio >= ts.APP_COR_CHAPADA_MIN)
                == (amostrado >= ts.APP_COR_CHAPADA_MIN))


def test_o_portao_do_codigo_e_o_limiar_publicado():
    # o estado exposto tem que ser o mesmo que decidiu
    for frame in (frame_bloqueio("x"), frame_app()):
        _, st = ts.classify_frame(frame)
        assert st["parece_app"] == (
            st["cor_chapada"] >= ts.APP_COR_CHAPADA_MIN)


def test_cara_de_foto_sem_marcador_erra_para_o_lado_que_nao_digita():
    """Na duvida entre papel de parede e tela bloqueada, o lado barato
    e o que recusa o teclado."""
    precisa_ocr()
    estado, st = ts.classify_frame(frame_bloqueio("xyzzy"))
    assert estado == ts.BLOQUEIO_FOTO
    assert st["marcador"] is None
    assert ts.pode_digitar({"estado": estado, "concorda": True}) is False


# ---------------------------------------------------------------------
# O avatar do login.
#
# Motivo, medido no rig em 2026-11-08: dois frames da MESMA tela de
# senha, com estatistica de pixel identica ate a quarta casa, deram
# marcador "Senha" num e None no outro -- o OCR falhou num placeholder
# apagado de cinco letras. Com isso a tela de senha virou BLOQUEIO_FOTO,
# estado em que pode_digitar() recusa, e o desbloqueio nao acontece.
# ---------------------------------------------------------------------

# Fracoes LIDAS dos frames reais que sobraram em queue/frames/keep/.
AVATAR_SENHA = (0.3363, 0.3363, 0.3387)
AVATAR_FOTO = 0.0001
AVATAR_APP_MAX = 0.0141          # 217_search_group.png


def frame_com_avatar(fracao_branca=True, w=1920, h=1080):
    """Tela de bloqueio escura com (ou sem) o glifo branco do login."""
    rng = numpy.random.RandomState(7)
    img = rng.randint(30, 70, (h, w, 3)).astype(numpy.uint8)
    if fracao_branca:
        x, y, bw, bh = ts.AVATAR_REGION
        cx, cy = x + bw // 2, y + bh // 2
        cv2.circle(img, (cx, cy), int(bh * 0.33), (255, 255, 255), -1)
    return img


def test_avatar_separa_senha_de_foto_e_de_app():
    for v in AVATAR_SENHA:
        assert v >= ts.AVATAR_BRANCO_MIN
    assert AVATAR_FOTO < ts.AVATAR_BRANCO_MIN
    assert AVATAR_APP_MAX < ts.AVATAR_BRANCO_MIN


def test_avatar_tem_folga_dos_dois_lados():
    """Encostar no limiar diz que a separacao sobreviveu por acaso."""
    assert min(AVATAR_SENHA) >= ts.AVATAR_BRANCO_MIN * 2
    assert AVATAR_APP_MAX * 2 <= ts.AVATAR_BRANCO_MIN


def test_tela_de_senha_e_reconhecida_mesmo_sem_o_ocr_ler_senha(monkeypatch):
    """A regressao exata: OCR nao acha nada, e ainda assim BLOQUEIO_SENHA.

    Sem isto a tela de senha cai em BLOQUEIO_FOTO, que pode_digitar()
    recusa -- e o desbloqueio fica impossivel justamente quando o OCR
    falha."""
    monkeypatch.setattr(ts, "_tem_texto", lambda *a, **k: None)
    estado, st = ts.classify_frame(frame_com_avatar())
    assert estado == ts.BLOQUEIO_SENHA
    assert st["marcador"] == "avatar"


def test_sem_avatar_e_sem_texto_continua_recusando_o_teclado(monkeypatch):
    """O ramo sem prova nenhuma nao pode ter ficado mais frouxo."""
    monkeypatch.setattr(ts, "_tem_texto", lambda *a, **k: None)
    estado, _ = ts.classify_frame(frame_com_avatar(fracao_branca=False))
    assert estado == ts.BLOQUEIO_FOTO
    assert ts.pode_digitar({"concorda": True, "estado": estado}) is False


def test_avatar_nao_passa_por_cima_do_portao_de_pixel(monkeypatch):
    """O avatar so e consultado depois de o portao dizer que NAO ha
    interface. Uma tela de aplicativo com algo branco no meio continua
    sendo APP, e nunca vira 'pode digitar a senha aqui'."""
    monkeypatch.setattr(ts, "_tem_texto", lambda *a, **k: None)
    app = numpy.full((1080, 1920, 3), 240, dtype=numpy.uint8)
    x, y, bw, bh = ts.AVATAR_REGION
    cv2.circle(app, (x + bw // 2, y + bh // 2), int(bh * 0.33), (255, 255, 255), -1)
    estado, st = ts.classify_frame(app)
    assert estado == ts.APP
    assert st["avatar"] >= ts.AVATAR_BRANCO_MIN   # o sinal existe...
    # ...e mesmo assim nao foi usado: no ramo APP o classificador
    # retorna antes, e "marcador" nem chega a ser gravado.
    assert st.get("marcador") is None


def test_frame_menor_que_a_regiao_nao_vira_prova():
    """Sem regiao nao ha prova, e ausencia de prova nao pode liberar o
    teclado (mesma regra do portao de cor chapada)."""
    assert ts._fracao_avatar(frame_preto(320, 200)) == 0.0


# Corpus reconstruido em 2026-11-08 e gravado direto em
# queue/frames/keep/, que a poda nao toca. O anterior (114 frames) foi
# apagado justamente por nao estar la -- APRENDIZADOS 43.
#
# Sete janelas reais do alvo, quatro escuras (media ~19) e tres claras
# (~170), para o limiar nao ficar calibrado num tema so.
CHAPADA_APP_CORPUS = (
    0.5505,   # terminal
    0.5559,   # bloco de notas
    0.5725,   # excel
    0.6909,   # vs code
    0.7263,   # chrome
    0.7629,   # explorer
    0.7629,   # whatsapp
)


def test_corpus_novo_de_aplicativos_fica_todo_acima_do_limiar():
    for v in CHAPADA_APP_CORPUS:
        assert v >= ts.APP_COR_CHAPADA_MIN
    assert min(CHAPADA_APP_CORPUS) >= ts.APP_COR_CHAPADA_MIN * 2, (
        "o pior aplicativo real encostou no limiar: remedir antes de confiar")


def test_janela_ainda_sendo_pintada_nao_e_aplicativo():
    """Medido em 2026-11-08: logo depois de trocar de janela pela barra
    de tarefas, 3 de 7 capturas pegaram a janela com a MOLDURA ja
    desenhada e o conteudo ainda preto -- cor chapada 0.94 a 0.96.

    Isso cai em PRETO, e pode_digitar() recusa. E o lado certo: uma
    janela que ainda nao pintou tambem ainda nao esta pronta para
    receber tecla. O teste existe para ninguem 'consertar' isso
    mandando preto chapado virar APP."""
    preto = numpy.zeros((1080, 1920, 3), dtype=numpy.uint8)
    estado, st = ts.classify_frame(preto)
    assert st["cor_chapada"] >= ts.APP_COR_CHAPADA_MIN   # chapado, sim
    assert estado == ts.PRETO                            # e mesmo assim nao e APP
    assert ts.pode_digitar({"concorda": True, "estado": estado}) is False
