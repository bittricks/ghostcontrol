"""Classifica em que estado a tela da maquina alvo esta.

Por que existe
==============
Em 2026-11-07 eu declarei a tela "ainda bloqueada" DUAS vezes a partir
de um unico `ocr_region` da tela inteira -- quando o Windows ja estava
destravado e o Excel em primeiro plano. O buffer da capturadora tinha
servido o frame "de antes", que e exatamente o que
`docs/CAPTURA_VIDEO_BUFFER.md` documenta. Gastei tres idas e voltas
investigando um problema que nao existia.

O doc existia. Nao impediu nada, porque a conferencia era montada na mao
a cada request. Entao a regra virou codigo:

    UMA AMOSTRA NAO CLASSIFICA.

`classify()` exige duas ou mais e so devolve um veredito se elas
concordarem; discordando, devolve INDETERMINADO -- que e a resposta
certa para "o sinal esta em transicao", e nao uma de suas pontas
escolhida a esmo.

Os cinco estados sao os que a operacao de verdade precisa distinguir, e
cada um pede uma acao diferente (ver docs/DESBLOQUEIO_TELA.md):

    SEM_SINAL        barras de cor: a capturadora nao recebe HDMI.
                     Mexer o mouse e esperar; nao e erro do daemon.
    PRETO            transicao: o sinal esta voltando. Esperar mais.
    BLOQUEIO_FOTO    tela de bloqueio (foto+relogio). Uma tecla/clique
                     leva ao campo de senha.
    BLOQUEIO_SENHA   campo de senha visivel. AQUI da para digitar -- e
                     so aqui, com `expect` em cima disso.
    APP              area de trabalho / aplicativo real.

A segunda regra, aprendida em 2026-11-07 quando este modulo errou no
rig pela primeira vez:

    APP PRECISA DE PROVA; OS OUTROS ESTADOS NAO.

`classify_frame` so devolve APP se achar na tela uma mancha grande de
UMA COR EXATA, que e o que um aplicativo pinta e uma foto nao (ver
APP_COR_CHAPADA_MIN). Sem essa prova o frame cai nos estados que
RECUSAM o teclado. A versao anterior perguntava o contrario -- "parece
foto?" -- e tudo que nao parecesse virava APP, de modo que a falta de
evidencia virava permissao para digitar. Numa tela de bloqueio isso
manda a senha errada para o campo de senha, e o orcamento e de tres
tentativas.
"""
SEM_SINAL = "SEM_SINAL"
PRETO = "PRETO"
BLOQUEIO_FOTO = "BLOQUEIO_FOTO"
BLOQUEIO_SENHA = "BLOQUEIO_SENHA"
APP = "APP"
INDETERMINADO = "INDETERMINADO"

#: Abaixo disto a tela e preta. Medido: um frame preto de verdade fica
#: em media < 20, enquanto a tela de bloqueio mais escura que vimos
#: ficou em ~46.
PRETO_MEDIA_MAX = 24
PRETO_DESVIO_MAX = 18

#: Barras SMPTE: cor muito saturada e constante na vertical. O desvio
#: DENTRO de cada coluna e quase zero (a barra e uniforme de cima a
#: baixo), e isso nenhuma tela de Windows faz.
BARRAS_SATURACAO_MIN = 110
BARRAS_DESVIO_VERTICAL_MAX = 14
BARRAS_FAIXAS_MIN = 5

