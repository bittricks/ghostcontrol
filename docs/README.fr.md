<!-- README du dépôt public. Version EN : README.md -->

# VeriKVM

**Un KVM logiciel, sans agent, qui pilote votre propre machine comme un humain.**

Il effectue de vraies tâches sur votre seconde machine : **il lit l'écran,
comprend dans quel état il se trouve, puis tape et clique** — sur un matériel
que la machine cible voit comme un clavier et une souris physiques réels. Rien
n'est installé sur la cible.

Et, contrairement à tout autre KVM logiciel, il **vérifie l'écran avant chaque
action et refuse d'agir dans la mauvaise fenêtre** — ainsi une tâche ne tombe
jamais sur l'écran de verrouillage ni dans la mauvaise application.

> **Pour vos propres machines.** Deux de vos machines, deux câbles, et vous.
> Voir [SECURITY.md](SECURITY.md) pour le périmètre et le modèle de menace.

🌐 [English](../README.md) · [Português](../README.pt-BR.md) · [Español](README.es.md) · [中文](README.zh.md) · **Français** · [Русский](README.ru.md)

MIT · basé sur un pont USB-HID CH9329 + une carte d'acquisition HDMI

---

## Ce que vous pouvez automatiser

VeriKVM vous épargne les heures passées à surveiller un second ordinateur.
Vous décrivez de petites tâches en JSON (ou réutilisez les exemples), et il
réalise le travail de bureau quotidien et professionnel que l'on automatise le
plus — en n'agissant que lorsque l'écran est bien celui qu'attend la tâche :

- **Répondre aux chats et aux messages** — WhatsApp Web, Telegram, Slack,
  Teams : repérer un nouveau message, taper la réponse, l'envoyer.
- **Garder une machine active, sans extinction** — l'empêcher de se mettre en
  veille, de se verrouiller ou de rester inactive pendant les tâches longues,
  sans changer les options d'alimentation.
- **Répondre et trier les e-mails** — ouvrir le client, lire ce qui est à
  l'écran, taper la réponse, classer.
- **Modifier des feuilles de calcul** — ouvrir Excel ou Google Sheets, saisir
  des lignes, déclencher un recalcul, enregistrer.
- **Remplir des formulaires et saisir des données** — frappe répétitive dans
  des applis web ou bureau sans API.
- **Piloter des applis qui bloquent les bots et les macros** — comme l'entrée
  est du vrai USB-HID, les logiciels qui refusent les scripts l'acceptent quand
  même.
- **Exécuter des lots sans surveillance la nuit** — mettez une liste en file ;
  il vérifie chaque écran d'abord, donc rien ne se déclenche dans la mauvaise
  fenêtre.
- **Piloter à distance un second PC (ou sans écran)** — sans agent, pilote ni
  logiciel de bureau à distance installé sur cette machine.

En bref : **automatisation de bureau sans agent (RPA) pour un second
ordinateur**, avec vérification de l'écran pour qu'une tâche ne tape jamais au
mauvais endroit.

## Pourquoi celui-ci

Tout autre KVM logiciel transmet vos frappes à l'aveugle — il ignore quelle
fenêtre a le focus, un écran qui se reverrouille avale ce que vous tapez, et il
signale « envoyé OK » même quand rien ne s'est produit. VeriKVM ferme la boucle
comme le fait une personne au clavier :

1. **Il lit l'écran.** Il capture le flux HDMI et classe ce qui est réellement
   à l'écran — bureau, la bonne appli, un écran de verrouillage, une boîte de
   dialogue.
2. **Il décide de l'état.** Si l'écran n'est pas celui qu'attend la tâche, il
   refuse le lot entier au lieu de taper au mauvais endroit.
3. **Il agit sur du matériel réel.** Il tape et clique via le CH9329, puis
   relit l'écran pour confirmer que l'action a bien eu lieu.

C'est la seule chose que les deux camps — KVM matériel et logiciel — sautent,
parce qu'ils transmettent l'entrée et n'ont jamais à se fier à une capture.

## Ce que c'est — et ce que ce n'est pas

