# Arquitectura — PowerClock (paquete `powerclock`)

## 1. Objetivo y principios
App multiplataforma (Linux → Windows → macOS) para automatizar energía y tareas: apagar, suspender, hibernar, **encender/despertar**, y ejecutar programas o scripts por hora o por condición. Las reglas son persistentes y funcionan aunque la GUI esté cerrada.

1. Núcleo común; código de SO aislado en `platform/<os>/`.
2. Demonio de usuario persistente; GUI, CLI y control remoto son clientes.
3. Privilegios mínimos: el demonio NUNCA corre como root; solo un helper diminuto con operaciones en lista blanca.
4. Seguro por defecto: cuenta atrás cancelable antes de acciones de energía, modo graceful, dry-run, guardas anti pérdida de datos.
5. Honesto con el hardware: `powerclock doctor` detecta qué funciona, qué no y cómo arreglarlo.
6. Sencillo para el 80 %: modo rápido estilo KShutdown; reglas avanzadas para el resto.

## 2. Componentes
```
   ┌──────────┐   ┌──────────┐   ┌────────────────────┐
   │ powerclock-gui  │   │ powerclock CLI  │   │ remoto (fase 5)    │
   │ PySide6  │   │ typer    │   │ Telegram / web     │
   └────┬─────┘   └────┬─────┘   └─────────┬──────────┘
        └──── HTTP + WebSocket 127.0.0.1 + token ────┘
                          │
             ┌────────────▼────────────┐
             │       powerclock-daemon         │  usuario · asyncio
             │ API · Store · Scheduler  │
             │ Sensors · Evaluator      │
             │ Executor · WakePlanner   │
             └────────────┬────────────┘
                          │  PlatformBackend (ABC)
     ┌──────────────┬─────┴────────┬──────────────┐
   linux/        windows/        macos/         fake/
 logind D-Bus   Win32/schtasks  pmset/osascript  (tests)
     │                              │
 powerclock-helper (root, polkit)      powerclock-helper (LaunchDaemon)
 solo: wake set/clear/get       solo: pmset schedule
```

| Componente | Qué es |
|---|---|
| `powerclock-daemon` | Servicio de usuario (systemd --user / tarea al iniciar sesión / LaunchAgent). Tiene todo el estado. |
| `powerclock` | CLI: acciones rápidas, gestión de reglas, `doctor`, instalación de servicio y helper. |
| `powerclock-gui` | Bandeja + ventana. Cliente del API. Muestra la cuenta atrás. |
| `powerclock-helper` | Script stdlib que corre como root. Solo `wake-set <epoch>`, `wake-clear`, `wake-get`. |

## 3. Stack y dependencias permitidas
- Python ≥ 3.11 · `pyproject.toml` + hatchling · layout `src/` · desarrollo con `uv`.
- `pydantic` v2 (modelos, validación, JSON Schema) · `fastapi` + `uvicorn` (API local + WS) · `httpx` (cliente) · `typer` + `rich` (CLI) · `psutil` (CPU, red, procesos, batería, usuarios) · `croniter` (recurrencias) · `platformdirs` (rutas) · `websockets` (servidor WS de uvicorn para `/events` y cliente WS de la CLI; `httpx` no habla WebSocket).
- Solo Linux: `dbus-fast` (logind, ScreenSaver, MPRIS, notificaciones) → `dbus-fast; sys_platform == "linux"`.
- Solo Windows (fase 3): `pywin32`.
- Extra `[gui]`: `PySide6-Essentials` (QtCore/Gui/Widgets/Network/Svg…, sin los Addons: 236 MB en disco en vez de 674 MB) y `qasync`. La GUI habla con el API como la CLI: `httpx` (async) y `websockets` para `/events`; nada de QtWebSockets (está en los Addons).
- Dev (grupo `dev` de uv; no es un extra publicado): `pytest`, `pytest-asyncio`, `ruff`, `time-machine`.
- Entry points: `powerclock`, `powerclock-daemon` y `powerclock-gui` (este en `[project.gui-scripts]`: en Windows se lanza sin ventana de consola).
- Licencia: GPL-3.0-or-later (decidida el 24-09-2026; texto en `LICENSE`).

## 4. Modelo de reglas
Regla = disparador + condiciones + guardas + acciones (secuencia) + opciones. Duraciones como texto: `"30s"`, `"5m"`, `"2h"`, `"1d"`.

```json
{
  "id": "backup-nocturno",
  "name": "Backup nocturno",
  "enabled": true,
  "trigger": {"type": "cron", "expr": "0 3 * * *"},
  "wake": true,
  "conditions": {"all": [{"type": "power_source", "is": "ac"}]},
  "guards": {
    "any": [
      {"type": "process_running", "name": "ffmpeg"},
      {"type": "media_playing"},
      {"type": "ssh_session"}
    ],
    "retry": "5m",
    "max_wait": "2h"
  },
  "actions": [
    {"type": "run", "cmd": ["/home/pc/bin/backup.sh"], "timeout": "2h", "wait": true},
    {"type": "wait_until", "condition": {"type": "net_below", "kbps": 50, "for": "5m"}, "timeout": "1h"},
    {"type": "notify", "title": "PowerClock", "body": "Backup terminado"},
    {"type": "power", "action": "shutdown", "mode": "graceful"}
  ],
  "warning": "60s",
  "on_missed": "skip",
  "on_error": "stop",
  "one_shot": false,
  "dry_run": false
}
```

Semántica:
- `conditions` falsas al disparar → **skip** (queda registrado).
- Alguna `guard` verdadera → **posponer**; reintenta cada `retry` hasta `max_wait`, y después skip.
- `actions` se ejecutan en secuencia; si una falla, `on_error`: `stop` (por defecto) | `continue`.
- `warning`: cuenta atrás cancelable antes de cualquier acción `power`.
- `on_missed`: `skip` | `run_once` (el instante pasó con el equipo apagado). Un disparo con más de 2 min de retraso cuenta como perdido; si se perdieron varios, se registra uno solo.
- Sensor que no se puede leer → valor **desconocido** (lógica de tres valores en `all`/`any`/`not`). Condiciones desconocidas → skip; guardas desconocidas → no bloquean; `wait_until` desconocido → sigue esperando.
- Una regla no se solapa consigo misma: si se dispara mientras su ejecución anterior sigue activa, el nuevo disparo se registra como skip.
- **Disparadores de estado** (`idle`, `process_exit`, `cpu_below`, `net_below`, `battery`, `power_source`): la regla se dispara cuando el estado se cumple (sostenido su `for`) y **una sola vez**; se rearma cuando el estado vuelve a ser falso (desconocido ni dispara ni rearma). Si ya se cumple al activarla, se dispara (p. ej. batería ya por debajo del umbral). Seguir inactivo no repite la regla de inactividad; volver a usar el equipo la rearma.
- `process_exit` solo cuenta un proceso **visto en marcha**: si aún no corre, espera a que arranque (nunca lo da por terminado; así una errata en el nombre no apaga el equipo). Con `name` se dispara cuando no queda ninguno con ese nombre; con `pid`, cuando ese proceso desaparece o su PID pasa a otro proceso (se distingue por su hora de inicio).
- `startup`: al arrancar el demonio (`daemon_start`) y/o tras reanudar (`resume`), pasado `delay`. Una regla añadida con el demonio ya en marcha espera al siguiente arranque o reanudación.
- Las ejecuciones de disparadores de estado y `startup` llevan `cause: "trigger"` (las de tiempo, `schedule`; las manuales, `manual`).

**Disparadores** — MVP: `at`, `countdown`, `cron`, `idle`, `process_exit`, `cpu_below`, `net_below`, `battery`, `power_source`, `desktop_session` (M10: cuando se abre la sesión del escritorio), `startup` (arranque del demonio o tras despertar), `manual`. M17: `sun` (amanecer/anochecer ± minutos; NOAA, coordenadas de `zone1970.tab` si no se dan), `calendar` (`.ics`/`webcal://`/archivo, `match`, `before`; `engine/calendar.py` lee cada 15 min, expande RRULE DAILY/WEEKLY(BYDAY)/MONTHLY/YEARLY con INTERVAL/COUNT/UNTIL/EXDATE en la hora de pared de su zona y avisa al planificador si cambian las citas), y de estado `wifi_ssid`, `active` (uso sin descanso de `pause`), `used_today` (suma de minutos con entrada, se reinicia a medianoche), `file` (archivo o patrón en carpeta), `device` (USB, etiquetas de disco, Bluetooth; `platform/linux/devices.py`), `temperature` (psutil). Más adelante: `webhook`, `telegram`.
Los disparadores de estado llevan `for` (condición sostenida N tiempo), p. ej. `{"type":"cpu_below","percent":10,"for":"5m"}`.

