<!-- README del repositorio público. Versión EN: ../README.md -->

# GhostControl

**Un KVM por software y sin agente que opera tu propia máquina como lo haría una persona.**

Realiza tareas reales en tu segunda máquina: **lee la pantalla, reconoce en
qué estado se encuentra y entonces escribe y hace clic** — sobre un hardware
que la máquina de destino percibe como un teclado y un ratón físicos. En la
máquina de destino no se instala nada.

Y, a diferencia de cualquier otro KVM por software, **comprueba la pantalla
antes de cada acción y se niega a actuar en la ventana equivocada**: así una
tarea nunca termina en la pantalla de bloqueo ni en la aplicación que no es.

> **Para tus propias máquinas.** Dos máquinas tuyas, dos cables y tú. Consulta
> [SECURITY.md](../SECURITY.md) para conocer el alcance y el modelo de amenazas.

🌐 [English](../../README.md) · [Português](README.pt-BR.md) · **Español** · [中文](README.zh.md) · [Français](README.fr.md) · [Русский](README.ru.md)

MIT · basado en un puente USB-HID CH9329 + una capturadora HDMI

---

## Qué puedes automatizar

GhostControl te ahorra las horas que pasarías vigilando una segunda computadora.
Defines tareas pequeñas en JSON (o reutilizas los ejemplos) y él se encarga
del trabajo de escritorio —personal y laboral— que más se suele automatizar,
actuando únicamente cuando la pantalla es la que la tarea espera:

- **Responder chats y mensajes** — WhatsApp Web, Telegram, Slack, Teams:
  detecta un mensaje nuevo, escribe la respuesta y la envía.
- **Mantener una máquina activa, sin que se apague** — evita que se suspenda,
  se bloquee o quede inactiva durante tareas largas, sin tocar las opciones de
  energía.
- **Responder y ordenar el correo** — abre el cliente, lee lo que hay en
  pantalla, escribe la respuesta y archiva.
- **Editar hojas de cálculo** — abre Excel o Google Sheets, introduce filas,
  fuerza un recálculo y guarda.
- **Rellenar formularios y cargar datos** — escritura repetitiva en
  aplicaciones web o de escritorio que no tienen API.
- **Manejar apps que bloquean bots y macros** — como la entrada es USB-HID
  real, el software que rechaza los scripts aun así la acepta.
- **Ejecutar lotes de madrugada, sin supervisión** — pon una lista en cola; él
  comprueba cada pantalla antes de actuar, así nada se dispara en la ventana
  equivocada.
- **Manejar en remoto un segundo PC (o uno sin monitor)** — sin agente, sin
  controlador y sin software de acceso remoto en esa máquina.

En resumen: **automatización de escritorio sin agente (RPA) para una segunda
computadora**, con verificación de pantalla para que una tarea jamás escriba
donde no debe.

## Por qué este

Cualquier otro KVM por software reenvía tus pulsaciones a ciegas: no sabe qué
ventana tiene el foco, una pantalla que vuelve a bloquearse se traga lo que
escribes, y da por "enviado" aunque no haya ocurrido nada. GhostControl cierra el
ciclo igual que una persona frente al teclado:

1. **Lee la pantalla.** Captura la señal HDMI y clasifica lo que hay realmente
   en ella: escritorio, la aplicación correcta, una pantalla de bloqueo, un
   diálogo.
2. **Decide el estado.** Si la pantalla no es la que la tarea espera, descarta
   el lote entero en lugar de escribir donde no corresponde.
3. **Actúa sobre hardware real.** Escribe y hace clic a través del CH9329 y
   vuelve a leer la pantalla para confirmar que la acción surtió efecto.

Es justo lo que se saltan tanto los KVM de hardware como los de software:
reenvían la entrada y nunca tienen que fiarse de una captura.

## Qué es — y qué no es

**Es** una herramienta de automatización y control remoto a nivel de SO, para
una máquina cuyo sistema operativo ya está en marcha. Sin agente, sin
controlador, sin software de escritorio remoto en la máquina de destino:
parece una persona frente al teclado.

**No es** un KVM de hardware. **No hay control de encendido, ni acceso a
BIOS/UEFI, ni medios virtuales.** Si necesitas control antes del arranque, usa
un IP-KVM basado en Raspberry Pi (PiKVM, TinyPilot). En [HARDWARE.md](../HARDWARE.md)
están los límites, sin adornos.

## Características

- **Verificación fail-closed** — clasifica la pantalla antes de cada acción,
  rechaza el estado incorrecto y confirma cada acción volviendo a leerla.
- **Entrada HID real** — un puente CH9329 que la máquina de destino no
  distingue de un teclado y un ratón físicos. Sin agente.
- **Teclados internacionales** — distribuciones intercambiables (US, ABNT2 y
  más). Un carácter que la distribución activa no puede producir se rechaza;
  nunca se emite con el glifo equivocado.
- **Medido, no supuesto** — una [guía de hardware](../HARDWARE.md) con las
  particularidades que medimos, y un [diario de ingeniería](../LEARNINGS.md) de lo
  que falló y por qué.

## Cómo se conecta

```
[ DESTINO ] --HDMI out--> [ capturadora ]        --USB--> [ CONTROLADOR ]
[ DESTINO ] <--USB HID--- [ CH9329 + CH340 ]    <--USB-- [ CONTROLADOR ]
```

Dos máquinas, dos cables. El controlador escribe archivos de tarea en JSON; el
daemon los ejecuta en la máquina de destino y vuelve a leer la pantalla. La
lista de piezas (~US$15–25) está en [HARDWARE.md](../HARDWARE.md).

## Primeros pasos

```bash
git clone https://github.com/bittricks/ghostcontrol
cd ghostcontrol
pip install -r requirements.txt

# arranca el daemon (detecta el puerto serie solo; --layout define la
# distribución de teclado de la máquina de destino, abnt2 por defecto)
python src/agent_daemon.py --layout us
```

La instalación, el cableado y la calibración completos están en [`docs/`](..).

## Estado

El núcleo de verificación está cubierto por una batería de pruebas (más de
400), incluida una prueba de frontera de arquitectura que mantiene el motor
libre de código específico de la aplicación.

## Seguridad

Esto controla una máquina tuya con una credencial tuya. **No abre ningún
puerto de red por defecto**: habla con el hardware, no con la red. Lee
[SECURITY.md](../SECURITY.md) antes de exponer nada, y también para reportar una
vulnerabilidad.

## Licencia

MIT — consulta [LICENSE](../../LICENSE).

## Apoyar

GhostControl es un proyecto voluntario. Si te ahorró un fin de semana, puedes
aportar on-chain. **Envía cada activo solo por la red indicada: equivocar la
red significa perder los fondos.**

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

**Para qué sirven las donaciones:** para el mantenimiento continuo, el hardware
con el que probamos y la documentación. **Qué no esperar:** funciones ni plazos
garantizados — es un proyecto voluntario y no se promete ningún resultado.
