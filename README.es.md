<p align="center"><img src="https://raw.githubusercontent.com/solucionesconscientes/powerclock/main/src/powerclock/gui/icons/powerclock.svg" width="96" alt=""></p>

# PowerClock

**Programador de apagado, encendido y tareas**

[English](README.md) · **Español**

> **Estado:** versión previa (se prepara la 0.1.0). Hoy funciona en Linux; Windows y macOS están
> previstos. Su pestaña Rápido se inspiró en [KShutdown](https://kshutdown.sourceforge.io/); es un
> programa distinto, escrito desde cero y sin relación con él.

**Programa el apagado, el encendido y tus tareas: a una hora exacta o cuando se cumplan las
condiciones que elijas.** PowerClock apaga, reinicia, suspende, hiberna, bloquea, cierra la sesión
y **enciende tu equipo** por sí solo, y ejecuta tus programas y scripts **a una hora, de forma
periódica o cuando se cumple una condición**: dejas de usar el equipo, termina un render o una
descarga, queda poca batería, se desenchufa el portátil…

Lo hace con **reglas persistentes** que PowerClock guarda en segundo plano (un pequeño servicio,
el *daemon*). Las reglas siguen funcionando con la ventana cerrada, después de reiniciar e incluso
con la sesión cerrada. Puedes manejarlo desde un **icono en la bandeja y una ventana**
(al estilo de KShutdown), desde la **línea de comandos** o desde cualquier programa a través de un
**API local**.

![La pestaña Rápido](https://raw.githubusercontent.com/solucionesconscientes/powerclock/main/docs/images/es/quick.png)

---

## Contenido

- [Qué puede hacer](#qué-puede-hacer)
- [Capturas](#capturas)
- [Requisitos](#requisitos)
- [Instalación](#instalación)
- [Empezar en cinco minutos](#empezar-en-cinco-minutos)
- [Cómo funciona: las ideas principales](#cómo-funciona-las-ideas-principales)
- [La interfaz gráfica](#la-interfaz-gráfica)
- [La línea de comandos](#la-línea-de-comandos)
- [Las reglas en detalle](#las-reglas-en-detalle)
- [Encender y despertar el equipo](#encender-y-despertar-el-equipo)
- [Condiciones y sensores](#condiciones-y-sensores)
- [Seguridad](#seguridad)
- [Uso en un servidor](#uso-en-un-servidor)
- [Archivos y ajustes](#archivos-y-ajustes)
- [El API local](#el-api-local)
- [Solución de problemas](#solución-de-problemas)
- [Desinstalar](#desinstalar)
- [Desarrollo](#desarrollo)
- [Hoja de ruta](#hoja-de-ruta)
- [Licencia](#licencia)

---

## Qué puede hacer

**Acciones de energía**

| Acción | Qué ocurre |
|---|---|
| Apagar | Apaga el equipo. Por defecto de forma *ordenada*: el escritorio pide antes a las aplicaciones abiertas que guarden (KDE y GNOME). |
| Reiniciar | Reinicia, también de forma ordenada por defecto. |
| Suspender | Suspensión en RAM (S3). Se reanuda en segundos. |
| Hibernar | Guarda la memoria en disco y apaga (necesita una swap tan grande como la RAM y `resume=` configurado). |
| Suspensión híbrida | Suspender + hibernar: se reanuda rápido y aguanta un corte de luz. |
| Bloquear la pantalla | Bloquea tu sesión. |
| Cerrar sesión | Cierra tu sesión (de forma ordenada por defecto). |
| Apagar la pantalla | Apaga el monitor (KDE, GNOME o X11). |
| **Encender / despertar** | Programa el reloj del hardware (RTC) para que el equipo **despierte de la suspensión o incluso se encienda estando apagado** a una hora. |

**Otras acciones** (pasos de una regla, que se ejecutan en orden): **abrir una aplicación
instalada** (elegida de la lista del menú, también Flatpak y Snap) con **recetas** ya preparadas
(una web en modo quiosco, una lista en bucle, un PDF como presentación…), colocando su ventana en
una pantalla o a pantalla completa y manteniéndola abierta si se cierra · **controlar un
reproductor** (reproducir, pausar, siguiente, poner una emisora) · **ajustar el volumen**, poco a
poco si quieres · **reproducir un sonido o decir un texto en voz alta** · **cambiar el escritorio**
(tema claro u oscuro, fondo, brillo, perfil de energía) · **conectar una VPN** o encender y apagar
el Wi-Fi · **mantener la pantalla encendida y silenciar los avisos** un rato · **hacer una captura
de pantalla** para el historial · **mandar un mensaje al móvil** (ntfy, Telegram) o a cualquier
webhook (Home Assistant…) · **preguntar con botones** y esperar la respuesta (repitiéndolo cada
pocos minutos, como un recordatorio de medicación) · ejecutar un programa o una orden del shell (con tiempo máximo y su salida guardada en el historial) · abrir un archivo o
una web · cerrar un programa (primero pidiéndoselo y luego forzándolo) · mostrar una
notificación · esperar un rato · esperar a que se cumpla una condición · programar el siguiente
encendido. Los nombres de archivo y los textos pueden llevar la fecha: `radio-{date}.mp3`.

**Cuándo** (el *trigger*):

- **A una hora**: una vez en una fecha y hora, tras un tiempo (una cuenta atrás) o de forma
  periódica con una expresión cron (cada noche a las 03:00, los laborables a las 07:30…), en tu
  zona horaria o en otra.
- **Cuando se cumple una condición**: no se usa el equipo desde hace un rato · termina un
  programa (un render, una compresión, una copia…) · el equipo queda en reposo (CPU baja un
  tiempo) · termina una descarga (red baja un tiempo) · la batería baja o sube de un nivel · se
  desenchufa o se enchufa el portátil · se abre la sesión del escritorio (al entrar) · arranca
  PowerClock o el equipo vuelve de la suspensión.
- **Manual**: desde la ventana, la bandeja, la línea de comandos o el API.

**Solo si / esperar mientras**:

- **Solo si…** (las *conditions*) decide si una regla se ejecuta en su momento ("solo si está
  enchufado", "solo los laborables", "solo entre las 22:00 y las 07:00", "solo en la Wi-Fi de
  casa"…).
- **Esperar mientras…** (las *guards*) la hace *esperar* y volver a mirar ("mientras se reproduce
  un vídeo", "mientras alguien está conectado por SSH", "mientras ffmpeg está en marcha"), hasta un
  límite.

**Además**: un **aviso** antes de cualquier acción de energía que puedes cancelar hasta el último
segundo (con *Cancelar* y *Posponer 10 minutos* en una notificación y en una ventana) · un **modo
prueba** (`--dry-run`) para probarlo todo sin apagar nada · un **historial** de cada ejecución con su resultado y su
motivo · `powerclock doctor`, que comprueba qué funciona en tu equipo y dice cómo arreglar lo que no ·
un **icono en la bandeja** · la interfaz en **español e inglés**.

## Capturas

| | |
|---|---|
| ![Pestaña Rápido](https://raw.githubusercontent.com/solucionesconscientes/powerclock/main/docs/images/es/quick.png) **Rápido**: una acción, cuándo y un botón que dice lo que hará. Debajo, lo programado. | ![Pestaña Reglas](https://raw.githubusercontent.com/solucionesconscientes/powerclock/main/docs/images/es/rules.png) **Reglas**: todas las reglas y lo próximo. |
| ![Editor: condiciones](https://raw.githubusercontent.com/solucionesconscientes/powerclock/main/docs/images/es/editor-conditions.png) **Editor de reglas**: *Solo si…*, las condiciones. | ![Editor: pasos](https://raw.githubusercontent.com/solucionesconscientes/powerclock/main/docs/images/es/editor-steps.png) **Editor de reglas**: los pasos, en orden. |
| ![Historial](https://raw.githubusercontent.com/solucionesconscientes/powerclock/main/docs/images/es/history.png) **Historial**: resultado y motivo de cada ejecución. | ![Diagnóstico](https://raw.githubusercontent.com/solucionesconscientes/powerclock/main/docs/images/es/diagnostics.png) **Diagnóstico**: qué funciona aquí y cómo arreglar el resto. |
| ![Aviso antes de actuar](https://raw.githubusercontent.com/solucionesconscientes/powerclock/main/docs/images/es/countdown.png) El **aviso** antes de una acción de energía. | ![Menú de la bandeja](https://raw.githubusercontent.com/solucionesconscientes/powerclock/main/docs/images/es/tray-menu.png) El **menú de la bandeja**. |

## Requisitos

- **Linux con systemd** (logind). Probado en Kubuntu 26.04 con KDE Plasma 6 en Wayland; también
  es compatible con GNOME y X11, y con cualquier escritorio para lo básico (las acciones de energía
  pasan por logind).
- **Python 3.11 o posterior** (lo traen todas las distribuciones actuales) y **pipx** para
  instalarlo.
- Para la ventana y la bandeja: una sesión gráfica. En GNOME, el icono de la bandeja necesita la
  extensión *AppIndicator* (Ubuntu la trae activada); sin ella, PowerClock funciona desde su ventana.
- Para **encender el equipo** a una hora: una alarma de encendido en el RTC (casi cualquier PC) y,
  para encender desde *apagado*, una BIOS/UEFI que lo permita (en portátiles, normalmente solo
  enchufado a la corriente). `powerclock doctor` te lo dice.
- Un servidor sin escritorio (un VPS) puede usar solo PowerClock en segundo plano y la línea de comandos.

## Instalación

### La forma fácil (Linux)

1. **Descarga el instalador**: [`install-powerclock.sh`](https://github.com/solucionesconscientes/powerclock/releases/latest/download/install-powerclock.sh) (unos KB).
2. **Permite que se ejecute**: clic derecho → *Propiedades* → *Permisos* → *Permitir ejecutar el
   archivo como un programa* (o, en una terminal, `chmod +x install-powerclock.sh`).
3. **Haz doble clic.** Una terminal muestra la descarga: PowerClock con su propio Python y Qt,
   unos 130 MB de descarga y 400 MB en disco, así no depende de lo que tenga tu sistema. Después se abre la
   ventana de instalación de PowerClock.
4. **Pulsa Instalar** y escribe tu contraseña cuando te la pida (una vez, para que PowerClock
   pueda encender el equipo).

Ya está: PowerClock queda en la bandeja y en el menú de aplicaciones, y su servicio en marcha. Todo
vive en tu carpeta personal salvo un pequeño programa que solo puede programar la alarma de
encendido, así que actualizar nunca pide contraseña.
Para actualizar: *Diagnóstico → Buscar actualizaciones* (o `powerclock update`). Para desinstalar:
*Diagnóstico → Desinstalar PowerClock…* (o `powerclock uninstall`).

Los instaladores de Windows y macOS funcionarán igual cuando lleguen esas versiones.

### Con pipx (usuarios técnicos y servidores)

```bash
sudo apt install pipx && pipx ensurepath   # una vez (aquí Debian/Ubuntu); después abre otra terminal
pipx install "powerclock[gui]"             # en un servidor, sin la ventana: pipx install powerclock
powerclock setup                           # servicio, menú, inicio con la sesión y permiso de encendido (sudo una vez)
powerclock doctor                          # qué funciona en este equipo
```

`powerclock setup --no-helper`, `--no-menu`, `--no-login` y `--unattended` eligen qué preparar;
`powerclock service install` y `powerclock helper install` lo hacen paso a paso. Mira
[Uso en un servidor](#uso-en-un-servidor).

## Empezar en cinco minutos

Todo lo que sigue se puede probar antes en **modo prueba**: añade `--dry-run` a una acción rápida,
o instala el servicio con `powerclock service install --dry-run`. Las acciones de energía solo se
anotan, nunca se hacen.

**Desde la ventana** (`powerclock gui`), pestaña *Rápido*: elige una *Acción* (p. ej. *Apagar*), elige
*Cuándo* (p. ej. *Dentro de un tiempo* → `30m`) y pulsa el botón, que dice lo que hará
(*Programar apagado*). Aparece en *Programado* con su hora y el icono de la bandeja se pone azul.
Puedes cancelarla o posponerla desde ahí, desde el menú de la bandeja o desde la ventana de aviso
que aparece un minuto antes de actuar.

**Desde la línea de comandos**:

```bash
powerclock shutdown --in 30m                   # apagar dentro de 30 minutos
powerclock suspend --at 23:30 --wake 07:30     # suspender a las 23:30 y despertar a las 07:30
powerclock shutdown --when-exits ffmpeg        # apagar cuando termine el render
powerclock suspend --when-idle 20m             # suspender tras 20 minutos sin usarlo
powerclock shutdown --when-net-below 50 --for 5m   # apagar cuando termine la descarga
powerclock reboot --when-cpu-below 10 --for 5m # reiniciar cuando la CPU se calme
powerclock run --at 03:00 --wake -- /home/yo/bin/backup.sh   # encender a las 03:00 para una copia
powerclock wake --at "2026-10-01 07:30"        # solo encender el equipo a esa hora

powerclock status      # qué hay programado, en marcha y vigilando
powerclock cancel      # cancelar el aviso en curso o la próxima acción rápida
powerclock postpone 10m
powerclock history     # qué se ejecutó y por qué
```

**Con una regla** (para lo que se repite): pon esto en `nocturno.json` y añádelo con
`powerclock rules add nocturno.json` (o créala en la pestaña *Reglas*):

```json
{
  "id": "backup-nocturno",
  "name": "Copia nocturna y apagar",
  "trigger": {"type": "cron", "expr": "0 3 * * *"},
  "wake": true,
  "conditions": {"type": "power_source", "is": "ac"},
  "guards": {"any": [{"type": "media_playing"}, {"type": "ssh_session"}], "retry": "5m", "max_wait": "2h"},
  "actions": [
    {"type": "run", "cmd": ["/home/yo/bin/backup.sh"], "timeout": "2h"},
    {"type": "notify", "title": "PowerClock", "body": "Copia terminada"},
    {"type": "power", "action": "shutdown"}
  ]
}
```

Cada noche el equipo se enciende solo a las 02:58 y a las 03:00 ejecuta la copia si está
enchufado. Mientras se reproduce un vídeo o alguien está conectado por SSH, espera (hasta dos
horas). Después te avisa y se apaga tras un aviso de un minuto que puedes cancelar.

## Cómo funciona: las ideas principales

- **PowerClock en segundo plano** (`powerclock-daemon`, el *daemon*) lo hace todo: guarda las reglas, vigila la hora y los sensores,
  ejecuta las acciones y anota el historial. Funciona **con tu usuario** (nunca como root), como
  servicio de usuario de systemd instalado con `powerclock service install`. La ventana, la bandeja y la
  línea de comandos son solo clientes: cerrarlos no cambia nada.
- **Una regla** es: **cuándo** (el *trigger*) + **solo si…** opcional (las *conditions*) +
  **esperar mientras…** opcional (las *guards*) + **qué hará** (los *pasos*, en orden) + opciones
  (aviso, solo una vez, encender el equipo…).
- **Una acción rápida** es una regla que te crean la pestaña Rápido, la bandeja o órdenes como
  `powerclock shutdown --in 30m`. Se ejecuta una vez y luego desaparece (su ejecución queda en el
  historial).
- **El aviso**: antes de cualquier acción de energía PowerClock te avisa con una cuenta atrás
  que puedes cancelar hasta el último segundo (60 segundos por defecto, ajustable por regla; `0s`
  para quitarlo). Durante ella
  aparecen una notificación y una ventana con **Cancelar** y **Posponer 10 minutos**, y también
  funcionan `powerclock cancel` y `powerclock postpone`.
- **El historial** guarda cada ejecución: cuándo, su origen (*Horario*, *Condición* o *Manual*),
  cómo terminó (*hecha*, *falló*, *cancelada*, *omitida*) y por qué, con el resultado de
  cada paso y las últimas líneas de la salida de cada orden.
- **Momentos perdidos**: si una hora programada pasa con el equipo apagado o suspendido, la regla
  se *omite* por defecto; con `"on_missed": "run_once"` se ejecuta una vez en cuanto se pueda.
- **Zonas horarias**: las horas siguen la zona horaria de tu equipo; una regla puede fijar la suya
  (`"timezone": "Europe/Madrid"`). Los cambios de hora de verano e invierno están contemplados (una
  tarea de las 02:30 pasa a las 03:30 el día del cambio de primavera y se ejecuta una sola vez el
  de otoño).

## La interfaz gráfica

Ábrela con `powerclock gui` o desde el menú de aplicaciones. Solo se ejecuta **una** copia: abrirla otra
vez muestra la ventana que ya está en marcha. Cerrar la ventana deja el icono en la bandeja;
*Ocultar el icono (PowerClock sigue funcionando)*, en su menú, cierra la interfaz (tus reglas
siguen funcionando en segundo plano).

**Colores y estados.** Los colores propios solo marcan estados; el resto sigue el tema de tu
escritorio (claro u oscuro) y su fuente. Cada estado lleva además símbolo y texto: ◷ **Programado**
(azul crepúsculo), ☀ **Encenderá** (ámbar), ◉ **Vigilando** una condición (lavanda), ◴ **Cuenta
atrás** (brasa), ✔ **Hecho** (verde), ✘ **Falló** (grana) y ⊘ **Omitido o cancelado** (pizarra).

**Franja «Próximo».** Arriba de la ventana: qué hará PowerClock después y cuándo («Apagar · hoy
23:30 · dentro de 5 h 12 min · se volverá a encender mañana 07:30»), en el color de su estado, con
**Posponer 10 min** y **Cancelar**; si PowerClock no está funcionando, lo dice y ofrece
**Iniciar PowerClock**.

**Icono de la bandeja.** Con los mismos colores: gris (nada programado), azul con un reloj (algo
programado), lavanda con un ojo (vigilando una condición), ámbar con un sol (va a encender el
equipo), brasa (hay un aviso en curso) y gris tachado (PowerClock no está funcionando en segundo
plano). Pasa el ratón por encima para ver lo próximo. Su menú tiene: lo próximo, **Cancelar**,
**Posponer 10 minutos**, **Ahora ▸** (apagar, reiniciar, suspender, hibernar, bloquear, cerrar
sesión, apagar la pantalla; las primeras con su cuenta atrás, y bloquear y apagar la pantalla al
momento), **Programar…**, **Abrir PowerClock** y **Ocultar el icono**. Un clic izquierdo abre la
ventana.

**Pestaña Rápido** (como KShutdown): **Qué hacer** son botones con icono (apagar, reiniciar,
suspender, hibernar, híbrida, bloquear, cerrar sesión, pantalla, un programa o una aplicación);
**Cuándo** se elige entre *Ahora*, *A las*, *Dentro de* y *Cuando…*, que abre las condiciones: tras
un tiempo sin usar el equipo, cuando termine un programa — elígelo entre los que están en marcha o
escribe su nombre o su PID —, cuando el equipo quede en reposo (CPU por debajo de…) o cuando termine
la descarga (red por debajo de…), con cuánto tiempo debe durar. Después, **Avisar antes**, si
**forzar** (sin esperar a que las aplicaciones guarden) y **Volver a encenderlo a las** una hora.
El único botón destacado dice lo que hará (*Apagar ahora*, *Programar apagado*…). A la derecha,
**Programado** muestra en tarjetas las acciones rápidas que aún no han actuado, con su estado,
**Cancelar** y, si tiene hora, **Posponer 10 min**. En las que esperan una condición se ve lo que mide el
sensor en ese momento ("ffmpeg está en marcha", "inactivo desde hace 5m 12s", "CPU 35 % · midiendo:
2m de 5m").

**Pestaña Reglas.** Todas las reglas, con una casilla para activarlas o desactivarlas, cuándo
actúan y lo próximo con su estado (el id sale al pasar el ratón por el nombre). **Nueva…**, **Editar…** (o doble clic), **Ejecutar ahora**,
**Borrar**, **Importar…** y **Exportar…** (archivos JSON).

**Editor de reglas.** Pestañas *Cuándo* (nombre, activada y cuándo actúa), *Solo si…* (las
condiciones que deben cumplirse todas), *Esperar mientras…* (los motivos para esperar, con cada
cuánto volver a mirar y cuándo desistir), *Qué hará* (los pasos en orden, con ↑ ↓ para
reordenarlos), *Opciones* y *JSON*. La
pestaña JSON muestra la misma regla como texto y se sincroniza con los formularios al cambiar de
pestaña, así que puedes editar en cualquiera de las dos. Las condiciones más complejas que una
lista (un *any*, grupos anidados) se conservan y se editan como JSON dentro del formulario. Los
errores se explican antes de guardar (por ejemplo, que apagar debe ser el último paso).

**Pestaña Historial.** Arriba, el resumen de los últimos 30 días (horas encendido y apagado y lo
ahorrado). Debajo, todas las ejecuciones con cuándo terminaron, la regla, el resultado (✔ ✘ ⊘), su
origen y el motivo; elige una para ver sus pasos y su salida.

**Pestaña Diagnóstico.** Si PowerClock está funcionando en segundo plano (y un botón para
iniciarlo), todo lo que comprueba `powerclock doctor`, con nombres claros y cómo arreglar lo que no
funciona, la próxima alarma de encendido, **Permitir encender el equipo…** (muestra las órdenes
exactas y las ejecuta pidiendo tu contraseña en una ventana del escritorio), **Probar un despertar dentro de 2 minutos…** y dos
casillas: *Mostrar PowerClock en el menú de aplicaciones* e *Iniciar el icono de la bandeja al iniciar la
sesión*, y **Electricidad**: la tarifa (solo con discriminación horaria), el consumo del equipo y
el precio del kWh para calcular el ahorro.

**Ventana de aviso.** Aparece por encima de las demás cuando una acción de energía está a punto de
ocurrir: un anillo que se vacía con los segundos en grande, qué va a pasar («El equipo se apagará
en 42 s») y que puedes cancelarlo hasta el último segundo. **Cancelar** (o Esc) es el botón
destacado, porque es lo seguro; al lado, **Posponer 10 minutos**.

La interfaz sigue los colores, los iconos, la fuente y el modo claro u oscuro de tu escritorio. Instalada con
pipx, Qt dibuja los controles con su propio estilo *Fusion*; mira
[aspecto nativo en KDE](#aspecto-nativo-en-kde) para tener Breeze exacto.

## La línea de comandos

`powerclock --help` y `powerclock ORDEN --help` explican cada opción. Las horas admiten `23:30` (su próxima
aparición), `"2026-10-01 07:30"` (hora local) o ISO 8601 con zona horaria. Las duraciones se
escriben `30s`, `5m`, `2h`, `1d` o combinadas (`1h30m`).

**Acciones rápidas** — una orden por acción: `shutdown` (apagar), `reboot` (reiniciar), `suspend`
(suspender), `hibernate` (hibernar), `hybrid-sleep` (suspensión híbrida), `lock` (bloquear),
`logout` (cerrar sesión), `screen-off` (apagar la pantalla), `run -- PROGRAMA ARGUMENTOS…` y
`launch APP [--recipe ID] -- ARGUMENTOS…` (abrir una aplicación instalada).

| Opción | Significado |
|---|---|
| *(ninguna)* | Ahora (tras la cuenta atrás). |
| `--in 30m` | Dentro de un tiempo. |
| `--at 23:30` | A una hora. |
| `--when-idle 20m` | Cuando nadie haya usado el equipo durante ese tiempo. |
| `--when-exits NOMBRE\|PID` | Cuando termine ese programa. Si aún no está en marcha, PowerClock espera a que arranque: un nombre mal escrito nunca apaga el equipo. |
| `--when-cpu-below 10` | Cuando el uso medio de CPU se mantenga por debajo del 10 %… |
| `--when-net-below 50` | …o el tráfico de red por debajo de 50 kbit/s… |
| `--for 5m` | …durante ese tiempo (por defecto `5m`). |
| `--warning 2m` | Cuenta atrás antes de actuar (por defecto `60s`; `0s` para ninguna). |
| `--force` | No dejar que las aplicaciones pidan guardar. |
| `--wake 07:30` | (acciones de energía) Encender también el equipo a esa hora; p. ej. suspender ahora y despertar por la mañana. |
| `--wake` | (`run`, `launch`) Encender el equipo para ejecutarlo o abrirla (con `--in`/`--at`). |
| `--log-in` | Con `--wake` (o `powerclock wake`): entrar solo en la sesión cuando eso encienda el equipo, con la pantalla bloqueada. |
| `--recipe ID` | (`launch`) Tomar los argumentos de una receta; lo que pide (`<url>`, `<file>`…) va después de `--`, en orden. |
| `--dry-run` | Opción global (`powerclock --dry-run shutdown …`): solo anotar la acción de energía. |

**Otras órdenes**

| Orden | Qué hace |
|---|---|
| `powerclock wake --at HORA` | Encender el equipo a esa hora (desde suspensión, o desde apagado si la BIOS lo permite). |
| `powerclock apps [TEXTO]` | Las aplicaciones instaladas (`launch` las abre por su id), con sus recetas. |
| `powerclock recipes [APP]` | Argumentos ya preparados para aplicaciones habituales. |
| `powerclock wake-lan MAC [--broadcast IP] [--port 9]` | Enciende ya otro equipo de la red (Wake-on-LAN). |
| `powerclock stats [--days 30] [--watts W\|auto] [--price P\|auto]` | Horas encendido y apagado y lo que ha ahorrado PowerClock (estimado; ver abajo). |
| `powerclock tariff [es-2.0td\|none]` | La tarifa de la luz para la condición de tramo (solo con discriminación horaria). |
| `powerclock secrets set NOMBRE` · `list` · `rm NOMBRE` | Tokens que los pasos usan por su nombre (`telegram_token`), fuera de `rules.json`, en `secrets.json` (0600). |
| `powerclock status` | Qué está en marcha, qué viene, qué se vigila y la próxima alarma de encendido. |
| `powerclock cancel [RUN_ID]` | Cancela la cuenta atrás en curso; si no hay, la acción rápida en marcha, la próxima con hora o la última que espera una condición. |
| `powerclock postpone [10m] [--run RUN_ID]` | Pospone la cuenta atrás en curso o la próxima acción rápida con hora. |
| `powerclock history [-n 20] [--rule ID]` | Ejecuciones pasadas, su resultado y por qué. |
| `powerclock rules list` | Todas las reglas y cuándo se disparan (o qué vigilan). |
| `powerclock rules show ID` | Una regla en JSON. |
| `powerclock rules add ARCHIVO.json` | Añade las reglas de un archivo (una regla o una lista). |
| `powerclock rules edit ID` | Edita una regla con tu `$EDITOR`. |
| `powerclock rules enable\|disable ID` | Activa o desactiva una regla (sigue guardada). |
| `powerclock rules run ID` | Ejecuta una regla ahora (sus condiciones, sus motivos para esperar y el aviso siguen valiendo). |
| `powerclock rules rm ID` | Borra una regla. |
| `powerclock rules export [ARCHIVO]` / `powerclock rules import ARCHIVO [--replace]` | Copia de seguridad y restauración de reglas. |
| `powerclock doctor [--json]` | Qué funciona en este equipo y cómo arreglar lo que no. |
| `powerclock doctor --test-wake 120` | Programa un despertar dentro de N segundos (60–3600) y **suspende ahora**; después dice si despertó solo y qué lo despertó. Pregunta antes y da 10 segundos para apartar las manos. |
| `powerclock service install [--linger] [--dry-run]` · `uninstall` · `status` | PowerClock en segundo plano, como servicio de usuario de systemd. `--linger` lo mantiene funcionando sin iniciar sesión. |
| `powerclock helper install [--unattended] [--print]` · `uninstall` | El permiso para encender el equipo: un pequeño programa de root (el *helper*) que solo programa la alarma de encendido (muestra los comandos `sudo` y pregunta antes de ejecutarlos). |
| `powerclock gui [--tray]` | Abre la ventana (o solo el icono de la bandeja). |
| `powerclock setup [--no-menu] [--no-login] [--no-helper] [--unattended]` | Prepara PowerClock en esta sesión: servicio, entrada del menú, inicio con la sesión y permiso para encender el equipo (lo mismo que la ventana del instalador). |
| `powerclock update` | Instala la versión más reciente y reinicia el servicio. |
| `powerclock uninstall [--purge]` | Lo quita todo (con `--purge`, también reglas e historial). |

## Las reglas en detalle

Las reglas son JSON. El editor lo escribe por ti, pero es lo bastante corto para escribirlo a
mano, y PowerClock valida cada regla: una errata en el nombre de un campo se señala, nunca se
ignora en silencio. El JSON Schema completo lo sirve el API local en `/schema/rule`, y en
[`examples/`](examples/) hay reglas listas para usar.

```json
{
  "id": "backup-nocturno",             // letras, números, - y _ (opcional al crearla)
  "name": "Copia nocturna",
  "enabled": true,
  "trigger": { … },                     // cuándo
  "conditions": { … },                  // solo si (opcional)
  "guards": { "any": [ … ], "retry": "5m", "max_wait": "2h" },   // esperar mientras (opcional)
  "actions": [ { … }, { … } ],          // qué hacer, en orden
  "warning": "60s",                     // aviso antes de las acciones de energía
  "wake": false,                        // encender el equipo para ella (solo con `at`, `countdown` o `cron`)
  "on_missed": "skip",                  // o "run_once"
  "on_error": "stop",                   // o "continue"
  "one_shot": false,                    // desactivarla tras dispararse una vez
  "dry_run": false,                     // solo anotar sus acciones de energía
  "timezone": "Europe/Madrid"           // opcional; por defecto, la del equipo
}
```

(JSON no admite comentarios: aquí solo son explicaciones.)

### Cuándo (`trigger`)

| `type` | Campos | Actúa |
|---|---|---|
| `at` | `when` (ISO 8601 con zona horaria) | Una vez, en ese momento. |
| `countdown` | `duration` | Ese tiempo después de activar la regla. Sobrevive a los reinicios. |
| `cron` | `expr` (5 campos o `@daily`, `@hourly`…) | Según ese calendario, en la zona horaria de la regla. |
| `idle` | `for` | Cuando nadie ha usado el teclado ni el ratón durante ese tiempo. |
| `process_exit` | `name` o `pid` | Cuando termina el programa. Con nombre, cuando no queda ninguno con ese nombre. Antes tiene que haberse visto en marcha. Un PID reutilizado por otro proceso cuenta como terminado. |
| `cpu_below` | `percent`, `for` | Cuando el uso **medio** de CPU de los últimos `for` está por debajo de `percent`. |
| `net_below` | `kbps`, `for`, `direction` (`down`, `up`, `both`), `interface` (opcional) | Cuando el tráfico de red **medio** de los últimos `for` está por debajo de `kbps` kilobits por segundo. |
| `battery` | `below` o `above` (%), `for` (opcional) | Cuando el nivel de batería cruza ese umbral (mantenido durante `for`). |
| `power_source` | `is` (`ac` o `battery`), `for` (opcional) | Cuando el equipo está con esa alimentación (mantenida durante `for`). |
| `desktop_session` | — | Cuando se abre una sesión del escritorio (alguien entra), así se pueden abrir aplicaciones. |
| `sun` | `event` (`sunrise`, `sunset`), `offset_minutes`, `latitude`/`longitude` (opcionales) | Al amanecer o al anochecer (más o menos esos minutos). Sin coordenadas usa la ciudad de tu zona horaria (Europe/Madrid → Madrid); se calcula en el equipo, sin internet. |
| `calendar` | `source` (dirección `.ics`/`webcal://` o archivo), `match` (opcional), `before` | Antes de cada cita del calendario cuyo título contenga `match`: Google, Nextcloud, Outlook… exportan esa dirección. Se lee cada 15 minutos; sin internet usa la última copia. |
| `wifi_ssid` | `ssid` | Al conectarse a esa red Wi-Fi. |
| `active` | `for`, `pause` (`5m`) | Tras `for` de uso sin un descanso de `pause`: hora de parar un rato. |
| `used_today` | `for` | Cuando el uso de hoy llega a ese total. |
| `file` | `path`, `pattern` (opcional, `*.pdf`) | Cuando aparece ese archivo, o un archivo así en esa carpeta. |
| `device` | `name` (o parte) | Al conectar un dispositivo: un USB o disco (su nombre o su etiqueta), unos auriculares Bluetooth… |
| `temperature` | `above` (°C), `sensor` (opcional) | Cuando el sensor más caliente (o ese) pasa de esa temperatura. |
| `startup` | `on` (`daemon_start`, `resume`), `delay` | Al arrancar PowerClock (p. ej. al encender) y/o al volver de la suspensión, pasado `delay`. |
| `manual` | — | Solo cuando se ejecuta a mano. |

**Los que vigilan un estado** (`idle`, `process_exit`, `cpu_below`, `net_below`,
`battery`, `power_source`, `desktop_session`, `wifi_ssid`, `active`, `used_today`, `file`, `device`,
`temperature`) se disparan **una vez** cuando el estado pasa a cumplirse, y solo
vuelven a dispararse después de que haya dejado de cumplirse. Seguir inactivo no suspende el equipo
una y otra vez; volver a usarlo rearma la regla. Si el estado ya se cumple al activar la regla (la
batería ya está baja), se dispara.

### Solo si… (`conditions`) y esperar mientras… (`guards`)

Las dos usan los mismos **predicados**:

| `type` | Campos | Se cumple cuando |
|---|---|---|
| `process_running` | `name` | Hay un programa con ese nombre en marcha. |
| `media_playing` | — | Un reproductor está reproduciendo (MPRIS). |
| `ssh_session` | — | Alguien ha iniciado sesión por SSH. |
| `idle` | `for` | Nadie ha usado el equipo durante ese tiempo. |
| `cpu_below` | `percent`, `for` | El uso medio de CPU de los últimos `for` está por debajo de `percent`. |
| `net_below` | `kbps`, `for`, `direction`, `interface` | El tráfico medio de red de los últimos `for` está por debajo de `kbps`. |
| `battery` | `below` o `above`, `for` | Nivel de batería por debajo/encima de eso. |
| `power_source` | `is`, `for` | Enchufado a la corriente o con batería. |
| `time_window` | `start`, `end` (`"22:00"`) | La hora del día está en esa franja (puede cruzar la medianoche: 22:00 → 07:00). |
| `weekday` | `days` (`mon` … `sun`) | Hoy es uno de esos días. |
| `wifi_ssid` | `ssid` | Conectado a esa red Wi-Fi. |
| `desktop_session` | — | Hay una sesión del escritorio abierta. |
| `holiday` | `country` (`ES`), `extra` (fechas) | Hoy es festivo nacional (España, con Viernes Santo calculado) o uno de `extra`: los autonómicos, locales o tus días libres. |
| `tariff_period` | `period` (`valley`, `flat`, `peak`) | La tarifa de la luz está en ese tramo. **Solo si has elegido una tarifa** (ver abajo); sin ella es desconocido. |
| `active`, `used_today`, `file`, `device`, `temperature` | como arriba | Lo mismo que los disparadores del mismo nombre, en este momento. |

Combínalos con `{"all": [ … ]}` (todas), `{"any": [ … ]}` (alguna) y `{"not": … }` (no), anidados
como quieras.

- **Solo si…** (las condiciones) se comprueba en el momento de actuar: si no se cumplen, la ejecución se
  *omite* (y queda anotada).
- **Esperar mientras…** (`"guards": {"any": [ … ]}`) se comprueba justo antes de actuar: mientras se
  cumpla alguna, la ejecución espera y vuelve a mirar cada `retry` (por defecto `5m`), hasta
  `max_wait` (por defecto `2h`); después se omite.
- Un sensor que no se puede leer deja su predicado como **desconocido**, nunca se inventa un
  valor. Las condiciones desconocidas no dejan ejecutar la regla; los motivos para esperar desconocidos no la
  bloquean; `wait_until` sigue esperando.

### Pasos

| `type` | Campos | Hace |
|---|---|---|
| `power` | `action` (`shutdown`, `reboot`, `suspend`, `hibernate`, `hybrid_sleep`, `lock`, `logout`, `screen_off`), `mode` (`graceful` o `force`) | Una acción de energía, tras la cuenta atrás. Apagar, reiniciar y cerrar sesión deben ser el último paso. |
| `run` | `cmd` (lista: programa y argumentos), `cwd`, `env`, `shell`, `timeout`, `wait` | Ejecuta un programa. Con `"shell": true`, `cmd` es una sola línea de órdenes. Con `wait` (por defecto) lo espera y falla si devuelve un error; su salida se guarda en el historial. Al cancelar o agotarse el tiempo se le pide que pare y 5 s después se fuerza. |
| `launch` | `app` (su id, mira `powerclock apps`), `args`, `recipe`, `window` (`screen`, `desktop`, `state`: `normal`/`maximized`/`fullscreen`/`minimized`, `above`), `keep_open`, `stop_signal` (`TERM`, `INT`, `HUP`), `wait_desktop` (por defecto `2m`) | Abre una aplicación instalada en tu sesión del escritorio, esperando hasta `wait_desktop` a que haya una. Se ejecuta como unidad propia (`app-powerclock-….service`), así ve tu pantalla aunque PowerClock arrancara antes de que entraras. `window` la coloca (KDE Plasma); `keep_open` la vuelve a abrir si se cierra (como mucho 3 veces por hora). |
| `media` | `command` (`play`, `pause`, `toggle`, `stop`, `next`, `previous`, `open`), `player` (parte de su nombre), `uri` (con `open`) | Controla un reproductor (MPRIS: VLC, Spotify, Elisa, navegadores…): el indicado, si no el que está sonando, si no el primero abierto. |
| `volume` | `level` (0–150 %), `mute` (`on`/`off`), `fade` | Ajusta el volumen de salida (PipeWire o PulseAudio), poco a poco durante `fade` (un despertador que va subiendo). |
| `sound` | `file` (una ruta o un sonido del tema, p. ej. `alarm-clock-elapsed`) o `say`, `language` | Reproduce un sonido, o dice un texto en voz alta (speech-dispatcher o espeak-ng) y espera a terminar. |
| `desktop` | `theme` (`light`, `dark` o un esquema de color), `wallpaper`, `brightness` (%), `power_profile` (`power-saver`, `balanced`, `performance`) | Ajustes del escritorio (KDE Plasma y GNOME). |
| `network` | `connect`, `disconnect` (una conexión guardada: una VPN…), `wifi` (`on`/`off`) | Conexiones de NetworkManager. |
| `inhibit` | `screen_on`, `do_not_disturb`, `no_sleep`, `duration` | Durante `duration` mantiene la pantalla encendida, retiene los avisos y/o impide que el equipo se suspenda; los pasos siguientes siguen al momento. |
| `screenshot` | `file` (por defecto `{data}/screenshots/{rule}-{datetime}.png`) | Guarda una imagen de la pantalla; el historial dice dónde. |
| `push` | `service` (`ntfy`, `telegram`, `webhook`), `url` (tema de ntfy o webhook), `chat` (Telegram), `title`, `message`, `priority` | Manda un mensaje fuera del equipo: al móvil con [ntfy](https://ntfy.sh) (sin cuenta: suscríbete a tu tema en su app) o con un bot de Telegram (su token va en `powerclock secrets set telegram_token`, nunca en las reglas), o como JSON a cualquier webhook. |
| `ask` | `title`, `body`, `buttons` (1–3), `go_on`, `repeat`, `timeout` (por defecto `1h`), `if_no_answer` (`stop` o `continue`) | Un aviso con botones que espera respuesta; la regla sigue con `go_on` y se para con cualquier otra. Sin respuesta vuelve a mostrarse cada `repeat`. |
| `open` | `target` | Abre un archivo o una URL con tu aplicación predeterminada. |
| `close_app` | `name` y `signal` (`TERM`, `INT` o `HUP`), o `app`; `timeout` (por defecto `30s`) | Pide a tus programas con ese nombre que se cierren, o cierra las copias de `app` que abrió PowerClock; las fuerza pasado `timeout`. |
| `notify` | `title`, `body` | Una notificación del escritorio (se omite en un equipo sin escritorio). |
| `wait` | `duration` | Espera. |
| `wait_until` | `condition` (un predicado), `timeout` (opcional) | Espera hasta que se cumpla la condición; falla pasado `timeout`. |
| `set_wake` | `when` o `after` | Programa un encendido (p. ej. "vuelve a despertarme dentro de 8 h"). |
| `wake_lan` | `mac`, `broadcast` (`255.255.255.255`), `port` (`9`) | Enciende **otro** equipo de la red local (Wake-on-LAN): el NAS antes de la copia, el PC de la oficina… Su tarjeta de red tiene que tenerlo activado en la BIOS/UEFI. En modo prueba no se envía. |

**Variables**: en `run` (`cmd`, `cwd`, `env`), `launch` (`args`), `open` y `notify`, se
sustituyen al ejecutarse `{date}` (2026-09-25), `{time}` (07-30), `{datetime}`
(2026-09-25_07-30), `{weekday}` (thu), `{rule}` (su id), `{home}` y `{data}` (la carpeta de datos de
PowerClock); p. ej. `ffmpeg -i URL -t 2h radio-{date}.mp3`. Cualquier otra llave queda como está.
`run` recibe además las variables de tu sesión del escritorio, así un programa con ventana
encuentra tu pantalla.

**Si un paso falla** (`"on_failure": [ … ]`): pasos que solo se ejecutan entonces, con `{error}`
diciendo qué salió mal, p. ej. `{"type": "push", "url": "https://ntfy.sh/mi-tema", "message":
"{rule}: {error}"}`. En el editor están en *Qué hará*.

Si un paso falla, la regla se detiene (`"on_error": "stop"`) o sigue con el siguiente
(`"continue"`); el historial dice qué paso falló y por qué. Una misma regla nunca se ejecuta dos
veces a la vez, y solo ocurre una acción de energía (y una cuenta atrás) al mismo tiempo.

### Opciones

| Campo | Por defecto | Significado |
|---|---|---|
| `warning` | `60s` | Cuenta atrás antes de cada acción de energía (`0s` para ninguna). |
| `wake` | `false` | Encender el equipo para esta regla (solo con `at`, `countdown` o `cron`). |
| `log_in` | `null` | Con `wake`: entrar solo en la sesión cuando eso enciende el equipo desde apagado, dejando la pantalla `locked` (bloqueada) o `unlocked` (visible); mira más abajo. |
| `on_missed` | `skip` | Si su momento pasó con el equipo apagado o suspendido (más de 2 minutos de retraso): `skip` (omitirla) o `run_once` (ejecutarla una vez). |
| `on_error` | `stop` | `stop` o `continue` cuando falla un paso. |
| `one_shot` | `false` | Desactivar la regla tras dispararse una vez. |
| `dry_run` | `false` | Solo anotar las acciones de energía de esta regla. |
| `timezone` | la del equipo | Nombre IANA (`Europe/Madrid`) para `cron`, `time_window` y `weekday`. |

### Los ejemplos

| Archivo | Qué hace |
|---|---|
| [`backup-nocturno.json`](examples/backup-nocturno.json) | Enciende el equipo por la noche, hace una copia de seguridad si está enchufado y nadie ve un vídeo ni está conectado por SSH, espera a que la red se calme, avisa y apaga. |
| [`buenos-dias-laborables.json`](examples/buenos-dias-laborables.json) | Enciende el equipo a las 07:30 los laborables y abre la agenda; si estaba apagado a esa hora, se ejecuta una vez en cuanto puede. |
| [`suspender-inactivo.json`](examples/suspender-inactivo.json) | Suspende tras 20 minutos sin uso, pero no mientras se reproduce algo, alguien está conectado por SSH o la CPU está ocupada. |
| [`apagar-al-terminar-ffmpeg.json`](examples/apagar-al-terminar-ffmpeg.json) | Apaga cuando termina ffmpeg, una sola vez. |
| [`apagar-tras-descarga.json`](examples/apagar-tras-descarga.json) | Apaga cuando el tráfico de bajada se mantiene por debajo de 50 kbit/s durante 5 minutos. |

## Encender y despertar el equipo

Los ordenadores tienen un reloj de hardware (RTC) con **una** alarma que puede despertarlos de la
suspensión y, si la BIOS/UEFI lo permite, encenderlos estando apagados. PowerClock gestiona esa alarma
por ti:

- Calcula el próximo encendido que necesitan tus reglas (`"wake": true`, `--wake`, `powerclock wake`) y
  lo programa **2 minutos antes**, para que PowerClock esté listo a tiempo. Lo reprograma cada vez
  que cambian las reglas, después de cada ejecución y justo antes de que el equipo se suspenda o se
  apague.
- Nunca mueve una alarma anterior que no sea suya, y deja la suya puesta cuando PowerClock se para
  (todavía tiene que encender el equipo).
- Escribir la alarma necesita root, así que lo hace un **programa diminuto** (el *helper*) que solo hace eso:
  `powerclock helper install` lo copia en `/usr/local/libexec/powerclock-helper` con una política de polkit. Pide
  tu contraseña **una vez**; a partir de ahí los encendidos no piden contraseña mientras tengas la
  sesión iniciada (aunque la pantalla esté bloqueada). Solo acepta "poner / quitar / leer la
  alarma", valida la hora estrictamente y ejecuta `rtcwake` con ruta absoluta y un entorno limpio.
- **Entrar solo en la sesión** (`"log_in": "locked"`, `--log-in`, *y entrar en la sesión* en
  Rápido): los programas con ventana necesitan una sesión del escritorio, y tras encender desde
  apagado el equipo se queda en la pantalla de acceso. PowerClock nunca activa la entrada
  automática para siempre. En su lugar, el helper guarda un **vale de un solo uso** con la hora
  de la alarma para **tu** usuario (quien lo pidió; nunca otra cuenta ni root). Al arrancar,
  antes de la pantalla de acceso, `powerclock-boot.service` lo mira: solo si este arranque es el
  de esa alarma (de la alarma a 10 minutos después, y sin haber pulsado el botón de encendido
  cuando la BIOS lo dice) escribe la entrada automática en `/run` (memoria), adonde apuntan los
  ajustes del gestor de acceso. Después PowerClock **bloquea la pantalla** al momento (salvo que
  la regla diga `unlocked`, para un quiosco con su propio usuario) y borra ese ajuste. Cualquier
  otro arranque pide tu contraseña como siempre, y un corte de luz no deja nada. Funciona con
  SDDM (KDE) y LightDM; con GDM aún no. La alarma se adelanta 3 minutos en vez de 2. Con la
  entrada automática la cartera de KDE no se abre: las recetas de navegador usan un perfil propio
  que no la necesita.
- **Con la sesión cerrada** (encender → ejecutar → apagar sin nadie con la sesión iniciada):
  `powerclock helper install --unattended` añade una regla de polkit para tu usuario, y
  `powerclock service install --linger` mantiene PowerClock funcionando sin iniciar sesión.

**Pruébalo**: `powerclock doctor --test-wake 120` (o *Probar un despertar dentro de 2 minutos* en
Diagnóstico) suspende el equipo y comprueba que despierta solo; si lo despertó otra cosa, te dice
qué. Lo aprendido con un Dell Latitude 5480:

- Un touchpad o un pointing stick pueden despertar un portátil en el mismo momento en que se
  suspende: aparta las manos durante la prueba (PowerClock te da 10 segundos).
- Despertar de la suspensión funcionó a la primera (2 s después de la alarma).
- Encender desde **apagado** también funcionó, enchufado a la corriente y con la BIOS de serie (el
  kernel arrancaba 14 s después de la alarma). Muchos portátiles lo necesitan enchufados, y algunas
  BIOS necesitan *Power Management → Auto On Time* (Dell) o una opción parecida; `powerclock doctor` da
  una pista para tu marca.

## Condiciones y sensores

PowerClock solo lee los sensores que usan tus reglas: si ninguna regla vigila la CPU, nunca lee la CPU.

- **La inactividad** la da el escritorio: en Wayland con `ext-idle-notify` (KDE Plasma, Sway,
  Hyprland…), en GNOME con Mutter, si no con logind, y en X11 con `xprintidle`. En Wayland solo
  cuentan el teclado y el ratón: una película reproduciéndose no hace que el equipo esté "en uso",
  así que añade una guarda `media_playing` a las reglas de inactividad (como hacen los ejemplos).
- **La CPU y la red** se miden cada 5 segundos; `cpu_below` y `net_below` usan la **media** de los
  últimos `for`, así que un pico de 5 segundos no estropea una media de 5 minutos, pero el trabajo
  de verdad sí. Hasta que PowerClock ha medido todo el `for` (p. ej. los 5 primeros minutos tras crear la
  regla), el valor es desconocido; un hueco en las medidas (una suspensión) vuelve a empezar la
  medición. `net_below` sin `interface` suma las interfaces físicas (no `lo`, Docker ni puentes
  virtuales); con `direction: both`, bajada + subida.
- **Los programas** se consultan cada 3 segundos; **la batería y la alimentación** cada 5; **las
  sesiones SSH** cada 10.
- **La reproducción** llega por MPRIS (cualquier reproductor que aparezca en los controles
  multimedia de tu escritorio) y **la Wi-Fi** por NetworkManager.
- **El uso del equipo** sale de la inactividad: cuenta como uso cualquier minuto con teclado o ratón
  (el total de hoy empieza de cero a medianoche en la zona horaria de la regla). **Los archivos** y
  **los dispositivos** se miran cada 5 segundos (USB, etiquetas de discos y Bluetooth por BlueZ);
  **la temperatura** cada 10.
- `powerclock status` y la ventana muestran lo que ve en ese momento cada regla que vigila.

**La tarifa de la luz (opcional).** Solo tiene sentido si tu contrato tiene precios distintos
según la hora (PVPC o tres periodos); con precio fijo da igual. Está desactivada: elígela en
Diagnóstico o con `powerclock tariff es-2.0td` (España 2.0TD: valle de 0 a 8 y fines de semana y
festivos nacionales; punta de 10 a 14 y de 18 a 22; llano el resto) y aparecerá la condición
«Tramo de la tarifa de la luz» para, por ejemplo, dejar las copias y descargas para el valle.
`powerclock tariff none` la quita.

**El ahorro (estimado).** PowerClock anota cada minuto que el equipo está encendido; un hueco es
tiempo apagado o en reposo, y si antes del hueco lo apagó o suspendió PowerClock, ese tiempo cuenta
como ahorro. La energía es ese tiempo por el consumo del equipo encendido (menos 1 W que sigue
gastando), y el dinero, por el precio del kWh. Sin tus datos usa valores típicos (15 W un portátil,
60 W un sobremesa, 0,15 €/kWh): ponlos en Diagnóstico → Electricidad o con `powerclock stats
--watts 45 --price 0.18`. El resumen de los últimos 30 días sale arriba en Historial. Es una
estimación: el tiempo con PowerClock parado cuenta como apagado.

## Seguridad

- **Nada se apaga sin avisar**: cada acción de energía tiene una cuenta atrás que se puede cancelar
  (salvo que pongas `warning: 0s`), con botones en una notificación y en una ventana, además de
  `powerclock cancel`.
- **Ordenado por defecto**: en KDE y GNOME, apagar, reiniciar y cerrar sesión pasan por el gestor
  de sesión para que las aplicaciones puedan pedir guardar. `force` solo se usa si lo pides.
- **Modo prueba** (*dry run*) en todas partes: por acción rápida (`--dry-run`), por regla
  (`"dry_run": true`), para todo el servicio (`powerclock service install --dry-run`, `"dry_run": true` en `daemon.json`, o
  `POWERCLOCK_DRY_RUN=1`). Las acciones de energía y las alarmas solo se anotan; lo demás sí se ejecuta.
- **Esperar mientras…** evita actuar en mal momento (un render, un vídeo, una sesión SSH…).
- **Mínimos privilegios**: PowerClock funciona con tu usuario. Solo el pequeño programa que
  programa la alarma de encendido funciona como root, solo toca la alarma del RTC y lo instalas tú, viendo antes los comandos
  exactos.
- **API privado**: solo escucha en `127.0.0.1` y necesita un token guardado en un archivo que solo
  puede leer tu usuario.
- `run` ejecuta los programas **sin shell** salvo que pongas `"shell": true`.
- Todo lo que se ejecutó, se omitió o se pospuso está en el historial, con su motivo.

## Uso en un servidor

En un equipo sin escritorio (un VPS, un servidor en casa):

```bash
pipx install powerclock                   # sin la ventana
powerclock service install --linger       # sigue funcionando sin nadie con la sesión iniciada
powerclock doctor
```

Todo funciona desde la línea de comandos; las notificaciones se omiten. Ejemplos: reiniciar cada
domingo a las 05:00 con una regla cron, reiniciar cuando termine una tarea larga
(`powerclock reboot --when-exits mi-tarea`), ejecutar scripts de mantenimiento según un calendario.
Encender desde apagado no suele estar disponible en máquinas virtuales.

## Archivos y ajustes

| Archivo | Qué es |
|---|---|
| `~/.config/powerclock/rules.json` | Tus reglas (`{"version": 1, "rules": [ … ]}`). Puedes editarlo a mano: PowerClock lo vuelve a cargar en menos de 2 segundos. Si tiene un error, PowerClock mantiene las últimas reglas buenas, muestra el error en `powerclock status` y no escribe el archivo hasta que lo arregles, así nunca se pierde tu edición. |
| `~/.config/powerclock/daemon.json` | Ajustes del servicio: `port` (por defecto `47831`), `dry_run` (`false`), `log_level` (`info`), `tariff` (`null` o `"es-2.0td"`), `watts` y `price_kwh` (para el ahorro; `null`: valores típicos), `currency` (`€`). |
| `~/.config/powerclock/api.token` | El token secreto del API (solo lo puedes leer tú). |
| `~/.local/share/powerclock/history.sqlite` | El historial de ejecuciones. |
| `~/.config/systemd/user/powerclock.service` | El servicio de usuario (`powerclock service install`). |
| `~/.local/share/applications/powerclock.desktop`, `~/.config/autostart/powerclock-gui.desktop` | Entrada del menú e inicio con la sesión (pestaña Diagnóstico). |

Variables de entorno: `POWERCLOCK_DRY_RUN=1` (modo prueba), `POWERCLOCK_HOME=/una/carpeta` (guarda todos los
archivos en una carpeta; útil para experimentar sin tocar tus reglas) y `POWERCLOCK_BACKEND=fake` (un
equipo simulado, lo usan los tests).

Registro: `journalctl --user -u powerclock -f`.

## El API local

Otros programas pueden manejar PowerClock con su API HTTP en `http://127.0.0.1:47831` con la cabecera
`Authorization: Bearer <token>` (el token está en `~/.config/powerclock/api.token`).

```bash
TOKEN=$(cat ~/.config/powerclock/api.token)
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:47831/pending
curl -s -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"action": "suspend", "in": "30m"}' http://127.0.0.1:47831/quick
```

| Método | Ruta | Uso |
|---|---|---|
| GET | `/health` | Versión, backend, zona horaria, tiempo en marcha, errores de las reglas. |
| GET · POST | `/rules` | Listar · crear. |
| GET · PUT · DELETE | `/rules/{id}` | Leer · reemplazar · borrar. |
| POST | `/rules/{id}/enable` · `/disable` · `/run` · `/cancel` · `/postpone` | Actuar sobre una regla. |
| GET | `/apps` · `/recipes` | Las aplicaciones instaladas (con sus recetas) · las recetas. |
| GET | `/stats?days=30` | Horas encendido, apagado y apagado gracias a PowerClock, acciones y ahorro estimado. |
| GET · PATCH | `/settings` | Los ajustes que se cambian en marcha: `tariff`, `watts`, `price_kwh`, `currency`. |
| POST | `/quick` | Una acción rápida: `action`, `command` o `app` (+ `args`), y `in`, `at`, `when_idle`, `when_exits`, `when_cpu_below`, `when_net_below` (+ `for`), `warning`, `mode`, `wake`, `wake_at`, `dry_run`. |
| POST | `/wake` | `{"at": "07:30"}`: encender el equipo a esa hora. |
| GET | `/pending` | Lo próximo, lo que está en marcha, lo que se vigila y la alarma de encendido. |
| GET | `/runs/{id}` | Una ejecución. |
| POST | `/runs/{id}/cancel` · `/cancel` | Cancelar una ejecución · la cuenta atrás actual o la próxima acción rápida. |
| POST | `/runs/{id}/postpone` · `/postpone` | Posponer (`{"delay": "10m"}`). |
| GET | `/history?limit=&offset=&rule_id=` | Ejecuciones pasadas. |
| GET | `/capabilities` | El informe de `powerclock doctor`. |
| GET | `/schema/rule` | El JSON Schema de una regla. |
| WebSocket | `/events` | Eventos en vivo: `run_started`, `warning_started`, `tick`, `postponed`, `cancelled`, `run_finished`, `rule_changed`, `wake_changed` (el token también puede ir en `?token=`). |

## Solución de problemas

- **"PowerClock no está funcionando en segundo plano"** — `powerclock service install` (o `powerclock service status`;
  registro: `journalctl --user -u powerclock`). Para probarlo en primer plano: `POWERCLOCK_DRY_RUN=1 powerclock-daemon`.
- **Una acción de energía no hace nada** — `powerclock doctor`: cada línea `power.*` dice si tu sistema
  lo permite (p. ej. hibernar necesita swap y `resume=`). Si una regla tiene `dry_run` o el servicio
  está en modo prueba, `powerclock status` lo dice.
- **No se pide a las aplicaciones que guarden** — `powerclock doctor` → `power.graceful` muestra el método
  encontrado (`org.kde.Shutdown` de KDE, `gnome-session-quit` de GNOME); si no hay ninguno, se usa
  logind directamente.
- **El equipo no se enciende** — ejecuta `powerclock doctor --test-wake 120` y lee qué lo despertó (o que
  no llegó a suspenderse). Revisa `wake.helper` y `wake.authorized` en `powerclock doctor`; para encender
  desde apagado, revisa la opción de la BIOS y déjalo enchufado.
- **Se despertó nada más suspenderse** — un touchpad, un pointing stick, un ratón o un teclado
  configurado para despertar el equipo; `powerclock doctor --test-wake` lo nombra.
- **Una regla de inactividad o de CPU nunca se dispara** — mira `powerclock status` (*Vigilando*): muestra
  lo que lee el sensor y cuánto del `for` se ha medido. Si la inactividad sale "desconocida", tu
  escritorio no la ofrece (mira [Condiciones y sensores](#condiciones-y-sensores)).
- **`--when-exits` no hace nada** — PowerClock espera hasta ver el programa en marcha (`powerclock status` dice
  "aún no está en marcha"). Comprueba el nombre exacto del proceso con `ps -e`.
- **No hay icono en la bandeja en GNOME** — instala o activa la extensión *AppIndicator and
  KStatusNotifierItem Support*, o usa la ventana.
- **Mi edición a mano de `rules.json` no se aplica** — `powerclock status` muestra el error; arréglalo y
  PowerClock lo cargará en menos de 2 segundos.

### Aspecto nativo en KDE

Con pipx, PowerClock trae su propia copia de Qt, que no puede cargar el estilo Breeze de KDE, así que los
controles se dibujan con el estilo *Fusion* de Qt (los colores, los iconos y el modo oscuro siguen
a Plasma). Para el aspecto Breeze exacto, usa el Qt de tu sistema:

```bash
sudo apt install python3-pyside6.qtwidgets python3-pyside6.qtnetwork python3-qasync qt6-svg-plugins
pipx install --system-site-packages powerclock    # sin [gui]
```

## Desinstalar

*Diagnóstico → Desinstalar PowerClock…*, o:

```bash
powerclock uninstall            # servicio, menú, inicio con la sesión, permiso de encendido (contraseña) y el programa
powerclock uninstall --purge    # …y también tus reglas y el historial
```

Si lo instalaste con pipx, el último paso es `pipx uninstall powerclock`.

## Desarrollo

```bash
uv sync --all-extras                     # todo, incluidas la interfaz y las herramientas
uv run pytest                            # tests (nunca tocan el sistema real)
uv run ruff check --fix . && uv run ruff format .
POWERCLOCK_DRY_RUN=1 uv run powerclock-daemon --foreground    # un servicio que no apaga nada
uv run powerclock-gui
uv run python scripts/i18n.py update     # textos nuevos a los catálogos de traducción
uv run python scripts/i18n.py compile
uv run python scripts/screenshots.py     # regenerar las imágenes del README
```

El diseño está en [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) y el plan en
[docs/ROADMAP.md](docs/ROADMAP.md). El código está en `src/powerclock/`: `models.py` (las reglas; la
fuente de verdad, también del JSON Schema), `engine/` (planificador, vigilancia de estados,
evaluador, ejecutor, planificador de encendidos), `sensors/`, `daemon/` (API, almacenamiento),
`cli/`, `gui/` y `platform/linux/` (todo lo específico de Linux). Los tests se ejecutan contra un
equipo simulado y un reloj falso; los pocos que leen el sistema real están marcados `real` y se
omiten por defecto.

## Hoja de ruta

- **0.1 — Linux** (ahora): todo lo anterior, con textos más claros y un paso para **abrir
  aplicaciones** instaladas (también Flatpak) con recetas: Chrome en modo quiosco, VLC en bucle,
  Okular en presentación…
- **0.2**: entrar en la sesión al encender el equipo (solo ese arranque, con la pantalla
  bloqueada), reproductores, volumen y ajustes del escritorio, el nuevo diseño, avisos al móvil
  (ntfy, Telegram), más condiciones (amanecer y anochecer, calendario, ficheros, dispositivos,
  tramos de la tarifa de la luz como opción) y encender otros equipos (Wake-on-LAN).
- **0.3 — Windows** y **0.4 — macOS**.
- **1.0**: control remoto (bot de Telegram, interfaz web), varios equipos, MQTT/Home Assistant,
  KDE Connect y describir reglas en lenguaje natural.

## Licencia

[GPL-3.0-or-later](LICENSE). PowerClock es software libre: puedes usarlo, estudiarlo, compartirlo y
mejorarlo; si distribuyes una versión modificada, debe seguir siendo libre con la misma licencia.