**Predicados** (para conditions/guards/wait_until): `process_running`, `power_source`, `battery`, `idle`, `cpu_below`, `net_below`, `media_playing`, `ssh_session`, `time_window`, `weekday`, `wifi_ssid`, `desktop_session` (hay una sesión del escritorio donde abrir apps); M17: `holiday` (festivos nacionales de España con Pascua calculada + `extra`), `tariff_period` (desconocido sin tarifa elegida), y `active`, `used_today`, `file`, `device`, `temperature`. Árbol lógico: `all` / `any` / `not`.

**Acciones**: `power` (`shutdown|reboot|suspend|hibernate|hybrid_sleep|lock|logout|screen_off`, `mode: graceful|force`) · `run` (`cmd` lista, `cwd`, `env`, `shell` false por defecto, `timeout`, `wait`) · `launch` (abrir una aplicación instalada, M10) · `open` (archivo/URL) · `close_app` (por `name` de proceso, con `signal` TERM/INT/HUP, o por `app`: las que abrió PowerClock; kill tras `timeout`) · `notify` · `wait` · `wait_until` · `set_wake` (absoluto/relativo) · M18: `wake_lan` (`mac`, `broadcast`, `port`; paquete mágico por UDP broadcast, 3 veces, `engine/wol.py` con sockets de la biblioteca estándar, igual en todos los SO; en modo prueba no se envía) · M13: `media` (MPRIS: play/pause/toggle/stop/next/previous/open con `uri`), `volume` (`level` 0–150 %, `mute` on/off, `fade` gradual en el motor, un cambio por segundo), `sound` (`file` o sonido del tema por nombre, o `say` con `language`), `desktop` (`theme` light/dark/esquema, `wallpaper`, `brightness`, `power_profile`), `network` (`connect`/`disconnect` de conexiones guardadas, `wifi` on/off), `inhibit` (pantalla encendida, No molestar, sin suspender; durante `duration` en segundo plano, se devuelven al apagar el demonio) y `screenshot` · M16: `push` (ntfy con `url` del tema, título en RFC 2047 si no es ASCII; Telegram con el secreto `telegram_token` y `chat`; webhook = POST JSON {title, message, rule}; httpx con 20 s; `engine/push.py`, sin código de SO), `ask` (aviso con 1–3 botones; sigue con `go_on`, para con otra respuesta —sin fallar: el paso dice «the rule stops here»—, repite cada `repeat` hasta `timeout`) y `on_failure` en la regla (pasos que solo corren si uno falla, con `{error}`; salen en el historial marcados). Secretos: `secrets.json` (0600) en la carpeta de configuración, `powerclock secrets set|list|rm`; nunca en `rules.json`, así exportar reglas no los filtra. En Linux (`platform/linux/media.py` y `settings.py`): wpctl→pactl, pw-play→paplay→aplay, spd-say→espeak-ng, plasma-apply-*→gsettings, brillo por D-Bus de KDE o GNOME→brightnessctl, power-profiles-daemon por D-Bus→powerprofilesctl, nmcli, `org.freedesktop.ScreenSaver.Inhibit`, `org.freedesktop.Notifications.Inhibit`, logind `sleep:idle` en modo `block`, spectacle→gnome-screenshot→grim. En modo prueba se ejecutan (como `run`).

**Variables** (M10, `engine/variables.py`): `{date}` (2026-09-25), `{time}` (07-30), `{datetime}` (2026-09-25_07-30), `{weekday}` (thu), `{rule}` (id) y las del demonio `{home}` y `{data}` (su carpeta de datos). Se sustituyen al ejecutarse en `run` (`cmd`, `cwd`, `env`), `launch.args`, `open.target` y `notify`; valen la hora de inicio de la ejecución en la zona de la regla y están escritas para caber en nombres de archivo. Solo se tocan esos nombres exactos: `{a,b}` del shell, `%(ext)s` de yt-dlp o un JSON quedan como están. `run` recibe además el entorno de la sesión del escritorio (ver `session_env`), así ve la pantalla aunque el servicio arrancara antes que la sesión.

**Paso `launch` (M10, hecho el 25-09-2026).** Abre una aplicación instalada en la sesión gráfica. Sale de 32 casos de uso: abrir aplicaciones es la pieza que más piden (13), y 20 de las 76 apps del equipo del usuario son Flatpak.
```json
{"type": "launch", "app": "google-chrome", "recipe": "chromium.kiosk",
 "args": ["--kiosk", "https://panel.ejemplo.es"],
 "window": {"screen": 2, "desktop": null, "state": "fullscreen", "above": false},
 "keep_open": true, "stop_signal": "TERM", "wait_desktop": "2m"}
```
- Espera hasta `wait_desktop` a que haya sesión del escritorio (`desktop_session`); si no llega, el paso falla con «no desktop session after 2m».
- Linux (`platform/linux/apps.py`, `session.py`, `kwin.py`): el catálogo lee los `.desktop` según la especificación de freedesktop.org ($XDG_DATA_HOME primero, luego $XDG_DATA_DIRS, más las carpetas de Flatpak y Snap por si al servicio le faltan); `Hidden` y `TryExec` sin programa las quitan, `NoDisplay` las oculta de la lista. La orden sale de `Exec`: los argumentos ocupan el sitio de `%f/%F/%u/%U` (o van al final); tras `--` o en la sección `@@u … @@` de `flatpak run --file-forwarding` solo van archivos y direcciones, así que las opciones (`-…`) se colocan justo antes. `Terminal=true` → `NotSupported` (usar `run` con `konsole -e`).
- Se arranca como servicio transitorio `app-powerclock-<id>-<aleatorio>.service` del gestor de usuario (`StartTransientUnit`): hereda el entorno que el escritorio publicó, `KillSignal` = `stop_signal`, `TimeoutStopSec` 30 s, `CollectMode=inactive-or-failed`; con `keep_open`, `Restart=always` cada 5 s y como mucho 3 veces por hora (`StartLimitBurst`). Si falla en los 2 primeros segundos, el paso falla y dice qué mirar (`journalctl --user -u …`). Sin gestor de usuario se lanza directamente (y `keep_open` → `NotSupported`). `close_app` con `app` para esas unidades (`StopUnit`).
- `window`: en KDE Plasma, un guion de KWin cargado por D-Bus (`org.kde.kwin.Scripting`) espera la primera ventana nueva que encaje (por PID, `desktopFileName` o clase) y la coloca; se descarga pasado `wait_window` (30 s). Fuera de KWin el paso funciona y lo anota («window placement needs KDE Plasma»).
- `app` es el identificador de escritorio (`org.kde.okular`, `one.ablaze.floorp`), no una ruta: sobrevive a actualizaciones y el backend construye la orden desde el `.desktop` (con `flatpak run` si toca). El catálogo de apps instaladas lo da el backend (menú, Flatpak, Snap).
- `recipe`: opcional; las recetas son datos (`src/powerclock/recipes.json`, 25 al empezar) que rellenan `args` con opciones comprobadas (Chrome quiosco o ventana de app, VLC en bucle, Okular en presentación…). Añadir programas no toca el código. En sus `args`, `<nombre>` es lo que rellena el usuario (con su etiqueta en `inputs`, en/es) y `{data}`… se sustituye al ejecutar. Los perfiles de navegador de los quioscos van en `{data}/profiles/` con `--password-store=basic`.
- `window`: esperar a que aparezca y colocarla (pantalla, escritorio virtual, `fullscreen|maximized|minimized`, encima de todo); en KDE con guiones de KWin por D-Bus. `keep_open`: reabrirla si se cierra, con límite por hora. Al cerrar (`close_app`) se podrá elegir la señal (algunos grabadores solo guardan con SIGINT).
- `run` sigue existiendo para guiones y órdenes sin ventana.

