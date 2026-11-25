<!-- README del repositorio público. Versión EN: README.md -->

# VeriKVM

**Un KVM por software, sin agente, que opera tu propia máquina como un humano.**

Realiza tareas reales en tu segunda máquina: **lee la pantalla, entiende en
qué estado está, y entonces escribe y hace clic** — en un hardware que el
equipo de destino ve como un teclado y un ratón físicos reales. No se instala
nada en el equipo de destino.

Y, a diferencia de cualquier otro KVM por software, **verifica la pantalla
antes de cada acción y se niega a actuar en la ventana equivocada** — así una
tarea nunca cae en la pantalla de bloqueo ni en la aplicación equivocada.

> **Para tus propias máquinas.** Dos máquinas tuyas, dos cables y tú. Consulta
> [SECURITY.md](SECURITY.md) para el alcance y el modelo de amenazas.

🌐 [English](README.md) · [Português](README.pt-BR.md) · **Español** · [中文](README.zh.md) · [Français](README.fr.md) · [Русский](README.ru.md)

MIT · sobre un puente USB-HID CH9329 + una tarjeta de captura HDMI

---

## Qué puedes automatizar

VeriKVM te ahorra las horas que pasarías vigilando una segunda computadora.
Describes tareas pequeñas en JSON (o reutilizas los ejemplos), y ejecuta el
trabajo de escritorio cotidiano y laboral que más se automatiza — actuando
siempre solo cuando la pantalla es la que la tarea espera:

- **Responder chats y mensajes** — WhatsApp Web, Telegram, Slack, Teams:
  detecta un mensaje nuevo, escribe la respuesta y la envía.
- **Mantener una máquina activa, sin apagarse** — evita que se duerma, se
  bloquee o quede inactiva durante tareas largas, sin cambiar las opciones de
  energía.
- **Responder y clasificar correos** — abre el cliente, lee lo que hay en
  pantalla, escribe la respuesta y archiva.
- **Editar hojas de cálculo** — abre Excel o Google Sheets, introduce filas,
  dispara un recálculo y guarda.
- **Rellenar formularios e introducir datos** — escritura repetitiva en
  aplicaciones web o de escritorio sin API.
- **Operar apps que bloquean bots y macros** — como la entrada es USB-HID
  real, el software que rechaza scripts aun así la acepta.
- **Ejecutar lotes sin supervisión de madrugada** — pon en cola una lista;
  verifica cada pantalla antes, así nada se dispara en la ventana equivocada.
- **Operar un segundo PC (o sin monitor) de forma remota** — sin agente,
  controlador ni software de acceso remoto instalado en esa máquina.

En resumen: **automatización de escritorio sin agente (RPA) para una segunda
computadora**, con verificación de pantalla para que una tarea nunca escriba
en el lugar equivocado.

## Por qué este

Cualquier otro KVM por software reenvía tus pulsaciones a ciegas — no sabe qué
ventana tiene el foco, una pantalla que vuelve a bloquearse se traga lo que
escribes, y reporta "enviado OK" aunque no haya pasado nada. VeriKVM cierra el
ciclo como lo hace una persona ante el teclado:

1. **Lee la pantalla.** Captura la señal HDMI y clasifica lo que realmente hay
   en pantalla — escritorio, la app correcta, una pantalla de bloqueo, un
   diálogo.
2. **Decide el estado.** Si la pantalla no es la que la tarea espera, rechaza
   todo el lote en vez de escribir en el lugar equivocado.
3. **Actúa en hardware real.** Escribe y hace clic a través del CH9329, y
   relee la pantalla para confirmar que la acción realmente surtió efecto.

Esto es lo único que tanto el bando de los KVM de hardware como el de software
se saltan, porque reenvían la entrada y nunca tienen que confiar en una
captura.

## Qué es — y qué no es

**Es** una herramienta de automatización y control remoto a nivel de SO, para
una máquina cuyo SO está en ejecución. Sin agente, sin controlador, sin
software de escritorio remoto en el equipo de destino — parece un humano ante
el teclado.