#: O que separa APLICATIVO de FOTO: a maior mancha de UMA COR EXATA.
#:
#: Um aplicativo pinta um fundo de cor exata -- o branco da planilha, o
#: cinza #1f1f1f do VS Code, o quase-preto do WhatsApp -- e essa unica
#: cor cobre quase metade da tela. Uma foto nao repete cor exata nem no
#: ceu mais liso: sobra ruido de sensor e de compressao. Medido em 29
#: frames reais rotulados a olho (2026-11-07):
#:
#:   bloqueio (10 frames)     maior cor exata  0.0042 .. 0.1446
#:   aplicativo (19 frames)   maior cor exata  0.4195 .. 0.6302
#:
#: Quase 3x de folga, e os dois piores casos sao justamente os que
#: derrubaram a versao anterior: bloqueio escuro 0.1446, Excel claro
#: 0.4195. O limiar fica no meio geometrico, arredondado.
#:
#: A VERSAO ANTERIOR usava saturacao e detalhe vertical, e os dois
#: estavam REFUTADOS pelos frames que eu ja tinha em disco:
#:
#:   VS Code escuro   saturacao 180, detalhe 35  -> chamado de FOTO
#:   bloqueio escuro  saturacao  26, detalhe 46  -> chamado de APP
#:
#: Errado nos dois sentidos, e o segundo e o caro: `pode_digitar`
#: liberaria o teclado na tela de bloqueio. Os limiares tinham sido
#: ajustados em 9 frames escolhidos por mim, todos de bloqueio colorido
#: e Excel claro -- validar na amostra que eu mesmo montei nao e
#: validar. Ver docs/APRENDIZADOS.md item 36.
APP_COR_CHAPADA_MIN = 0.25

#: De quantos em quantos pixels amostrar para medir a cor chapada.
#: Medido: passo 2 da a mesma separacao (folga 0.291 contra 0.275) por
#: 7ms em vez de 27ms no frame cheio.
COR_CHAPADA_PASSO = 2

#: Onde fica o bloco de login (nome do usuario + campo de senha) num
#: alvo 1920x1080. Medido: nome em y~536, "Senha" em y~599.
#:
#: Buscar o marcador na TELA INTEIRA nao funciona, e isso foi medido do
#: jeito constrangedor: "Senha" aparece em algum canto da tela do Excel,
#: e o classificador chamou a planilha de tela de login. Marcador curto
#: em area grande acha qualquer coisa.
LOGIN_REGION = [480, 420, 980, 400]

#: Texto que identifica o campo de senha, procurado SO em LOGIN_REGION.
#: Sao ASCII de proposito: o Tesseract desta maquina so tem o pacote
#: `eng`.
MARCADORES_SENHA = ("Senha", "Password")

#: Texto do bloqueio sem campo de senha (Spotlight).
MARCADORES_FOTO = ("Bloqueado", "Ver previsao")

#: O avatar do login: disco com o glifo BRANCO de usuario, logo acima do
#: nome. Medido num alvo 1920x1080.
#:
#: Existe porque em 2026-11-08 o rig mostrou o `marcador` de texto
#: falhando: dois frames da MESMA tela de senha, com estatistica de
#: pixel identica ate a quarta casa, deram "Senha" num e None no outro.
#: A palavra e um placeholder apagado de cinco letras dentro do campo --
#: pouco pixel e pouco contraste para o OCR depender dele sozinho.
#:
#: O glifo e o oposto disso: mancha branca grande e saturacao ~0.
#: Medido nos frames que restam em keep/ --
#:   tela de senha ...... 0.3363 / 0.3363 / 0.3387  (inclusive a de
#:                        fundo CLARO, entao nao e so contraste)
#:   bloqueio por foto .. 0.0001
#:   aplicativo ......... 0.0000 a 0.0141
#: Fator de 24x entre o pior de um lado e o melhor do outro.
AVATAR_REGION = [900, 345, 120, 125]
AVATAR_BRANCO_MIN = 0.15


def _cor_chapada(frame, passo=COR_CHAPADA_PASSO):
    """Fracao da tela coberta pela COR EXATA mais comum.

    E a prova positiva de que existe interface na tela: aplicativo tem
    fundo de cor exata, foto nao tem. Ver APP_COR_CHAPADA_MIN.
    """
    import numpy

    amostra = frame[::passo, ::passo]
    chave = (amostra[:, :, 0].astype(numpy.int32) << 16
             | amostra[:, :, 1].astype(numpy.int32) << 8
             | amostra[:, :, 2].astype(numpy.int32))
    _, contagem = numpy.unique(chave, return_counts=True)
    return float(contagem.max()) / chave.size