**Estadísticas de uso y ahorro (M18).** El latido del demonio (cada 60 s) anota periodos encendido en `history.sqlite` (tabla `awake`: `since`, `until`, `ended`); un silencio de más de 3 min abre un periodo nuevo (el equipo estuvo apagado o en reposo). Justo antes de un `shutdown|reboot|suspend|hibernate|hybrid_sleep` real, el ejecutor emite `power_action` y el periodo se cierra con esa acción; los latidos de los siguientes 3 min se ignoran (el apagado ordenado tarda). `engine/savings.py` suma: encendido, apagado, apagado tras una acción de PowerClock (sin `reboot`), y kWh = horas × (W − 1 W de reposo) / 1000. W y €/kWh son ajustes (`watts`, `price_kwh`); sin ellos, 15 W con batería, 60 W sin ella y 0,15 €/kWh, marcados como típicos. El tiempo con el demonio parado cuenta como apagado: es una estimación y se dice así.

**Tarifa de la luz (M17, decidido el 25-09-2026).** Ajuste opcional del demonio, **desactivado por defecto**: solo compensa a quien tiene discriminación horaria (PVPC o contrato de tres precios; con precio fijo 24 h da igual la hora). Valores: sin tarifa · España 2.0TD (punta 10–14 y 18–22, llano 8–10, 14–18 y 22–24, valle 0–8; fines de semana y festivos nacionales, valle) · franjas propias (otros países; **pendiente**: de momento solo 2.0TD). Se guarda en `daemon.json` (`tariff`), se elige en Diagnóstico, con `powerclock tariff` o `PUT /settings/tariff`, y `/health` la devuelve. Solo con una tarifa elegida aparece la condición `tariff_period` (`valley|flat|peak`) en el editor y en las recetas.

**Detalles fijados en M1** (referencia completa: el JSON Schema de `GET /schema/rule`, generado desde `src/powerclock/models.py`):
- Todo objeto rechaza campos desconocidos: una errata en `rules.json` da error en vez de ignorarse.
- `id`: `[a-z0-9][a-z0-9_-]*` (máx. 64). Duraciones compuestas en orden d→h→m→s (`"1h30m"`), resolución 1 s.
- Instantes (`at.when`, `set_wake.when`, `countdown.armed_at`) en ISO 8601 **con zona**: `"2026-09-24T07:30:00+02:00"`.
- `timezone` (opcional, nombre IANA como `"Europe/Madrid"`): zona de `cron`, `time_window` y `weekday`; por defecto, la del sistema.
- `countdown`: `{"duration": "30m", "armed_at": null}`. El demonio rellena `armed_at` al activar la regla, así la cuenta atrás sobrevive a reinicios.
- `cron`: 5 campos o `@hourly`, `@daily`, `@weekly`…
- `wake: true` solo con disparadores de tiempo (`at`, `countdown`, `cron`).
- `shutdown`, `reboot` y `logout` deben ser la última acción (nada detrás llegaría a ejecutarse); tras `suspend` o `hibernate` sí puede haber más.
- `cpu_below` y `net_below` exigen `for`. `net_below.kbps` va en kilobits/s, con `direction` (`down|up|both`) e `interface` opcionales. `battery`: `below` o `above`.
- Exactamente uno de: `process_exit` → `name` | `pid`; `set_wake` → `when` | `after`; `battery` → `below` | `above`.
- `startup`: `on` (`daemon_start`, `resume`) y `delay`. `time_window`: `start`/`end` como `"22:00"`, cruza medianoche si start > end. `weekday.days`: `mon…sun`.
- `run` con `shell: true` → `cmd` es una única línea de comando; `timeout` solo con `wait: true`.

**Almacenamiento** (`platformdirs`; `POWERCLOCK_HOME` lo concentra todo en un directorio, útil para tests y pruebas aisladas): `rules.json` en user_config_dir (`{"version": 1, "rules": [...]}`, editable a mano, validado al cargar, escritura atómica 0600, recarga en caliente cada 2 s) · `history.sqlite` en user_data_dir (0600; también guarda la última marca de vida del demonio, cada 60 s, para detectar disparos perdidos mientras estuvo parado) · `daemon.json` (`port`, `dry_run`, `log_level`) · `api.token` (0600).
- Si `rules.json` tiene **cualquier** error (JSON roto, regla inválida, id duplicado): al arrancar se cargan las reglas válidas; en una recarga siguen funcionando las anteriores; en ambos casos el demonio **no escribe** el archivo hasta que se corrija (las escrituras del API responden 409), para no perder nunca una edición a mano. Los errores aparecen en `/health` y `powerclock status`.

## 5. Motor
- **Scheduler**: bucle asyncio. Los disparadores de tiempo calculan `next_fire` (croniter + zoneinfo). Duerme hasta el más cercano, como mucho 30 s, para resincronizar tras suspensiones, saltos de reloj y cambios de horario.
- **Sensores bajo demanda** (`SensorHub`, `sensors/registry.py`): se sondean de continuo solo los que hacen falta: los disparadores de estado de las reglas activas y los predicados con `for` de las reglas activas o con una ejecución en curso. Intervalos: inactividad, CPU, red, batería/AC y multimedia 5 s; procesos 3 s; SSH 10 s; Wi-Fi 30 s. El resto (p. ej. una guarda `process_running` de un cron diario) se lee solo cuando se pregunta y la lectura se reutiliza mientras tiene menos del 90 % de su intervalo. Sin reglas que lo usen, no se lee nada.
- **`for` e historial**: `cpu_below` y `net_below` comparan la **media** de las muestras de los últimos `for` con el umbral (un pico de 5 s no rompe una media de 5 min; una carga real sí). `battery`/`power_source` con `for`: todas las muestras de ese tiempo deben cumplirlo. `idle` no necesita historial (el SO ya cuenta el tiempo inactivo). Hasta que el historial cubre todo el `for`, el valor es **desconocido**; un hueco entre muestras de más de 3 intervalos (suspensión, salto de reloj) lo reinicia. Consecuencia: una guarda con `for` de una regla recién creada no bloquea hasta tener historial. `net_below` con `direction: both` suma bajada y subida; sin `interface`, el total de las interfaces físicas (sin `lo`, `docker*`, `veth*`, `br-*`, `virbr*`).
- **Watcher** (`engine/watcher.py`): un bucle que pide al hub las muestras que tocan, evalúa los disparadores de estado y dispara las reglas (semántica en §4). Duerme hasta la siguiente muestra; si nada se sondea, hasta que cambien las reglas o el equipo reanude.
- **Evaluator**: evalúa conditions/guards/wait_until. `time_window` y `weekday` los resuelve él con el reloj y la zona de la regla; el resto se lo pregunta al `SensorHub`, que aplica `for` con su historial. Las lecturas en bruto llegan por `Readings` (`sensors/base.py`): psutil para CPU, red, procesos, batería/AC y SSH, y el backend para inactividad, multimedia y Wi-Fi (`sensors/system.py`); en los tests, `FakeReadings`.
- **Executor**: cada ejecución es un `Run` (id, estado: `warning|running|waiting|done|failed|cancelled|skipped|postponed`, pasos con su resultado y motivo), cancelable por API. Solo una acción de energía activa a la vez (la segunda espera en `waiting`), así "la cuenta atrás actual" está siempre bien definida. Durante la cuenta atrás, notificación con botones Cancelar / Posponer 10 min. `notify` es de mejor esfuerzo: sin escritorio queda como skip, no como fallo. `run` guarda los últimos 4000 caracteres de la salida; al cancelar o agotar `timeout`, el comando recibe SIGTERM y, 5 s después, SIGKILL.
- **Reloj**: todo el motor lee la hora y duerme a través de `Clock` (`engine/clock.py`); los tests usan `FakeClock`, que distingue el reloj de pared (`jump`, como una suspensión) del monótono (`advance`).
- **Cron y cambio de hora**: cron sigue la hora local de la regla. En el hueco de primavera la ejecución se desplaza (02:30 → 03:30); en la hora repetida de otoño cada hora local se ejecuta una sola vez, en su primera aparición.
- **Dry-run (kill-switch)**: con `POWERCLOCK_DRY_RUN=1` se usa el backend **real** envuelto en `DryRunPlatform`: las lecturas (inactividad, multimedia, capacidades…) son reales, pero `power`, `wake_set` y `wake_clear` solo se registran. `dry_run: true` en una regla hace lo mismo con sus acciones `power`. `run`, `open`, `close_app` y `notify` sí se ejecutan.
- **Resume/arranque**: tras `after_resume` (PrepareForSleep(false)) el scheduler revisa al momento; sin eventos de energía lo nota en ≤ 30 s. Al arrancar, el demonio pasa a cada regla la última vez que se revisó (`since`) para detectar lo perdido y aplicar `on_missed`.
- **Reglas que cambia el motor**: armar un `countdown` (al crear o reactivar la regla) y desactivar una `one_shot` tras dispararse emiten `rule_changed` para que el demonio lo guarde.

