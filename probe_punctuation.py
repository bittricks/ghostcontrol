"""Sonda no hardware real quais glifos saem dos usages que `hid_keycodes`
so conseguiu INFERIR do layout ABNT2.

Por que existe
==============
O HID nao tem retorno: o CH9329 manda uma posicao de tecla e quem decide o
glifo e o driver de layout do Windows do ALVO. Um usage errado nao levanta
erro -- emite outro caractere. E se o outro caractere for tecla morta, ele
ainda engole o caractere seguinte, entao o estrago e silencioso e nao fica
no lugar onde foi causado. Ja aconteceu: `[` estava no usage 0x2F, que
neste layout e o acento agudo, de modo que `[A` virava `Á`.

Por isso `hid_keycodes.UNVERIFIED_CHARS` recusa esses caracteres por
padrao, e este probe e o unico caminho para liberar um deles.

Como usar
=========
1. Deixe o cursor num campo de TEXTO SIMPLES do alvo (caixa de mensagem do
   WhatsApp, Bloco de Notas). NAO use celula do Excel: ela interpreta `=`,
   `'` e `+` e mostra outra coisa que o digitado.
2. Confira antes o que esta em foco -- este script digita, e digitar na
   janela errada e o erro que o resto do projeto existe para evitar:

       python agent_daemon.py --port COM5 --once   # com um lote de expect

   ou simplesmente olhe um frame de `capture_frame.py`.
3. Rode:

       python probe_punctuation.py --port COM5 --out probe.png

4. Compare o PNG com o gabarito impresso no terminal. Para cada par que
   bater, remova o caractere de `UNVERIFIED_CHARS` em `hid_keycodes.py` e
   anote na tabela de `docs/TECLADO_ABNT2_HID.md`. Para cada par que NAO
   bater, corrija o usage e sonde de novo -- nunca "promova na duvida".

O probe digita cada candidato entre marcadores `>` e `<` porque um glifo
que nao sai (tecla morta pendurada, por exemplo) desaparece sem deixar
rastro: `>[<` virou `><` diz que nada chegou, enquanto `[` sozinho num
texto corrido e indistinguivel de um caractere perdido na serial.
"""
import argparse

import os
import sys
import time

import ch9329
import hid_keycodes

# Um probe por linha de texto. Mais que isso num campo estreito faz o
# texto rolar e o comeco sai do frame.
GRUPOS = (
    ("pontuacao deslocada", "[]{}\\|"),
    ("apostrofo e aspas", "'\""),
    ("glifo de tecla morta", "´`~^¨"),
)

# Entre eventos de um probe: generoso de proposito. A tecla morta precisa
# do intervalo para "armar", e aqui a velocidade nao importa -- o que
# importa e nao atribuir ao usage um erro que foi de temporizacao.
CHAR_DELAY = 0.15


def linhas_de_probe():
    """[(rotulo, texto_a_digitar, gabarito_esperado), ...]"""
    out = []
    for rotulo, chars in GRUPOS:
        texto = " ".join(">%s<" % c for c in chars)
        out.append((rotulo, texto, texto))
    return out


def digita(controller, linhas, char_delay=CHAR_DELAY):
    for i, (rotulo, texto, _) in enumerate(linhas):
        if i:
            controller.press_named_key("enter")
            time.sleep(char_delay)
        # allow_unverified: este e o unico lugar do projeto que pode.
        # O proposito do probe e justamente medir o que nao foi medido.
        controller.type_text(texto, char_delay=char_delay,
                             allow_unverified=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", required=True, help="porta serial do CH9329 (ex: COM5)")
    p.add_argument("--out", help="caminho do PNG com o resultado na tela")
    p.add_argument("--char-delay", type=float, default=CHAR_DELAY)
    p.add_argument("--dry-run", action="store_true",
                   help="so imprime o gabarito, nao digita nada")
    a = p.parse_args(argv)

    linhas = linhas_de_probe()

    print("Gabarito -- o alvo deve mostrar exatamente isto:")
    for rotulo, _, gabarito in linhas:
        print("  %-22s %s" % (rotulo, gabarito))
    print()
    print("Hoje recusados por falta de medicao: %s"
          % " ".join(sorted(hid_keycodes.UNVERIFIED_CHARS)))

    if a.dry_run:
        return 0

    with ch9329.CH9329Controller(a.port) as controller:
        controller.release_all_keys()
        digita(controller, linhas, char_delay=a.char_delay)

    if a.out:
        from capture_frame import capture_frame_to_file

        capture_frame_to_file(a.out)
        print("\nframe: %s" % os.path.abspath(a.out))
        print("Compare com o gabarito acima ANTES de promover qualquer "
              "entrada em hid_keycodes.UNVERIFIED_CHARS.")
    else:
        print("\nSem --out: capture a tela por outro caminho antes de "
              "concluir qualquer coisa. O probe nao prova nada sem a leitura.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