def _fracao_avatar(frame, region=None):
    """Fracao da regiao do avatar coberta por branco quase puro.

    Branco == claro E quase sem saturacao: o glifo do login e branco
    chapado, enquanto uma foto clara (ceu, parede) quase sempre carrega
    alguma cor. Ver AVATAR_REGION para os numeros medidos.

    Devolve 0.0 se a regiao nao couber no frame (alvo menor que
    1920x1080): sem regiao nao ha prova, e aqui a ausencia de prova tem
    que ser o lado que NAO libera o teclado.
    """
    import cv2
    import numpy

    recorte = _recorta(frame, region or AVATAR_REGION)
    if recorte is None:
        return 0.0
    x, y, w, h = recorte
    r = frame[y:y + h, x:x + w]
    cinza = cv2.cvtColor(r, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(r, cv2.COLOR_BGR2HSV)
    branco = numpy.logical_and(cinza > 225, hsv[:, :, 1] < 40)
    return float(branco.sum()) / cinza.size


def _estatisticas(frame):
    import cv2
    import numpy

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # desvio vertical medio: numa barra de cor ele e ~0
    desvio_vertical = float(numpy.mean(gray.std(axis=0)))
    # quantas faixas de matiz distintas ao longo de x
    matizes = hsv[:, :, 0].mean(axis=0)
    faixas = 1
    for i in range(1, len(matizes)):
        if abs(float(matizes[i]) - float(matizes[i - 1])) > 8:
            faixas += 1
    return {
        "media": float(gray.mean()),
        "desvio": float(gray.std()),
        "saturacao": float(hsv[:, :, 1].mean()),
        "desvio_vertical": desvio_vertical,
        "faixas": faixas,
        "cor_chapada": _cor_chapada(frame),
        "avatar": _fracao_avatar(frame),
    }


def _tem_texto(frame, marcadores, region=None, lang="eng"):
    """Qual marcador aparece na regiao, tentando varias escalas (ou None)."""
    import screen_utils

    for alvo in marcadores:
        achado = screen_utils.find_text_in_frame(
            frame, alvo, region=region, lang=lang)
        if achado.get("found"):
            return alvo
    return None


def _recorta(frame, region):
    """A regiao, ou o frame inteiro se ela nao couber (alvo menor)."""
    x, y, w, h = region
    if frame.shape[0] < y + h or frame.shape[1] < x + w:
        return None
    return [x, y, w, h]


def classify_frame(frame, lang="eng"):
    """Classifica UM frame. Devolve (estado, detalhe).

    Nao use direto para decidir: um frame pode ser o do buffer antigo.
    Use classify().
    """
    st = _estatisticas(frame)

    if st["media"] <= PRETO_MEDIA_MAX and st["desvio"] <= PRETO_DESVIO_MAX:
        return PRETO, st

    if (st["saturacao"] >= BARRAS_SATURACAO_MIN
            and st["desvio_vertical"] <= BARRAS_DESVIO_VERTICAL_MAX
            and st["faixas"] >= BARRAS_FAIXAS_MIN):
        return SEM_SINAL, st

    # O OCR so entra DEPOIS do portao de pixel. Ele e caro, e -- mais
    # importante -- um marcador curto procurado na tela toda acha
    # qualquer coisa: "Senha" aparece num canto da tela do Excel.
    #
    # A pergunta do portao e "ha PROVA de interface?", e nao "parece
    # foto?". A diferenca importa porque o ramo sem prova e o que decide
    # o estado quando nao se sabe, e ele precisa ser o ramo que RECUSA o
    # teclado. Na versao anterior a pergunta era a outra, e o que faltava
    # de prova virava APP -- ou seja, virava permissao.
    parece_app = st["cor_chapada"] >= APP_COR_CHAPADA_MIN
    st["parece_app"] = parece_app
    if parece_app:
        return APP, st

    # Ordem importa: o campo de senha e o estado mais especifico, e a
    # tela de bloqueio com foto tambem mostra clima e relogio.
    achado = _tem_texto(frame, MARCADORES_SENHA,
                        region=_recorta(frame, LOGIN_REGION), lang=lang)
    if achado:
        st["marcador"] = achado
        return BLOQUEIO_SENHA, st

    # O avatar do login, quando o OCR nao leu o placeholder "Senha".
    # E sinal ADICIONAL, nunca substituto: so pode ampliar o que ja era
    # reconhecido, nunca tirar.
    #
    # Ampliar BLOQUEIO_SENHA nao e de graca -- e o estado em que
    # pode_digitar() libera a SENHA. O que segura o risco e o lugar
    # desta checagem: ela so roda depois do portao de pixel ter dito que
    # NAO ha interface na tela, entao uma janela de aplicativo nunca
    # chega aqui. Medido: aplicativo vai no maximo a 0.0141, contra
    # 0.3363 das telas de senha.
    if st["avatar"] >= AVATAR_BRANCO_MIN:
        st["marcador"] = "avatar"
        return BLOQUEIO_SENHA, st

    achado = _tem_texto(frame, MARCADORES_FOTO, lang=lang)
    st["marcador"] = achado
    # Sem prova de interface e sem marcador. Fica em BLOQUEIO_FOTO de
    # proposito, porque pode_digitar() recusa esse estado -- na duvida
    # entre "area de trabalho com papel de parede" e "tela bloqueada",
    # errar para o lado que NAO digita e o lado barato: perde-se um
    # lote, contra digitar a esmo numa tela de senha.
    #
    # Medido no rig em 2026-11-07: a tela de bloqueio ficou um bom tempo
    # mostrando SO a foto, sem relogio e sem data, e so depois de uma
    # tecla apareceu o relogio. Quer dizer que o caminho "cara de foto,
    # nenhum marcador" nao e exotico -- e o estado normal da tela de
    # bloqueio ociosa.
    return BLOQUEIO_FOTO, st


def classify(frames, lang="eng"):
    """Classifica a partir de DUAS OU MAIS amostras.

    Devolve {"estado", "concorda", "por_frame", "detalhe"}.

    Levanta ValueError com uma amostra so. Isso e de proposito e e o
    ponto deste modulo: o buffer da capturadora serve frame velho, e
    uma leitura unica ja me fez afirmar duas vezes que a tela estava
    bloqueada quando nao estava.
    """
    frames = list(frames)
    if len(frames) < 2:
        raise ValueError(
            "classify() exige 2+ amostras: uma leitura so nao distingue o "
            "estado atual de um frame velho servido pelo buffer da "
            "capturadora (ver docs/CAPTURA_VIDEO_BUFFER.md). Capture de "
            "novo com um intervalo entre as capturas.")

    vereditos = [classify_frame(f, lang=lang) for f in frames]
    estados = [e for e, _ in vereditos]
    concorda = len(set(estados)) == 1
    return {
        "estado": estados[0] if concorda else INDETERMINADO,
        "concorda": concorda,
        "por_frame": estados,
        "detalhe": vereditos[-1][1],
    }


def pode_digitar(resultado):
    """So dois estados aceitam teclado, e por motivos diferentes.

    APP para trabalhar, BLOQUEIO_SENHA para digitar a senha. Nos outros
    o teclado vai para o nada (ou pior, para a janela errada quando o
    sinal voltar no meio do lote).
    """
    return resultado.get("concorda") and resultado["estado"] in (APP, BLOQUEIO_SENHA)


def amostrar(capture_fn, amostras=2, intervalo=1.5, lang="eng"):
    """Captura `amostras` frames espacados e classifica.

    `capture_fn` devolve um frame (ex.: ctx.capture_array).
    """
    import time

    frames = []
    for i in range(max(2, int(amostras))):
        if i:
            time.sleep(intervalo)
        frames.append(capture_fn())
    return classify(frames, lang=lang)