## 6. Encendido/despertar — WakePlanner (diferenciador)
- El RTC guarda UNA sola alarma. WakePlanner (`engine/wake.py`) calcula el próximo disparo de las reglas activas con `wake: true`, le resta un margen (120 s, para que el demonio esté listo), lo redondea a segundos (nunca a menos de 10 s vista) y lo programa. Las peticiones sueltas (`powerclock wake --at`, `--wake` de las acciones rápidas, la acción `set_wake`) se convierten en reglas `quick-…` de un solo uso con `wake: true` y un `notify`, así solo hay una fuente de verdad.
- Nunca retrasa ni borra una alarma **ajena** que llegue antes (p. ej. la de `powerclock doctor --test-wake` o un `rtcwake` a mano): solo borra la suya. Al parar el demonio la alarma **se queda** (tiene que encender el equipo). Los errores (helper sin instalar, sin permiso) quedan en `/pending` → `wake.error` y en `powerclock status`, y se reintentan en el siguiente cambio.
- Se reprograma en tres momentos: (a) al cambiar reglas, (b) tras cada disparo, (c) justo antes de apagar/suspender. Para (c), el demonio toma un inhibidor logind `delay` (`shutdown:sleep`) **solo mientras hay una alarma que mantener**; en `PrepareForShutdown`/`PrepareForSleep(true)` reescribe la alarma y libera el inhibidor. Así se cubren también los apagados manuales del usuario. Tras reanudar, vuelve a leer la alarma (puede haberse consumido) y programa la siguiente.
- Lectura: el backend lee `/sys/class/rtc/rtc0/wakealarm` directamente (es legible sin privilegios), convirtiendo si el RTC va en hora local. Escritura: `pkexec powerclock-helper wake-set|wake-clear`; códigos 126/127 de pkexec → `NotSupported` (sin permiso) con la pista de `--unattended`.
- `powerclock doctor --test-wake N` (60–3600 s): tras confirmación explícita y 10 s para apartar las manos (un touchpad o un pointing stick pueden despertarlo), programa la alarma (si falla, **no suspende**), suspende y, al reanudar, dice si despertó sola (`ok`), antes de tiempo (¿a mano?), tarde o si no llegó a suspender, y **qué lo despertó** si el SO lo dice (`wakeup_source()`: en Linux `/sys/power/pm_wakeup_irq` + `/proc/interrupts` + nombres de `/sys/class/input`; solo se muestra si cambió durante la prueba, porque puede quedarse viejo). En dry-run no hace nada.
- Primera prueba en el Latitude 5480 (23-09-2026): suspensión S3 correcta, pero despertó a los ~11 s por la IRQ 51 = touchpad Alps `DLL07A7:01` / DualPoint Stick (wakeup habilitado), no por el RTC. De ahí la cuenta atrás y el diagnóstico anteriores.
- Segunda prueba (24-09-2026, con las manos fuera): **despertó sola desde S3 a los 2 s de la alarma** (alarma 11:20:03, reanudación 11:20:05). El despertar desde suspensión funciona en el Latitude 5480.
- Tercera prueba (24-09-2026, **desde S5**, con AC): `powerclock-helper wake-set` para las 11:31:06, apagado a las 11:26:12 y **se encendió sola**; el kernel leyó el RTC a las 11:31:20 (≈14 s de POST y arranque). El encendido programado desde apagado funciona en el Latitude 5480 con la BIOS de serie.
- Linux: el helper usa `rtcwake -m no -t <epoch>`, que respeta RTC en UTC o localtime según `/etc/adjtime`; si falla, recurre a `/sys/class/rtc/rtc0/wakealarm`: escribe `0` y después el valor **relativo** `+<segundos>`. Un valor absoluto el kernel lo interpreta en la hora del RTC, que puede ir en hora local (arranque dual con Windows) y desplazaría la alarma 1–2 h; el relativo no depende de eso. Para consultar: `rtcwake -m show`. Para borrar: `rtcwake -m disable`.
- **Modo desatendido** (encender → ejecutar → apagar sin iniciar sesión): el servicio de usuario necesita `loginctl enable-linger <usuario>`, y sin sesión activa `allow_active` no se aplica. Por eso hace falta una regla polkit opcional (`50-powerclock-unattended.rules`) que conceda a ese usuario las acciones `org.freedesktop.login1.power-off/reboot/suspend/hibernate` (y sus variantes `-multiple-sessions`) **y la acción del helper `org.powerclock.helper.wake`**; sin esta última, el WakePlanner no podría programar el siguiente despertar y la cadena se cortaría tras el primero. Lo instalan `powerclock service install --linger` y `powerclock helper install --unattended`.
- **Entrar al encender (M12, hecho el 25-09-2026; falta la prueba real): llave de un solo uso.** Campo `log_in: locked|unlocked` de la regla (exige `wake`), `--log-in` en la CLI y «y entrar en la sesión» en Rápido; el WakePlanner adelanta la alarma 3 min (no 2) y arma el vale con `autologin_arm`, o lo desarma. Helper: `autologin-arm <epoch> <sesión|-> <locked|unlocked>` (el usuario sale de `PKEXEC_UID`/`SUDO_UID` ≥ 1000, nunca de un argumento; la sesión debe existir en wayland-sessions/ o xsessions/; `-` = la de SDDM), `autologin-disarm`, `autologin-done` y `boot` (lo llama `powerclock-boot.service`, `DefaultDependencies=no`, `Before=display-manager.service`, `WantedBy=graphical.target`). `boot` gasta el vale siempre, acepta de 60 s antes de la alarma a 600 s después, descarta el tipo de encendido SMBIOS 0x06 (botón), y deja `/run/powerclock/used` (uid y modo) para el demonio, que al ver la sesión bloquea la pantalla (si `locked`) y llama a `autologin-done`. Instalar el permiso de encendido instala también el servicio y los enlaces de SDDM/LightDM; `doctor` lo comprueba (`autologin`). Las apps gráficas necesitan una sesión, y tras un encendido desde S5 el equipo se queda en la pantalla de acceso. Nunca activamos la entrada automática permanente; en su lugar:
  1. Al programar un encendido de una regla con «entrar en la sesión», el ayudante guarda un vale en `/var/lib/powerclock/autologin.json` (usuario, sesión, hora de la alarma). Solo root escribe ahí.
  2. `powerclock-boot.service` (sistema, `Before=display-manager.service`) lo lee al arrancar: si la hora está entre la alarma y 10 min después (y, si la BIOS lo dice, el arranque fue por el reloj y no por el botón: SMBIOS *Wake-up Type*), escribe la orden de entrada automática en `/run/powerclock/autologin.conf` y borra el vale.
  3. SDDM: `/etc/sddm.conf.d/zz-powerclock.conf` es un enlace a ese fichero, creado una vez al instalar; si no existe, SDDM lo ignora. LightDM: igual con `lightdm.conf.d`; GDM: `/run/gdm/custom.conf` (a confirmar). Gestor desconocido → `NotSupported`, sin tocar nada.
  4. En cuanto aparece la sesión: bloquear la pantalla y borrar el fichero de `/run`. Al estar en memoria, un corte de luz no deja nada activado; con `Relogin=false`, cerrar la sesión vuelve a pedir contraseña.
  - KWallet no se abre sin contraseña (`sddm-autologin` no usa `pam_kwallet5`): los navegadores de las recetas usan perfil propio y `--password-store=basic`. Con el disco cifrado (LUKS) el arranque se para antes; no aplica.
  - Quiosco (pantalla visible): con un usuario dedicado sin permisos de administrador. Casi toda la automatización (opciones de arranque, D-Bus, MPRIS) funciona con la pantalla bloqueada; el teclado y el ratón virtuales no (las pulsaciones irían al bloqueo).
  - Medido en el Latitude: 32 s de la alarma a la pantalla de acceso, unos 50 s al escritorio listo; el margen pasa a 3 min cuando hay que entrar.
