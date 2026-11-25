<!-- README du dépôt public. Version EN : ../README.md -->

# VeriKVM

**Un KVM logiciel et sans agent qui pilote votre propre machine comme le ferait une personne.**

Il accomplit de vraies tâches sur votre seconde machine : **il lit l'écran,
reconnaît l'état dans lequel il se trouve, puis tape et clique** — sur un
matériel que la machine cible prend pour un vrai clavier et une vraie souris.
Rien n'est installé sur la cible.

Et, contrairement à tout autre KVM logiciel, il **vérifie l'écran avant chaque
action et refuse d'agir dans la mauvaise fenêtre** : ainsi une tâche ne tombe
jamais sur l'écran de verrouillage ni dans la mauvaise application.

> **Pour vos propres machines.** Deux de vos machines, deux câbles, et vous.
> Voir [SECURITY.md](SECURITY.md) pour le périmètre et le modèle de menace.

🌐 [English](../README.md) · [Português](../README.pt-BR.md) · [Español](README.es.md) · [中文](README.zh.md) · **Français** · [Русский](README.ru.md)

MIT · basé sur un pont USB-HID CH9329 + une carte d'acquisition HDMI

---

## Ce que vous pouvez automatiser

VeriKVM vous épargne les heures passées à surveiller un second ordinateur.
Vous décrivez de petites tâches en JSON (ou réutilisez les exemples), et il
prend en charge le travail de bureau — personnel comme professionnel — que
l'on automatise le plus, en n'agissant que lorsque l'écran est bien celui
qu'attend la tâche :

- **Répondre aux chats et aux messages** — WhatsApp Web, Telegram, Slack,
  Teams : repérer un nouveau message, taper la réponse, l'envoyer.
- **Garder une machine active, sans extinction** — l'empêcher de se mettre en
  veille, de se verrouiller ou de rester inactive pendant les tâches longues,
  sans toucher aux options d'alimentation.
- **Répondre et trier les e-mails** — ouvrir le client, lire ce qui est à
  l'écran, taper la réponse, classer.
- **Modifier des feuilles de calcul** — ouvrir Excel ou Google Sheets, saisir
  des lignes, lancer un recalcul, enregistrer.
- **Remplir des formulaires et saisir des données** — frappe répétitive dans
  des applis web ou bureau dépourvues d'API.
- **Piloter des applis qui bloquent les bots et les macros** — l'entrée étant
  du vrai USB-HID, les logiciels qui refusent les scripts l'acceptent quand
  même.
- **Lancer des lots la nuit, sans surveillance** — mettez une liste en file ;
  il vérifie chaque écran avant d'agir, donc rien ne se déclenche dans la
  mauvaise fenêtre.
- **Piloter à distance un second PC (ou sans écran)** — sans agent, sans
  pilote et sans logiciel de bureau à distance sur cette machine.

En bref : **automatisation de bureau sans agent (RPA) pour un second
ordinateur**, avec vérification de l'écran pour qu'une tâche ne tape jamais au
mauvais endroit.

## Pourquoi celui-ci

Tout autre KVM logiciel transmet vos frappes à l'aveugle : il ignore quelle
fenêtre a le focus, un écran qui se reverrouille avale ce que vous tapez, et il
annonce « envoyé » même quand rien ne s'est produit. VeriKVM boucle la boucle
comme le ferait une personne au clavier :

1. **Il lit l'écran.** Il capture le flux HDMI et classe ce qui s'y trouve
   vraiment : bureau, la bonne appli, un écran de verrouillage, une boîte de
   dialogue.
2. **Il décide de l'état.** Si l'écran n'est pas celui qu'attend la tâche, il
   rejette le lot entier au lieu de taper au mauvais endroit.
3. **Il agit sur du matériel réel.** Il tape et clique via le CH9329, puis
   relit l'écran pour confirmer que l'action a bien eu lieu.

C'est précisément ce que laissent de côté les deux camps — KVM matériel et
logiciel — parce qu'ils transmettent l'entrée sans jamais avoir à se fier à une
capture.

## Ce que c'est — et ce que ce n'est pas

**C'est** un outil d'automatisation et de contrôle à distance au niveau du SE,
pour une machine dont le système est déjà démarré. Sans agent, sans pilote,
sans logiciel de bureau à distance sur la cible : il passe pour une personne au
clavier.

**Ce n'est pas** un KVM matériel. **Pas de contrôle de l'alimentation, pas
d'accès BIOS/UEFI, pas de média virtuel.** S'il vous faut un contrôle avant le
démarrage, utilisez un IP-KVM basé sur Raspberry Pi (PiKVM, TinyPilot). Les
limites, sans détour, sont dans [HARDWARE.md](HARDWARE.md).

## Fonctionnalités

- **Vérification fail-closed** — classe l'écran avant chaque action, refuse le
  mauvais état et confirme chaque action en relisant l'écran.
- **Entrée HID réelle** — un pont CH9329 que la cible ne distingue pas d'un
  clavier et d'une souris physiques. Sans agent.
- **Claviers internationaux** — dispositions interchangeables (US, ABNT2 et
  plus). Un caractère que la disposition active ne peut pas produire est
  refusé, jamais émis avec le mauvais glyphe.
- **Mesuré, pas deviné** — un [guide matériel](HARDWARE.md) avec les
  particularités que nous avons mesurées, et un [journal
  d'ingénierie](LEARNINGS.md) de ce qui a cassé et pourquoi.

## Comment ça se branche

```
[ CIBLE ] --HDMI out--> [ dongle d'acquisition ]  --USB--> [ CONTRÔLEUR ]
[ CIBLE ] <--USB HID--- [ CH9329 + CH340 ]       <--USB-- [ CONTRÔLEUR ]
```

Deux machines, deux câbles. Le contrôleur écrit des fichiers de tâche en JSON ;
le daemon les exécute sur la cible et relit l'écran. La liste des pièces
(~15–25 US$) est dans [HARDWARE.md](HARDWARE.md).

## Pour commencer

```bash
git clone https://github.com/bittricks/verikvm
cd verikvm
pip install -r requirements.txt

# démarre le daemon (détecte le port série tout seul ; --layout définit la
# disposition clavier de la cible, abnt2 par défaut)
python src/agent_daemon.py --layout us
```

Installation, câblage et calibration complets dans [`docs/`](.).

## État

Le cœur de vérification est couvert par une suite de tests (plus de 400), dont
un test de frontière d'architecture qui garde le moteur exempt de code
spécifique à l'application.

## Sécurité

Ceci contrôle une de vos machines avec un de vos identifiants. **Il n'ouvre
aucun port réseau par défaut** : il parle au matériel, pas au réseau. Lisez
[SECURITY.md](SECURITY.md) avant d'exposer quoi que ce soit, et pour signaler
une vulnérabilité.

## Licence

MIT — voir [LICENSE](../LICENSE).

## Soutenir

VeriKVM est un projet bénévole. S'il vous a épargné un week-end, vous pouvez
contribuer on-chain. **N'envoyez chaque actif que sur le réseau indiqué : se
tromper de réseau, c'est perdre les fonds.**

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

**À quoi servent les dons :** à la maintenance continue, au matériel sur lequel
nous testons et à la documentation. **Ce qu'il ne faut pas attendre :** des
fonctionnalités ou des délais garantis — c'est un projet bénévole, aucun
résultat n'est promis.