**C'est** un outil d'automatisation et de contrôle à distance au niveau du SE,
pour une machine dont le SE est en cours d'exécution. Sans agent, sans pilote,
sans logiciel de bureau à distance sur la cible — il ressemble à un humain au
clavier.

**Ce n'est pas** un KVM matériel. **Pas de contrôle de l'alimentation, pas
d'accès BIOS/UEFI, pas de média virtuel.** Si vous avez besoin d'un contrôle
avant démarrage, utilisez un IP-KVM basé sur Raspberry Pi (PiKVM, TinyPilot).
Voir [HARDWARE.md](HARDWARE.md) pour les limites honnêtes.

## Fonctionnalités

- **Vérification fail-closed** — classe l'écran avant chaque action, refuse le
  mauvais état, et confirme chaque action en relisant l'écran.
- **Entrée HID réelle** — un pont CH9329 que la cible ne distingue pas d'un
  clavier et d'une souris physiques. Sans agent.
- **Claviers internationaux** — dispositions enfichables (US, ABNT2 et plus).
  Un caractère que la disposition active ne peut pas produire est refusé,
  jamais émis sous le mauvais glyphe.
- **Mesuré, pas deviné** — un [guide matériel](HARDWARE.md) avec les
  particularités que nous avons mesurées, et un [journal
  d'ingénierie](LEARNINGS.md) de ce qui a cassé et pourquoi.

## Comment ça se branche

```
[ CIBLE ] --HDMI out--> [ dongle d'acquisition ] --USB--> [ CONTRÔLEUR ]
[ CIBLE ] <--USB HID--- [ CH9329 + CH340 ]       <--USB-- [ CONTRÔLEUR ]
```

Deux machines, deux câbles. Le contrôleur écrit des fichiers de tâche JSON ; le
daemon les exécute sur la cible et relit l'écran. Voir
[HARDWARE.md](HARDWARE.md) pour la liste des pièces (~15–25 US$).

## Pour commencer

```bash
git clone https://github.com/bittricks/verikvm
cd verikvm
pip install -r requirements.txt

# démarre le daemon (détecte le port série automatiquement ; --layout
# définit la disposition clavier de la cible, abnt2 par défaut)
python src/agent_daemon.py --layout us
```

Installation, câblage et calibration complets dans [`docs/`](.).

## État

Le cœur de vérification est couvert par une suite de tests (400+), dont un test
de frontière d'architecture qui garde le moteur exempt de code spécifique à
l'application.

## Sécurité

Ceci contrôle une de vos machines avec un de vos identifiants. **Il n'ouvre
aucun port réseau par défaut** — il parle au matériel, pas au réseau. Lisez
[SECURITY.md](SECURITY.md) avant d'exposer quoi que ce soit, et pour signaler
une vulnérabilité.

## Licence

MIT — voir [LICENSE](../LICENSE).

## Soutenir

VeriKVM est un projet bénévole. S'il vous a épargné un week-end, vous pouvez
contribuer on-chain. **N'envoyez chaque actif que sur le réseau indiqué — un
mauvais réseau signifie des fonds perdus.**

**Bitcoin**
```
bc1qp8auny76nc73x5kepej2dsyl54x06nvxgrwjy6
```

**Ethereum et EVM** — ETH, USDC, USDT sur Ethereum, Base, Arbitrum, Optimism, Polygon, BNB Chain
```
0x935D040a03cb94B3cD1736b1f0813A6A0Ab0BE72
```

**Solana** — SOL et jetons SPL
```
24LvX1XQ7xF6SGeRwx3NmbPMAaaqHF2FJp7rEM9GMjpS
```

**Tron** — TRX et TRC-20 (p. ex. USDT-TRC20)
```
TRxSPc5tNmgHvr4t9bPtnG6U7iApKedX8n
```

**Monero** — XMR
```
86oP1vf2TucfxGQDkXyBJeJnf5yeC7uzperQsnFdmS3EYHP4zYt3DdeYyP12Qo69w6AEuGYfMTSeKZHDrC8fzECm2c8GRii
```

**À quoi servent les dons :** maintenance continue, le matériel sur lequel nous
testons, et la documentation. **Ce qu'il ne faut pas attendre :** des
fonctionnalités ou des délais garantis — c'est un projet bénévole, aucun
résultat n'est promis.