- Windows (fase 3): tarea programada con `WakeToRun` que ejecuta `powerclock wake-hook`. `doctor` comprueba los temporizadores de reactivación y Modern Standby (`powercfg /a`).
- macOS (fase 4): `pmset schedule wakeorpoweron` vía helper.
- Realidad del hardware: desde S3/S4 suele funcionar; desde S5 depende de la BIOS/UEFI; en portátiles suele requerir corriente AC. `doctor` lo avisa y lo verifica con `--test-wake`.

## 7. PlatformBackend
```python
class PlatformBackend(ABC):
    name: str
    async def power(self, action: PowerAction, mode: PowerMode) -> None: ...
    async def wake_set(self, when: datetime) -> None: ...
    async def wake_clear(self) -> None: ...
    async def wake_get(self) -> datetime | None: ...
    async def idle_seconds(self) -> float | None: ...
    async def media_playing(self) -> bool | None: ...
    async def wifi_ssid(self) -> str | None: ...
    async def notify(self, title: str, body: str, actions: list[str] | None = None) -> str | None: ...
    async def open(self, target: str) -> None: ...
    async def apps(self) -> list[AppInfo]: ...                     # M10: las aplicaciones instaladas
    async def launch(self, request: LaunchRequest) -> str: ...    # M10: abrir una (app, args, window, keep_open, stop_signal)
    async def close_app(self, app: str, grace: timedelta) -> int: ...
    async def desktop_session(self) -> bool | None: ...
    async def session_env(self) -> dict[str, str]: ...              # el entorno de la sesión del escritorio
    async def subscribe_power_events(self, callback) -> None: ...   # before_sleep, after_resume, before_shutdown
    def inhibit_delay(self) -> AbstractAsyncContextManager: ...
    async def capabilities(self) -> list[Capability]: ...
```
- `Capability(id, supported: bool, detail: str, fix_hint: str | None)`.
- Solo `power` y `capabilities` son obligatorios; cualquier otro método que un backend no implemente lanza `NotSupported(feature, detail, fix_hint)`.
- `notify(title, body, actions)`: `actions` es `{clave: etiqueta}`. Sin `actions` vuelve enseguida; con `actions` espera a que el usuario elija una (devuelve su clave) o cierre la notificación (`None`), así que se lanza como tarea y se cancela cuando deja de hacer falta.
- `subscribe_power_events` recibe un `PowerEvent` (`before_sleep`, `after_resume`, `before_shutdown`).
- Lo genérico (CPU, red, procesos, batería, usuarios) va en `sensors/` con psutil, no en el backend.
- `FakePlatform`: en memoria, registra todas las llamadas. Se usa en TODOS los tests (el dry-run usa el backend real, ver §5). Se selecciona con `POWERCLOCK_BACKEND=fake`.

**Linux (detalle)**
- Energía: logind `org.freedesktop.login1.Manager` → `CanPowerOff/CanSuspend/CanHibernate…` y luego `PowerOff/Reboot/Suspend/Hibernate/HybridSleep(interactive=true)`. Apagar/reiniciar comprueban `Can*` **antes** de pedírselo al escritorio; `no`/`na` → `NotSupported`.
- Graceful: en KDE, `org.kde.Shutdown` (`logoutAndShutdown`, `logoutAndReboot`, `logout`) para que las apps pidan guardar; en GNOME, `gnome-session-quit`. Verificar por introspección en tiempo de ejecución y recurrir a logind si no existe.
- Bloquear y cerrar sesión forzado: `Lock`/`Terminate` sobre la sesión gráfica del usuario (propiedad `Display` de `login1.User`, que funciona también desde un servicio systemd de usuario). Apagar pantalla: `kscreen-doctor --dpms off` (KDE) → `PowerSaveMode` de `org.gnome.Mutter.DisplayConfig` (GNOME) → `xset dpms force off` (X11).
- Idle (debe funcionar en Wayland), estrategias en cadena: **Wayland `ext-idle-notify-v1`** (cliente mínimo en Python puro, `linux/wayland.py`; v2 mide solo teclado/ratón; granularidad 5 s) → `org.gnome.Mutter.IdleMonitor.GetIdletime` (GNOME, ms) → logind `IdleHint`/`IdleSinceHint` (solo tan fiable como el escritorio que lo marque) → `xprintidle` (X11). `org.freedesktop.ScreenSaver.GetSessionIdleTime` queda **fuera**: en KDE Wayland responde "not supported on this platform" (verificado en M3) y en X11 sus unidades no son fiables para decidir una suspensión.
- Multimedia: MPRIS (`PlaybackStatus == "Playing"`); sin bus de sesión → desconocido. Notificaciones: `org.freedesktop.Notifications`; con botones, urgencia crítica y sin caducidad, se espera `ActionInvoked`/`NotificationClosed` y se cierra con `CloseNotification` si se cancela. Wi-Fi: `PrimaryConnection` de NetworkManager → `SpecificObject` → `Ssid`.
- Entorno de un servicio systemd de usuario: puede faltar `DBUS_SESSION_BUS_ADDRESS` (se usa `$XDG_RUNTIME_DIR/bus`) y `WAYLAND_DISPLAY` (se busca `wayland-*` en el directorio de ejecución y se pasa a `kscreen-doctor`/`xdg-open`).
- Zona horaria (`timezone()`): `$TZ` → enlace `/etc/localtime` → `/etc/timezone` → contenido de `/etc/localtime` → UTC.
- Eventos: señales `PrepareForSleep`/`PrepareForShutdown`; inhibidor `Inhibit("shutdown:sleep", "powerclock", motivo, "delay")`.
- Helper: `/usr/local/libexec/powerclock-helper` (root:root 0755, `#!/usr/bin/python3` del sistema, solo stdlib) + `/usr/share/polkit-1/actions/org.powerclock.helper.policy` (acción `org.powerclock.helper.wake`) con `allow_active=yes` y la anotación `org.freedesktop.policykit.exec.path` → `pkexec /usr/local/libexec/powerclock-helper wake-set <epoch>` sin contraseña en sesión activa. Valida que el epoch sea solo dígitos, al menos 5 s en el futuro y como mucho 366 días. Nunca ejecuta nada arbitrario: `rtcwake` con ruta absoluta y entorno limpio. `wake-get` imprime el epoch UTC o `none`.
- `powerclock helper install [--unattended] [--print]` muestra los comandos `sudo install -D -o root -g root -m 0755|0644 …` exactos y solo los ejecuta si el usuario responde que sí; con `--unattended` genera la regla para ese usuario en su directorio de datos. `uninstall` borra la alarma y los tres archivos. `doctor` comprueba que el helper instalado coincide con el de esta versión, pregunta a polkit con `pkcheck --action-id org.powerclock.helper.wake --process <pid>` si este proceso puede programar la alarma sin contraseña (sin ejecutar nada como root), y muestra la alarma actual.
- `doctor` informa de: RTC presente, helper instalado, Can*, hibernación configurada (swap/resume), AC/batería, sesión Wayland/X11, escritorio, fabricante/modelo (`/sys/class/dmi/id/`) con pista de BIOS (p. ej. Dell: *Power Management → Auto On Time*), linger activo, RTC UTC/local.

## 8. API local
`http://127.0.0.1:<puerto>` (por defecto 47831, configurable) · cabecera `Authorization: Bearer <token>`.

