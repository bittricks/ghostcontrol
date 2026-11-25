<!-- Versão PT. English: README.md -->

# VeriKVM

**Um KVM por software, agentless, que opera a sua máquina como um humano.**

Ele faz tarefas de verdade na sua segunda máquina: **lê a tela, entende em
que estado ela está, e então digita e clica** — num hardware que o alvo
enxerga como teclado e mouse físicos. Nada é instalado no alvo.

E, diferente de qualquer outro KVM por software, ele **confere a tela antes
de cada ação e se recusa a agir na janela errada** — então uma tarefa nunca
cai na tela de bloqueio nem no app errado.

> **Para as suas próprias máquinas.** Duas máquinas suas, dois cabos, e você.
> Veja [SECURITY.md](docs/SECURITY.md) para o escopo e o modelo de ameaça.

🌐 [English](README.md) · **Português** · [Español](docs/README.es.md) · [中文](docs/README.zh.md) · [Français](docs/README.fr.md) · [Русский](docs/README.ru.md)

MIT · sobre uma ponte USB-HID CH9329 + uma placa de captura HDMI

---

## O que dá para automatizar

O VeriKVM poupa as horas que você gastaria vigiando uma segunda máquina.
Você descreve tarefas pequenas em JSON (ou reaproveita os exemplos), e ele
executa o trabalho de desktop do dia a dia e do trabalho que as pessoas mais
automatizam — sempre agindo só quando a tela é a que a tarefa espera:

- **Responder chats e mensagens** — WhatsApp Web, Telegram, Slack, Teams:
  detecta a mensagem nova, digita a resposta e envia.
- **Manter a máquina ativa, sem desligar** — impede dormir, bloquear ou ficar
  ociosa durante tarefas longas, sem mexer nas opções de energia.
- **Responder e triar e-mails** — abre o cliente, lê o que está na tela,
  digita a resposta e arquiva.
- **Editar planilhas** — abre o Excel ou o Google Sheets, insere linhas,
  dispara um recálculo e salva.
- **Preencher formulários e fazer entrada de dados** — digitação repetitiva
  em apps web ou desktop que não têm API.
- **Operar apps que barram bots e macros** — como a entrada é USB-HID real,
  softwares que bloqueiam scripts mesmo assim aceitam.
- **Rodar lotes sem supervisão de madrugada** — enfileira uma lista; ele
  confere cada tela antes, então nada dispara na janela errada.
- **Controlar um segundo PC (ou sem monitor) remotamente** — sem agente,
  driver ou software de acesso remoto instalado naquela máquina.

Em resumo: **automação de desktop sem agente (RPA) para um segundo
computador**, com verificação de tela para que uma tarefa nunca digite no
lugar errado.

## Por que este

Todo outro KVM por software encaminha a tecla às cegas — não sabe qual janela
está em foco, uma tela que re-trava engole o que você digita, e ele reporta
"enviado OK" mesmo quando nada aconteceu. O VeriKVM fecha o ciclo do jeito
que uma pessoa ao teclado faz:

1. **Lê a tela.** Captura o HDMI e classifica o que está mesmo na tela — área
   de trabalho, o app certo, tela de bloqueio, um diálogo.
2. **Decide o estado.** Se a tela não é a que a tarefa espera, recusa o lote
   inteiro em vez de digitar no lugar errado.
3. **Age no hardware real.** Digita e clica pelo CH9329, e relê a tela para
   confirmar que a ação surtiu efeito.

É a única coisa que as turmas de KVM de hardware e de software pulam, porque
encaminham entrada e nunca precisam confiar numa captura.

## O que é — e o que não é

**É** uma ferramenta de automação e controle remoto em nível de SO, para uma
máquina cujo SO está rodando. Sem agente, sem driver, sem software de controle
remoto no alvo — parece um humano ao teclado.

**Não é** um KVM de hardware. **Sem controle de energia, sem BIOS/UEFI, sem
mídia virtual.** Se você precisa de controle pré-boot, use um IP-KVM baseado
em Raspberry Pi (PiKVM, TinyPilot). Veja os limites honestos em
[HARDWARE.md](docs/HARDWARE.md).

## Recursos

- **Verificação fail-closed** — classifica a tela antes de cada ação, recusa
  o estado errado, e confirma cada ação relendo a tela.
- **Entrada HID real** — uma ponte CH9329 que o alvo não distingue de um
  teclado e mouse físicos. Agentless.
- **Teclados internacionais** — layouts plugáveis (US, ABNT2 e mais). Um
  caractere que o layout ativo não produz é recusado, nunca emitido como
  glifo errado.
- **Medido, não chutado** — um [guia de hardware](docs/HARDWARE.md) com as
  peculiaridades que medimos, e um [diário de engenharia](docs/LEARNINGS.md) do
  que quebrou e por quê.

## Como conecta

```
[ ALVO ] --HDMI out--> [ dongle de captura ] --USB--> [ CONTROLADOR ]
[ ALVO ] <--USB HID--- [ CH9329 + CH340 ]   <--USB-- [ CONTROLADOR ]
```

Duas máquinas, dois cabos. O controlador escreve arquivos JSON de tarefa; o
daemon executa no alvo e relê a tela. A lista de peças (~US$15–25) está em
[HARDWARE.md](docs/HARDWARE.md).

## Começando

```bash
git clone https://github.com/bittricks/verikvm
cd verikvm
pip install -r requirements.txt

# sobe o daemon (auto-detecta a porta serial; --layout define o layout
# do teclado do alvo, padrão abnt2)
python src/agent_daemon.py --layout us
```

Instalação, ligação e calibração completas em [`docs/`](docs/).

## Status

O núcleo de verificação é coberto por uma suíte de testes (400+), incluindo
um teste de fronteira de arquitetura que mantém o motor livre de código
específico de aplicação.

## Segurança

Isto controla uma máquina sua com uma credencial sua. **Não abre porta de
rede por padrão** — fala com o hardware, não com a rede. Leia
[SECURITY.md](docs/SECURITY.md) antes de expor qualquer coisa, e para reportar uma
vulnerabilidade.

## Licença

MIT — veja [LICENSE](LICENSE).

## Apoie

O VeriKVM é um projeto voluntário. Se ele te poupou um fim de semana, você
pode contribuir on-chain. **Envie cada ativo somente na rede indicada — rede
errada significa fundos perdidos.**

**Bitcoin**
```
bc1qp8auny76nc73x5kepej2dsyl54x06nvxgrwjy6
```

**Ethereum e EVM** — ETH, USDC, USDT em Ethereum, Base, Arbitrum, Optimism, Polygon, BNB Chain
```
0x935D040a03cb94B3cD1736b1f0813A6A0Ab0BE72
```

**Solana** — SOL e tokens SPL
```
24LvX1XQ7xF6SGeRwx3NmbPMAaaqHF2FJp7rEM9GMjpS
```

**Tron** — TRX e TRC-20 (ex.: USDT-TRC20)
```
TRxSPc5tNmgHvr4t9bPtnG6U7iApKedX8n
```

**Monero** — XMR
```
86oP1vf2TucfxGQDkXyBJeJnf5yeC7uzperQsnFdmS3EYHP4zYt3DdeYyP12Qo69w6AEuGYfMTSeKZHDrC8fzECm2c8GRii
```

**O que as doações apoiam:** manutenção contínua, o hardware que usamos para
testar, e a documentação. **O que não esperar:** recursos ou prazos
garantidos — é um projeto voluntário, nenhum resultado é prometido.