**No es** un KVM de hardware. **No hay control de energía, ni acceso a
BIOS/UEFI, ni medios virtuales.** Si necesitas control antes del arranque, usa
un IP-KVM basado en Raspberry Pi (PiKVM, TinyPilot). Consulta
[HARDWARE.md](HARDWARE.md) para los límites honestos.

## Características

- **Verificación fail-closed** — clasifica la pantalla antes de cada acción,
  rechaza el estado equivocado y confirma cada acción releyendo la pantalla.
- **Entrada HID real** — un puente CH9329 que el equipo de destino no distingue
  de un teclado y un ratón físicos. Sin agente.
- **Teclados internacionales** — distribuciones conectables (US, ABNT2 y más).
  Un carácter que la distribución activa no puede producir se rechaza, nunca se
  emite como el glifo equivocado.
- **Medido, no supuesto** — una [guía de hardware](HARDWARE.md) con las
  peculiaridades que medimos, y un [diario de ingeniería](LEARNINGS.md) de lo
  que falló y por qué.

## Cómo se conecta

```
[ DESTINO ] --HDMI out--> [ dongle de captura ] --USB--> [ CONTROLADOR ]
[ DESTINO ] <--USB HID--- [ CH9329 + CH340 ]    <--USB-- [ CONTROLADOR ]
```

Dos máquinas, dos cables. El controlador escribe archivos de tarea JSON; el
daemon los ejecuta en el equipo de destino y relee la pantalla. Consulta
[HARDWARE.md](HARDWARE.md) para la lista de piezas (~US$15–25).

## Primeros pasos

```bash
git clone https://github.com/bittricks/verikvm
cd verikvm
pip install -r requirements.txt

# inicia el daemon (detecta el puerto serie automáticamente; --layout
# define la distribución del teclado del destino, por defecto abnt2)
python src/agent_daemon.py --layout us
```

La instalación, el cableado y la calibración completos están en
[`docs/`](docs/).

## Estado

El núcleo de verificación está cubierto por una suite de pruebas (400+),
incluida una prueba de frontera de arquitectura que mantiene el motor libre de
código específico de la aplicación.

## Seguridad

Esto controla una máquina tuya con una credencial tuya. **No abre ningún
puerto de red por defecto** — habla con el hardware, no con la red. Lee
[SECURITY.md](SECURITY.md) antes de exponer nada, y para reportar una
vulnerabilidad.

## Licencia

MIT — consulta [LICENSE](LICENSE).

## Apoyar

VeriKVM es un proyecto voluntario. Si te ahorró un fin de semana, puedes
contribuir on-chain. **Envía cada activo solo en la red indicada — una red
equivocada significa fondos perdidos.**

**Bitcoin**
```
bc1qp8auny76nc73x5kepej2dsyl54x06nvxgrwjy6
```

**Ethereum y EVM** — ETH, USDC, USDT en Ethereum, Base, Arbitrum, Optimism, Polygon, BNB Chain
```
0x935D040a03cb94B3cD1736b1f0813A6A0Ab0BE72
```

**Solana** — SOL y tokens SPL
```
24LvX1XQ7xF6SGeRwx3NmbPMAaaqHF2FJp7rEM9GMjpS
```

**Tron** — TRX y TRC-20 (p. ej. USDT-TRC20)
```
TRxSPc5tNmgHvr4t9bPtnG6U7iApKedX8n
```

**Monero** — XMR
```
86oP1vf2TucfxGQDkXyBJeJnf5yeC7uzperQsnFdmS3EYHP4zYt3DdeYyP12Qo69w6AEuGYfMTSeKZHDrC8fzECm2c8GRii
```

**Qué apoyan las donaciones:** mantenimiento continuo, el hardware con el que
probamos y la documentación. **Qué no esperar:** funciones o plazos
garantizados — es un proyecto voluntario, no se promete ningún resultado.