| Método | Ruta | Uso |
|---|---|---|
| GET | `/health` | versión, uptime, backend |
| GET · POST | `/rules` | listar · crear |
| GET · PUT · DELETE | `/rules/{id}` | ver · editar · borrar |
| POST | `/rules/{id}/enable` · `/disable` · `/run` | |
| POST | `/rules/{id}/cancel` · `/rules/{id}/postpone` | una regla concreta: su ejecución en curso (o su cuenta atrás); si es una acción rápida que aún no ha actuado, la cancela (queda en el historial) o retrasa su momento `{"delay"}`. Otras reglas sin ejecución en curso → 409 (se desactivan o se editan) |
| POST | `/quick` | acción rápida estilo KShutdown → regla `one_shot` |
| POST | `/wake` | `{"at": "07:30"}` → regla de despertar de un solo uso |
| GET | `/pending` | próximos disparos + ejecuciones activas + `watching` (reglas con disparador de estado: estado, si está armada y lo que mide su sensor) + `wake: {at, error}` |
| GET | `/runs/{id}` | una ejecución (activa o del historial) |
| POST | `/runs/{id}/cancel` · `/cancel` | cancelar ejecución · la cuenta atrás actual, si no la acción rápida en curso, si no la próxima acción rápida (queda en el historial como `cancelled`) |
| POST | `/runs/{id}/postpone` · `/postpone` | posponer `{"delay": "10m"}` (10 min por defecto) · la cuenta atrás actual, si no la próxima acción rápida (se retrasa su disparador) |
| GET | `/history` | historial paginado |
| GET | `/capabilities` | informe doctor |
| GET | `/apps` | aplicaciones instaladas (id, nombre y traducciones, icono, Flatpak, categorías) con los ids de sus recetas |
| GET | `/recipes` | las recetas (`recipes.json`) |
| GET | `/stats?days=30` | uso y ahorro (M18): horas encendido/apagado/apagado por PowerClock, acciones, W, €/kWh (reales o típicos), kWh y dinero |
| GET · PATCH | `/settings` | ajustes cambiables en marcha (`tariff`, `watts`, `price_kwh`, `currency`; el resto → 422), guardados en `daemon.json` |
| PUT | `/settings/tariff` | atajo para `tariff` |
| GET | `/schema/rule` | JSON Schema (GUI y futuro asistente IA) |
| WS | `/events` | `warning_started`, `tick`, `cancelled`, `postponed`, `run_started`, `run_finished`, `rule_changed`, `wake_changed`, `power_action` (PowerClock va a apagar/suspender: cierra el periodo encendido de las estadísticas) |

Solo escucha en 127.0.0.1. El acceso remoto (fase 5) será opt-in. Sin `/docs` ni `/openapi.json`. El WebSocket acepta el token en la cabecera o en `?token=` (para clientes que no pueden poner cabeceras). Todas las rutas son `async` para ejecutarse en el bucle del motor.

`/quick` recibe `{"action" | "command" | "app" (con `args`), "in" | "at" | "when_idle" | "when_exits" | "when_cpu_below" | "when_net_below", "for", "mode", "warning", "dry_run", "wake", "wake_at"}`; `at` admite `"23:30"` (su próxima aparición), `"2026-09-24 07:30"` (hora local del demonio) o ISO con zona. `when_exits` es un nombre de proceso o un PID (solo dígitos); `for` solo vale con CPU/red (por defecto `5m`). Crea una regla `one_shot` con id `quick-…` que se borra sola al terminar (o al cancelarse); sin momento se ejecuta ya. `/cancel` elige la cuenta atrás en curso, luego la acción rápida en marcha, luego la próxima con hora y, si no hay, la última que espera una condición. Posponer una que espera una condición → 409 (no tiene hora que retrasar).

## 9. CLI
```
powerclock shutdown --in 30m
powerclock suspend --at 23:30 --wake 07:30
powerclock shutdown --when-idle 20m
powerclock shutdown --when-exits ffmpeg
powerclock reboot --when-cpu-below 10 --for 5m
powerclock shutdown --when-net-below 50 --for 5m        # descarga terminada
powerclock run --when-exits ffmpeg -- notify-send "Render terminado"
powerclock wake --at "2026-09-24 07:30"
powerclock run --at 03:00 --wake -- /home/pc/bin/backup.sh
powerclock launch org.kde.okular --at 09:00 -- --presentation ~/informe.pdf
powerclock launch vlc --recipe vlc.loop --in 1h -- ~/Música/Ambiente
powerclock apps [texto] | powerclock recipes [APP]
powerclock status | powerclock cancel | powerclock postpone 10m
powerclock rules list|show|add <f.json>|edit <id>|enable|disable|rm|export|import
powerclock doctor [--json] [--test-wake 120]
powerclock service install [--linger] | uninstall | status
powerclock helper install [--unattended] [--print] | uninstall [--print]
powerclock gui [--tray]
```
Los comandos rápidos crean reglas `one_shot` vía API (`powerclock shutdown|reboot|suspend|hibernate|hybrid-sleep|lock|logout|screen-off|run [--in|--at|--when-idle|--when-exits|--when-cpu-below|--when-net-below [--for]] [--force] [--warning] [--wake]`). Con `--when-*` muestran al momento lo que ve el sensor (p. ej. "ffmpeg is not running yet: waiting for it to start"); `powerclock status` las lista en **Watching** y `powerclock rules list` lo muestra en su columna "Next". Si el demonio no está activo, lo indican y sugieren `powerclock service install`. Opción global `--dry-run`. `powerclock service install --dry-run` instala el servicio en modo dry-run (pruebas).

## 10. GUI (PySide6)
Decisiones (M7):
- **Qt Widgets estándar, sin librerías exclusivas de KDE** (KDE Frameworks, Kirigami): el mismo código en cualquier escritorio y SO. Descartados por consumo o por encaje: Rust (Slint/iced; más ligero, pero rompe `pipx install` y duplica lenguaje), plasmoide (solo KDE), Tauri/Electron (motor web), Tkinter (sin bandeja, no viene en el Python de Ubuntu), GTK4 (sin bandeja).
- **Consumo**: solo la bandeja vive siempre (medido en el Latitude, Wayland: ~50 MB; con la ventana construida ~65 MB; 0 % CPU en reposo porque todo llega por `/events`, sin sondeo). La ventana se crea al abrirla y se destruye al cerrarla. En el VPS no se instala (`pipx install powerclock` sin `[gui]`).
- **Sin bandeja también funciona** (GNOME sin la extensión AppIndicator): la ventana es la app y la cuenta atrás sigue llegando por notificación.
- **Aspecto**: con el Qt de pip, estilo Fusion con la paleta, los iconos y el modo claro/oscuro del escritorio (en Plasma: colores e iconos Breeze; no el estilo de los controles ni la fuente). Modo nativo opcional en Linux, con el mismo código: `sudo apt install python3-pyside6.qtwidgets python3-pyside6.qtnetwork python3-qasync qt6-svg-plugins` y `pipx install --system-site-packages powerclock` (sin `[gui]`) → usa el Qt del sistema y se ve Breeze exacto.
- **Una sola instancia** (`QLocalServer`): lanzar `powerclock-gui` otra vez muestra la ventana de la que ya corre.
- **Nunca bloquea el hilo de Qt**: `qasync` integra asyncio en el bucle de Qt; las peticiones y el WebSocket son corrutinas. Los componentes solo necesitan un bucle asyncio en marcha, así los tests los ejercitan sin qasync (Qt `offscreen`).
- **Enlace con el demonio** (`gui/client.py`): `HttpApi` (httpx async; relee puerto y token tras un fallo, por si el demonio se reinició) y `DaemonLink`, que mantiene `/health` y `/pending` al día: los refresca con cada evento de `/events` (salvo `tick`), agrupando ráfagas, y repite la consulta si llega un evento mientras otra está en curso. Sin demonio: estado "sin conexión" y reintento con espera creciente (hasta 10 s). Con la ventana abierta, refresco cada 5 s para ver en vivo lo que miden los sensores.
- **Bandeja**: icono según estado (inactivo / programado / cuenta atrás / sin demonio); tooltip con lo próximo; menú con lo próximo, Cancelar, Posponer 10 min, **Ahora** (apagar, reiniciar, suspender… con su cuenta atrás de 60 s; bloquear y apagar pantalla, al momento), Programar…, Abrir PowerClock y cerrar el icono (las reglas siguen: las ejecuta el demonio).
- **Rápido** (estilo KShutdown): Acción (las de energía o "Ejecutar un programa") + Cuándo (ahora / fecha y hora / dentro de / inactividad / al terminar un programa, eligiéndolo entre los que corren / CPU baja / red baja, con su `for`) + cuenta atrás, forzar y "Encender también el equipo a las…" → Aceptar. Debajo, las acciones rápidas en espera con Cancelar y +10 min (este último solo si tienen hora o están en cuenta atrás).
- **Reglas**: tabla con activar/desactivar, cuándo y lo próximo (hora o lo que ve el sensor); nueva, editar, ejecutar ahora, borrar (pregunta), importar y exportar.
- **Editor de reglas** (`gui/editor.py` + `gui/forms.py`): los formularios se **generan del JSON Schema de cada modelo** (`models.model_json_schema`): un control por tipo de campo (duración, fecha local, hora, número con sus límites, lista de opciones, días, orden como línea de shell, entorno `K=V`, zona horaria, programa en marcha…), así el editor sigue a `models.py` sin formularios a mano. Pestañas Regla (disparador), Condiciones ("solo si se cumplen todas" + guardas "esperar mientras se cumpla alguna" con su reintento y límite), Pasos (ordenables), Opciones y JSON; las dos vistas se sincronizan al cambiar de pestaña. Condiciones complejas (`any`, anidadas) se editan como JSON dentro del formulario sin perderse. Se valida con los mismos modelos antes de enviar; editar una cuenta atrás no la reinicia.
- **Historial** (resultado, por qué se ejecutó, motivo y pasos de cada ejecución) y **Diagnóstico**: estado del demonio y botón "Iniciar el servicio" (si ya está instalado solo lo arranca; si no, pregunta y lo instala; en dry-run, como servicio dry-run), capacidades con cómo arreglarlas, próxima alarma, **instalar el ayudante** (muestra los comandos exactos y los ejecuta con `pkexec /bin/sh -c …`: una sola ventana de contraseña del sistema), **probar un despertar en 2 min** (pregunta, 10 s para apartar las manos, informa del resultado; en dry-run no hace nada) y las casillas de menú de aplicaciones y arranque con la sesión.
- **Diálogo de cuenta atrás** (`WindowStaysOnTopHint`; en Wayland el compositor decide): Cancelar (también con Esc) / Posponer 10 min. Se abre con `warning_started` o al arrancar la GUI a mitad de una cuenta atrás; se cierra con el fin de la ejecución, con un `/pending` pedido después de abrirse que ya no la tenga, o 3 s después de llegar a 0.
- **Menú y autoarranque** (`install/autostart.py` → `platform/linux/autostart.py`): `~/.local/share/applications/powerclock.desktop` (+ icono en `icons/hicolor/scalable/apps/powerclock.svg`) y `~/.config/autostart/powerclock-gui.desktop` con `--tray`, en carpetas del usuario, sin root.
- **Traducciones**: gettext. Los textos son los `_("…")` del código; `scripts/i18n.py update` los lleva a `src/powerclock/locale/<idioma>/LC_MESSAGES/powerclock.po` y `compile` genera el `.mo` (sin herramientas de gettext). Los tests fallan si un texto queda sin traducir, si una traducción pierde un `{marcador}` o el formato de rich, o si el `.mo` no está al día. Qt carga además sus propias traducciones (`qtbase_es`). Los tests corren en inglés (`LC_ALL=C.UTF-8`).

**Rediseño (decidido el 25-09-2026).** Propuesta completa en la página «Rediseño de PowerClock»; se aplica por fases (ROADMAP M9, M14, M15).
- **Identidad sobre el tema del sistema:** fondos, textos y controles siguen el tema del escritorio (claro/oscuro, accesibilidad); los colores propios solo marcan estados, iconos, la franja «Próximo» y el botón principal.
- **Paleta «noche y alba»** (AA ≥ 4,5:1 en claro y oscuro): Crepúsculo `#2F5FD0` programado y acción principal · Alba `#E8A33D` (texto `#8A4F00`) encender y despertar · Lavanda `#6A4FC7` vigilando una condición · Brasa `#B33A0A` cuenta atrás · Hoja `#177245` hecho · Grana `#B42323` falló · Pizarra `#586379` omitido o cancelado. El estado nunca va solo por color: siempre icono y texto.
- **Proporciones:** letra ×√φ por paso (11/14/18/23/29/37 px, base 14), espaciados Fibonacci (3, 5, 8, 13, 21, 34, 55, 89), ventana por defecto **987×610** (M14: rectángulo áureo de dos números de Fibonacci; 800×494 se quedaba corta con la franja «Próximo» encima del formulario) y Rápido repartido 61,8/38,2 %. La fuente, la del escritorio: `platform/linux/look.py` la lee de `kdeglobals` (o el valor por defecto de Plasma, Noto Sans 10) o de `gsettings` en GNOME, porque el Qt de pip no carga el tema de plataforma.
- **Aplicado en M14** (`gui/style.py` con los tokens, `gui/cards.py` con las piezas): colores de estado con variante oscura (todos ≥ 4,5:1, comprobado en un test) y símbolo (◷ ☀ ◉ ◴ ✔ ✘ ⊘); iconos de bandeja nuevos con dos estados más (vigilando, encenderá); franja «Próximo» con Posponer/Cancelar o Iniciar; acciones en botones y «Cuándo» segmentado (Ahora · A las · Dentro de · Cuando…) con la misma interfaz que un QComboBox (`currentData`, `findData`…); lo programado en tarjetas; anillo de 144 px en la cuenta atrás con «Cancelar» destacado; un único botón principal por pantalla. Reglas e Historial siguen en tabla (muchas filas y columnas: se comparan mejor así) pero con el estado en color, símbolo y texto; el id de la regla se pliega en el tooltip.
- **Tono:** tranquilo y preciso; frases cortas, verbos concretos, siempre qué va a pasar y cuándo; cada error dice qué pasó y cómo arreglarlo; ante lo que da miedo (apagar), recordar que hay aviso y que se puede cancelar.
- **Subtítulo:** «Programa el apagado, el encendido y tus tareas: a una hora exacta o cuando se cumplan las condiciones que elijas.» / *Schedule shutdown, wake-up and your tasks, at an exact time or when the conditions you choose are met.* Nombre corto: «Programador de apagado, encendido y tareas» / *Shutdown, wake-up and task scheduler*.
- **Vocabulario** (lo técnico queda en la CLI, en los nombres de campo de `rules.json` y en «Avanzado»):

| Concepto | Antes | ES | EN |
|---|---|---|---|
| Servicio | demonio | PowerClock en segundo plano | PowerClock in the background |
| Dry run | simulacro | modo prueba (no apaga nada de verdad) | test mode (nothing really turns off) |
| Helper | ayudante de encendido | permiso para encender el equipo | permission to turn the computer on |
| Unattended | desatendido | funcionar también con la sesión cerrada | also work when you are logged out |
| Trigger · conditions · guards · steps | disparador · condiciones · guardas · pasos | Cuándo · Solo si… · Esperar mientras… · Qué hará | When · Only if… · Wait while… · What it does |
| Warning | cuenta atrás | avisar antes | warn me first |
| Botón de Rápido | Aceptar | Programar apagado · Apagar ahora (según acción y momento) | Schedule shutdown · Shut down now |
| Lista de Rápido | En espera | Programado | Scheduled |
| idle (Rápido) | cuando nadie use el equipo durante | tras un tiempo sin usar el equipo | after a period without use |
| net_below (Rápido) | cuando el tráfico de red se mantenga por debajo de | cuando termine la descarga | when the download finishes |
| cpu_below (Rápido) | cuando el uso de CPU se mantenga por debajo de | cuando el equipo quede en reposo | when the computer goes quiet |
| wake_at | encender también el equipo a las | volver a encenderlo a las | turn it back on at |
| cause | por qué: a mano · programada · condición | origen: manual · horario · condición | source: manual · schedule · condition |
| Bandeja | cerrar el icono de la bandeja | ocultar el icono (PowerClock sigue funcionando) | hide the icon (PowerClock keeps working) |

## 11. Instalación
**Para todos (decidido el 24-09-2026): lanzador + Python.** El usuario medio descarga un archivo, le da doble clic, pone su contraseña una vez y queda todo hecho. Un único archivo que funcione en los tres SO no es viable (formatos de ejecutable distintos; un `.py` falla sin Python en Windows y macOS, y en Linux no puede mostrar ventanas sin Tkinter/Qt ni crear entornos sin `python3-venv`). Por eso:

1. **Lanzador mínimo por SO** (unos KB, sin Python): `installers/install-powerclock.sh` (Linux); `.command` (macOS, fase 4) y `.bat` (Windows, fase 3) seguirán el mismo guion. Hace solo esto:
   - si se abrió con doble clic (sin terminal), se vuelve a abrir en una terminal para que se vea el progreso (konsole, gnome-terminal, `x-terminal-emulator`, xterm…);
   - descarga **uv en una versión fija** a una carpeta propia (`~/.local/share/powerclock/uv/`), con curl, wget o, si no hay, el Python del sistema, y comprueba su **SHA-256 escrito en el propio lanzador** (no el publicado junto al archivo): una descarga manipulada se rechaza;
   - `uv tool install --python 3.13 "powerclock[gui]"` con Python gestionado por uv (`UV_PYTHON_PREFERENCE=only-managed`): no depende del Python del sistema (versión, `venv`, PEP 668). Los comandos quedan en `~/.local/bin`;
   - abre `powerclock-gui --setup`.
   Variables para pruebas: `POWERCLOCK_SOURCE` (instalar desde una carpeta, un wheel o una URL en vez de PyPI) y `POWERCLOCK_DRY_RUN=1` (el servicio se instala en dry-run).
2. **Ventana de instalación de PowerClock** (Python/Qt, común a los tres SO): casillas *Iniciar el icono de la bandeja con la sesión*, *Mostrar en el menú*, *Encender el equipo a una hora* (ayudante) y *También sin nadie con la sesión iniciada* (desatendido) → **Instalar** → una sola contraseña (polkit en Linux; UAC y la de macOS en sus fases) → listo, y abre PowerClock. Los pasos (`install/steps.py`) usan las fachadas por SO que ya existen (`service`, `helper`, `autostart`): entrada del menú e icono, servicio de usuario (y linger si es desatendido), arranque con la sesión y, con la única contraseña, el ayudante y sus reglas polkit. Todo en carpetas del usuario salvo el ayudante, así que **actualizar no pide contraseña** (salvo si cambia el ayudante). La CLI tiene lo mismo: `powerclock setup` y `powerclock uninstall`.
3. **Después**: bienvenida la primera vez que se abre la ventana; Diagnóstico muestra la versión, busca actualizaciones (PyPI) y, si PowerClock se instaló con el lanzador, actualiza con un clic (`uv tool upgrade`); **Desinstalar** quita servicio, menú, arranque con la sesión, ayudante (contraseña) y el propio programa, y conserva reglas e historial salvo que se pida lo contrario.

El lanzador descarga PowerClock de PyPI, así que requiere publicarlo allí (con Trusted Publishing desde GitHub). Para usuarios técnicos y servidores sigue valiendo pipx:
```
pipx install "powerclock[gui]"     # escritorio
pipx install powerclock            # servidor / VPS
powerclock setup                   # o, por partes: service install / helper install
```
- Linux: `~/.config/systemd/user/powerclock.service` (`ExecStart=<venv>/bin/powerclock-daemon --foreground`, `Restart=on-failure`; `systemctl --user enable --now`; linger opcional con `loginctl enable-linger`, sin sudo) · `~/.config/autostart/powerclock-gui.desktop` y la entrada del menú. Una parada por SIGTERM es limpia: guarda la marca de vida y conserva las acciones rápidas pendientes.
- Windows: tarea "al iniciar sesión" para el demonio · acceso directo de Inicio para la GUI.
- macOS: `~/Library/LaunchAgents/org.powerclock.daemon.plist` · helper como LaunchDaemon.
- Descartados: un `.run`/AppImage con todo dentro (≈100 MB y un paquete por SO que construir y probar; se podría añadir para instalar sin internet), Flatpak para la app (el sandbox tiene su propio espacio de procesos, ejecutaría los comandos de `run` dentro del sandbox y no puede instalar el helper, polkit ni el servicio), Snap (confinamiento `classic`).
- Paquetes de distribución (`.deb`/`.rpm`): opcionales y más adelante (ROADMAP, "Empaquetado"). Para dejarlo fácil: el helper debe poder vivir también en `/usr/libexec/powerclock-helper` y `powerclock service install` debe limitarse a activar un `powerclock.service` que ya instale un paquete.

## 12. Seguridad
- Demonio sin privilegios; helper con lista blanca y validación estricta; ejecutado con el Python del sistema, nunca desde el venv.
- API solo en localhost + token 0600.
- `run` con `shell=False` por defecto.
- Cuenta atrás cancelable antes de acciones de energía; `graceful` por defecto; `force` solo explícito.
- Todo disparo, skip o posposición queda en el historial con su motivo.

## 13. Estructura del repositorio
```
KSHUTDOWN-EVOLUTION/
├── CLAUDE.md  README.md  pyproject.toml  .gitignore
├── docs/                ARCHITECTURE.md  ROADMAP.md
├── examples/            reglas de ejemplo (*.json)
├── src/powerclock/
│   ├── models.py        # Rule, Trigger*, Predicate*, Action*, parse_duration
│   ├── config.py        # rutas platformdirs (POWERCLOCK_HOME), daemon.json, token, escritura atómica
│   ├── timeparse.py     # "23:30" / "2026-09-24 07:30" → instante
│   ├── doctor.py        # powerclock doctor: informe del backend + comprobaciones genéricas
│   ├── i18n.py          # textos traducibles (gettext)
│   ├── labels.py        # nombres traducidos (tipos, campos, estados) y motivos del motor en palabras
│   ├── recipes.py       # recetas por aplicación (recipes.json)
│   ├── locale/          # es/LC_MESSAGES/powerclock.po + powerclock.mo (scripts/i18n.py)
│   ├── connection.py    # dónde está el API del demonio, su token y sus errores (CLI y GUI)
│   ├── engine/          # core.py (Engine) clock.py scheduler.py watcher.py evaluator.py executor.py runs.py processes.py wake.py variables.py push.py sun.py holidays.py tariff.py calendar.py wol.py savings.py
│   ├── sensors/         # base.py (SensorReader, Readings) system.py (psutil + SystemReadings) fake.py registry.py (SensorHub)
│   ├── platform/        # __init__.py (get_backend) base.py fake.py dryrun.py
│   │   ├── linux/       # backend.py logind.py idle.py wayland.py desktop.py notify.py network.py dbus.py commands.py host.py capabilities.py service.py (systemd) helper.py autostart.py (.desktop) apps.py (catálogo de .desktop y su orden) session.py (gestor de usuario de systemd: entorno, sesión, unidades) kwin.py (colocar ventanas)
│   │   ├── windows/     # fase 3
│   │   └── macos/       # fase 4
│   ├── helper/          # powerclock_helper_linux.py org.powerclock.helper.policy 50-powerclock-unattended.rules.in (plantilla por usuario)
│   ├── daemon/          # main.py (powerclock-daemon) core.py (Daemon) api.py store.py (reglas + historial) events.py
│   ├── cli/             # main.py client.py format.py
│   ├── install/         # service.py autostart.py helper.py (fachadas por SO) steps.py (instalar/desinstalar) program.py (versión, actualizar)
│   └── gui/             # app.py (powerclock-gui) controller.py client.py (HttpApi, DaemonLink) tray.py window.py quick.py rules.py editor.py forms.py history.py diagnostics.py maintenance.py countdown.py setup.py (ventana de instalación) welcome.py summary.py widgets.py energy.py tasks.py single.py icons.py icons/*.svg
├── installers/          # install-powerclock.sh (lanzador de Linux; .command y .bat en las fases 3 y 4)
├── scripts/             # i18n.py (extraer y compilar traducciones) screenshots.py (capturas del README, Qt offscreen y backend falso)
└── tests/               # unit/ (unit/gui: Qt offscreen) + real/ (@pytest.mark.real, excluidos por defecto)
```

## 14. Límites conocidos y decisiones
- El encendido desde S5 no está garantizado (BIOS); en portátil, con AC.
- En Wayland, idle vía D-Bus del escritorio; `xprintidle` solo en X11.
- Nombre: **PowerClock** — *Shutdown, wake-up and task scheduler* (decidido el 24-09-2026; nombre de trabajo anterior: "KShutdown Evolution", `kse`). Libre en PyPI y sin otra app con ese nombre; descartados por existir ya apps que hacen lo mismo: Shutdown Scheduler, PowerPilot, PowerTask, AutoShutdown, PowerWise, PowerCron, PowerWake. Paquete, comandos (`powerclock`, `powerclock-daemon`, `powerclock-gui`), carpetas, servicio (`powerclock.service`) y ayudante (`powerclock-helper`, acción polkit `org.powerclock.helper.wake`) llevan el nombre. Las variables de entorno son `POWERCLOCK_*`; las antiguas `KSE_*` se siguen aceptando (y si cualquiera de las dos pide dry-run, es dry-run), para que una costumbre nunca haga que se apague el equipo de verdad. No usar "KShutdown" (es un proyecto ajeno): solo se cita como inspiración de la pestaña Rápido.
