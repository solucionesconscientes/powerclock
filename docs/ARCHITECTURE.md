# Arquitectura — KShutdown Evolution (nombre de trabajo · paquete `kse`)

## 1. Objetivo y principios
App multiplataforma (Linux → Windows → macOS) para automatizar energía y tareas: apagar, suspender, hibernar, **encender/despertar**, y ejecutar programas o scripts por hora o por condición. Las reglas son persistentes y funcionan aunque la GUI esté cerrada.

1. Núcleo común; código de SO aislado en `platform/<os>/`.
2. Demonio de usuario persistente; GUI, CLI y control remoto son clientes.
3. Privilegios mínimos: el demonio NUNCA corre como root; solo un helper diminuto con operaciones en lista blanca.
4. Seguro por defecto: cuenta atrás cancelable antes de acciones de energía, modo graceful, dry-run, guardas anti pérdida de datos.
5. Honesto con el hardware: `kse doctor` detecta qué funciona, qué no y cómo arreglarlo.
6. Sencillo para el 80 %: modo rápido estilo KShutdown; reglas avanzadas para el resto.

## 2. Componentes
```
   ┌──────────┐   ┌──────────┐   ┌────────────────────┐
   │ kse-gui  │   │ kse CLI  │   │ remoto (fase 5)    │
   │ PySide6  │   │ typer    │   │ Telegram / web     │
   └────┬─────┘   └────┬─────┘   └─────────┬──────────┘
        └──── HTTP + WebSocket 127.0.0.1 + token ────┘
                          │
             ┌────────────▼────────────┐
             │       kse-daemon         │  usuario · asyncio
             │ API · Store · Scheduler  │
             │ Sensors · Evaluator      │
             │ Executor · WakePlanner   │
             └────────────┬────────────┘
                          │  PlatformBackend (ABC)
     ┌──────────────┬─────┴────────┬──────────────┐
   linux/        windows/        macos/         fake/
 logind D-Bus   Win32/schtasks  pmset/osascript  (tests)
     │                              │
 kse-helper (root, polkit)      kse-helper (LaunchDaemon)
 solo: wake set/clear/get       solo: pmset schedule
```

| Componente | Qué es |
|---|---|
| `kse-daemon` | Servicio de usuario (systemd --user / tarea al iniciar sesión / LaunchAgent). Tiene todo el estado. |
| `kse` | CLI: acciones rápidas, gestión de reglas, `doctor`, instalación de servicio y helper. |
| `kse-gui` | Bandeja + ventana. Cliente del API. Muestra la cuenta atrás. |
| `kse-helper` | Script stdlib que corre como root. Solo `wake-set <epoch>`, `wake-clear`, `wake-get`. |

## 3. Stack y dependencias permitidas
- Python ≥ 3.11 · `pyproject.toml` + hatchling · layout `src/` · desarrollo con `uv`.
- `pydantic` v2 (modelos, validación, JSON Schema) · `fastapi` + `uvicorn` (API local + WS) · `httpx` (cliente) · `typer` + `rich` (CLI) · `psutil` (CPU, red, procesos, batería, usuarios) · `croniter` (recurrencias) · `platformdirs` (rutas) · `websockets` (servidor WS de uvicorn para `/events` y cliente WS de la CLI; `httpx` no habla WebSocket).
- Solo Linux: `dbus-fast` (logind, ScreenSaver, MPRIS, notificaciones) → `dbus-fast; sys_platform == "linux"`.
- Solo Windows (fase 3): `pywin32`.
- Extra `[gui]`: `PySide6`, `qasync`. La GUI usa `QtWebSockets` (incluido en PySide6) para `/events`.
- Dev (grupo `dev` de uv; no es un extra publicado): `pytest`, `pytest-asyncio`, `ruff`, `time-machine`.
- Entry points: `kse`, `kse-daemon`, `kse-gui`.
- Licencia provisional: GPL-3.0-or-later (decidir antes de publicar).

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
    {"type": "notify", "title": "KSE", "body": "Backup terminado"},
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

**Disparadores** — MVP: `at`, `countdown`, `cron`, `idle`, `process_exit`, `cpu_below`, `net_below`, `battery`, `power_source`, `startup` (arranque del demonio o tras despertar), `manual`. Más adelante: `file`, `wifi_ssid`, `usb`, `temperature`, `webhook`, `telegram`, `calendar`, `sunrise`/`sunset`.
Los disparadores de estado llevan `for` (condición sostenida N tiempo), p. ej. `{"type":"cpu_below","percent":10,"for":"5m"}`.

**Predicados** (para conditions/guards/wait_until): `process_running`, `power_source`, `battery`, `idle`, `cpu_below`, `net_below`, `media_playing`, `ssh_session`, `time_window`, `weekday`, `wifi_ssid`. Árbol lógico: `all` / `any` / `not`.

**Acciones**: `power` (`shutdown|reboot|suspend|hibernate|hybrid_sleep|lock|logout|screen_off`, `mode: graceful|force`) · `run` (`cmd` lista, `cwd`, `env`, `shell` false por defecto, `timeout`, `wait`) · `open` (archivo/URL) · `close_app` (término limpio y kill tras timeout) · `notify` · `wait` · `wait_until` · `set_wake` (absoluto/relativo) · más adelante `webhook`, `telegram`.

**Detalles fijados en M1** (referencia completa: el JSON Schema de `GET /schema/rule`, generado desde `src/kse/models.py`):
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

**Almacenamiento** (`platformdirs`; `KSE_HOME` lo concentra todo en un directorio, útil para tests y pruebas aisladas): `rules.json` en user_config_dir (`{"version": 1, "rules": [...]}`, editable a mano, validado al cargar, escritura atómica 0600, recarga en caliente cada 2 s) · `history.sqlite` en user_data_dir (0600; también guarda la última marca de vida del demonio, cada 60 s, para detectar disparos perdidos mientras estuvo parado) · `daemon.json` (`port`, `dry_run`, `log_level`) · `api.token` (0600).
- Si `rules.json` tiene **cualquier** error (JSON roto, regla inválida, id duplicado): al arrancar se cargan las reglas válidas; en una recarga siguen funcionando las anteriores; en ambos casos el demonio **no escribe** el archivo hasta que se corrija (las escrituras del API responden 409), para no perder nunca una edición a mano. Los errores aparecen en `/health` y `kse status`.

## 5. Motor
- **Scheduler**: bucle asyncio. Los disparadores de tiempo calculan `next_fire` (croniter + zoneinfo). Duerme hasta el más cercano, como mucho 30 s, para resincronizar tras suspensiones, saltos de reloj y cambios de horario.
- **Sensores bajo demanda**: solo se sondean los que usa alguna regla activa (idle 5 s, CPU/red 5 s con media móvil, procesos 3 s).
- **Evaluator**: evalúa conditions/guards/wait_until. `time_window` y `weekday` los resuelve él con el reloj y la zona de la regla; el resto se lo pregunta a un `SensorReader` (`sensors/base.py`), que es quien aplica `for` con su historial (M6).
- **Executor**: cada ejecución es un `Run` (id, estado: `warning|running|waiting|done|failed|cancelled|skipped|postponed`, pasos con su resultado y motivo), cancelable por API. Solo una acción de energía activa a la vez (la segunda espera en `waiting`), así "la cuenta atrás actual" está siempre bien definida. Durante la cuenta atrás, notificación con botones Cancelar / Posponer 10 min. `notify` es de mejor esfuerzo: sin escritorio queda como skip, no como fallo. `run` guarda los últimos 4000 caracteres de la salida; al cancelar o agotar `timeout`, el comando recibe SIGTERM y, 5 s después, SIGKILL.
- **Reloj**: todo el motor lee la hora y duerme a través de `Clock` (`engine/clock.py`); los tests usan `FakeClock`, que distingue el reloj de pared (`jump`, como una suspensión) del monótono (`advance`).
- **Cron y cambio de hora**: cron sigue la hora local de la regla. En el hueco de primavera la ejecución se desplaza (02:30 → 03:30); en la hora repetida de otoño cada hora local se ejecuta una sola vez, en su primera aparición.
- **Dry-run (kill-switch)**: con `KSE_DRY_RUN=1` se usa el backend **real** envuelto en `DryRunPlatform`: las lecturas (inactividad, multimedia, capacidades…) son reales, pero `power`, `wake_set` y `wake_clear` solo se registran. `dry_run: true` en una regla hace lo mismo con sus acciones `power`. `run`, `open`, `close_app` y `notify` sí se ejecutan.
- **Resume/arranque**: tras `after_resume` (PrepareForSleep(false)) el scheduler revisa al momento; sin eventos de energía lo nota en ≤ 30 s. Al arrancar, el demonio pasa a cada regla la última vez que se revisó (`since`) para detectar lo perdido y aplicar `on_missed`.
- **Reglas que cambia el motor**: armar un `countdown` (al crear o reactivar la regla) y desactivar una `one_shot` tras dispararse emiten `rule_changed` para que el demonio lo guarde.

## 6. Encendido/despertar — WakePlanner (diferenciador)
- El RTC guarda UNA sola alarma. WakePlanner (`engine/wake.py`) calcula el próximo disparo de las reglas activas con `wake: true`, le resta un margen (120 s, para que el demonio esté listo), lo redondea a segundos (nunca a menos de 10 s vista) y lo programa. Las peticiones sueltas (`kse wake --at`, `--wake` de las acciones rápidas, la acción `set_wake`) se convierten en reglas `quick-…` de un solo uso con `wake: true` y un `notify`, así solo hay una fuente de verdad.
- Nunca retrasa ni borra una alarma **ajena** que llegue antes (p. ej. la de `kse doctor --test-wake` o un `rtcwake` a mano): solo borra la suya. Al parar el demonio la alarma **se queda** (tiene que encender el equipo). Los errores (helper sin instalar, sin permiso) quedan en `/pending` → `wake.error` y en `kse status`, y se reintentan en el siguiente cambio.
- Se reprograma en tres momentos: (a) al cambiar reglas, (b) tras cada disparo, (c) justo antes de apagar/suspender. Para (c), el demonio toma un inhibidor logind `delay` (`shutdown:sleep`) **solo mientras hay una alarma que mantener**; en `PrepareForShutdown`/`PrepareForSleep(true)` reescribe la alarma y libera el inhibidor. Así se cubren también los apagados manuales del usuario. Tras reanudar, vuelve a leer la alarma (puede haberse consumido) y programa la siguiente.
- Lectura: el backend lee `/sys/class/rtc/rtc0/wakealarm` directamente (es legible sin privilegios), convirtiendo si el RTC va en hora local. Escritura: `pkexec kse-helper wake-set|wake-clear`; códigos 126/127 de pkexec → `NotSupported` (sin permiso) con la pista de `--unattended`.
- `kse doctor --test-wake N` (60–3600 s): tras confirmación explícita y 10 s para apartar las manos (un touchpad o un pointing stick pueden despertarlo), programa la alarma (si falla, **no suspende**), suspende y, al reanudar, dice si despertó sola (`ok`), antes de tiempo (¿a mano?), tarde o si no llegó a suspender, y **qué lo despertó** si el SO lo dice (`wakeup_source()`: en Linux `/sys/power/pm_wakeup_irq` + `/proc/interrupts` + nombres de `/sys/class/input`; solo se muestra si cambió durante la prueba, porque puede quedarse viejo). En dry-run no hace nada.
- Primera prueba en el Latitude 5480 (23-09-2026): suspensión S3 correcta, pero despertó a los ~11 s por la IRQ 51 = touchpad Alps `DLL07A7:01` / DualPoint Stick (wakeup habilitado), no por el RTC. De ahí la cuenta atrás y el diagnóstico anteriores.
- Segunda prueba (24-09-2026, con las manos fuera): **despertó sola desde S3 a los 2 s de la alarma** (alarma 11:20:03, reanudación 11:20:05). El despertar desde suspensión funciona en el Latitude 5480.
- Tercera prueba (24-09-2026, **desde S5**, con AC): `kse-helper wake-set` para las 11:31:06, apagado a las 11:26:12 y **se encendió sola**; el kernel leyó el RTC a las 11:31:20 (≈14 s de POST y arranque). El encendido programado desde apagado funciona en el Latitude 5480 con la BIOS de serie.
- Linux: el helper usa `rtcwake -m no -t <epoch>`, que respeta RTC en UTC o localtime según `/etc/adjtime`; si falla, recurre a `/sys/class/rtc/rtc0/wakealarm`: escribe `0` y después el valor **relativo** `+<segundos>`. Un valor absoluto el kernel lo interpreta en la hora del RTC, que puede ir en hora local (arranque dual con Windows) y desplazaría la alarma 1–2 h; el relativo no depende de eso. Para consultar: `rtcwake -m show`. Para borrar: `rtcwake -m disable`.
- **Modo desatendido** (encender → ejecutar → apagar sin iniciar sesión): el servicio de usuario necesita `loginctl enable-linger <usuario>`, y sin sesión activa `allow_active` no se aplica. Por eso hace falta una regla polkit opcional (`50-kse-unattended.rules`) que conceda a ese usuario las acciones `org.freedesktop.login1.power-off/reboot/suspend/hibernate` (y sus variantes `-multiple-sessions`) **y la acción del helper `org.kse.helper.wake`**; sin esta última, el WakePlanner no podría programar el siguiente despertar y la cadena se cortaría tras el primero. Lo instalan `kse service install --linger` y `kse helper install --unattended`.
- Windows (fase 3): tarea programada con `WakeToRun` que ejecuta `kse wake-hook`. `doctor` comprueba los temporizadores de reactivación y Modern Standby (`powercfg /a`).
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
    async def subscribe_power_events(self, callback) -> None: ...   # before_sleep, after_resume, before_shutdown
    def inhibit_delay(self) -> AbstractAsyncContextManager: ...
    async def capabilities(self) -> list[Capability]: ...
```
- `Capability(id, supported: bool, detail: str, fix_hint: str | None)`.
- Solo `power` y `capabilities` son obligatorios; cualquier otro método que un backend no implemente lanza `NotSupported(feature, detail, fix_hint)`.
- `notify(title, body, actions)`: `actions` es `{clave: etiqueta}`. Sin `actions` vuelve enseguida; con `actions` espera a que el usuario elija una (devuelve su clave) o cierre la notificación (`None`), así que se lanza como tarea y se cancela cuando deja de hacer falta.
- `subscribe_power_events` recibe un `PowerEvent` (`before_sleep`, `after_resume`, `before_shutdown`).
- Lo genérico (CPU, red, procesos, batería, usuarios) va en `sensors/` con psutil, no en el backend.
- `FakePlatform`: en memoria, registra todas las llamadas. Se usa en TODOS los tests (el dry-run usa el backend real, ver §5). Se selecciona con `KSE_BACKEND=fake`.

**Linux (detalle)**
- Energía: logind `org.freedesktop.login1.Manager` → `CanPowerOff/CanSuspend/CanHibernate…` y luego `PowerOff/Reboot/Suspend/Hibernate/HybridSleep(interactive=true)`. Apagar/reiniciar comprueban `Can*` **antes** de pedírselo al escritorio; `no`/`na` → `NotSupported`.
- Graceful: en KDE, `org.kde.Shutdown` (`logoutAndShutdown`, `logoutAndReboot`, `logout`) para que las apps pidan guardar; en GNOME, `gnome-session-quit`. Verificar por introspección en tiempo de ejecución y recurrir a logind si no existe.
- Bloquear y cerrar sesión forzado: `Lock`/`Terminate` sobre la sesión gráfica del usuario (propiedad `Display` de `login1.User`, que funciona también desde un servicio systemd de usuario). Apagar pantalla: `kscreen-doctor --dpms off` (KDE) → `PowerSaveMode` de `org.gnome.Mutter.DisplayConfig` (GNOME) → `xset dpms force off` (X11).
- Idle (debe funcionar en Wayland), estrategias en cadena: **Wayland `ext-idle-notify-v1`** (cliente mínimo en Python puro, `linux/wayland.py`; v2 mide solo teclado/ratón; granularidad 5 s) → `org.gnome.Mutter.IdleMonitor.GetIdletime` (GNOME, ms) → logind `IdleHint`/`IdleSinceHint` (solo tan fiable como el escritorio que lo marque) → `xprintidle` (X11). `org.freedesktop.ScreenSaver.GetSessionIdleTime` queda **fuera**: en KDE Wayland responde "not supported on this platform" (verificado en M3) y en X11 sus unidades no son fiables para decidir una suspensión.
- Multimedia: MPRIS (`PlaybackStatus == "Playing"`); sin bus de sesión → desconocido. Notificaciones: `org.freedesktop.Notifications`; con botones, urgencia crítica y sin caducidad, se espera `ActionInvoked`/`NotificationClosed` y se cierra con `CloseNotification` si se cancela. Wi-Fi: `PrimaryConnection` de NetworkManager → `SpecificObject` → `Ssid`.
- Entorno de un servicio systemd de usuario: puede faltar `DBUS_SESSION_BUS_ADDRESS` (se usa `$XDG_RUNTIME_DIR/bus`) y `WAYLAND_DISPLAY` (se busca `wayland-*` en el directorio de ejecución y se pasa a `kscreen-doctor`/`xdg-open`).
- Zona horaria (`timezone()`): `$TZ` → enlace `/etc/localtime` → `/etc/timezone` → contenido de `/etc/localtime` → UTC.
- Eventos: señales `PrepareForSleep`/`PrepareForShutdown`; inhibidor `Inhibit("shutdown:sleep", "kse", motivo, "delay")`.
- Helper: `/usr/local/libexec/kse-helper` (root:root 0755, `#!/usr/bin/python3` del sistema, solo stdlib) + `/usr/share/polkit-1/actions/org.kse.helper.policy` (acción `org.kse.helper.wake`) con `allow_active=yes` y la anotación `org.freedesktop.policykit.exec.path` → `pkexec /usr/local/libexec/kse-helper wake-set <epoch>` sin contraseña en sesión activa. Valida que el epoch sea solo dígitos, al menos 5 s en el futuro y como mucho 366 días. Nunca ejecuta nada arbitrario: `rtcwake` con ruta absoluta y entorno limpio. `wake-get` imprime el epoch UTC o `none`.
- `kse helper install [--unattended] [--print]` muestra los comandos `sudo install -D -o root -g root -m 0755|0644 …` exactos y solo los ejecuta si el usuario responde que sí; con `--unattended` genera la regla para ese usuario en su directorio de datos. `uninstall` borra la alarma y los tres archivos. `doctor` comprueba que el helper instalado coincide con el de esta versión, pregunta a polkit con `pkcheck --action-id org.kse.helper.wake --process <pid>` si este proceso puede programar la alarma sin contraseña (sin ejecutar nada como root), y muestra la alarma actual.
- `doctor` informa de: RTC presente, helper instalado, Can*, hibernación configurada (swap/resume), AC/batería, sesión Wayland/X11, escritorio, fabricante/modelo (`/sys/class/dmi/id/`) con pista de BIOS (p. ej. Dell: *Power Management → Auto On Time*), linger activo, RTC UTC/local.

## 8. API local
`http://127.0.0.1:<puerto>` (por defecto 47831, configurable) · cabecera `Authorization: Bearer <token>`.

| Método | Ruta | Uso |
|---|---|---|
| GET | `/health` | versión, uptime, backend |
| GET · POST | `/rules` | listar · crear |
| GET · PUT · DELETE | `/rules/{id}` | ver · editar · borrar |
| POST | `/rules/{id}/enable` · `/disable` · `/run` | |
| POST | `/quick` | acción rápida estilo KShutdown → regla `one_shot` |
| POST | `/wake` | `{"at": "07:30"}` → regla de despertar de un solo uso |
| GET | `/pending` | próximos disparos + ejecuciones activas + `wake: {at, error}` |
| GET | `/runs/{id}` | una ejecución (activa o del historial) |
| POST | `/runs/{id}/cancel` · `/cancel` | cancelar ejecución · la cuenta atrás actual, si no la acción rápida en curso, si no la próxima acción rápida (queda en el historial como `cancelled`) |
| POST | `/runs/{id}/postpone` · `/postpone` | posponer `{"delay": "10m"}` (10 min por defecto) · la cuenta atrás actual, si no la próxima acción rápida (se retrasa su disparador) |
| GET | `/history` | historial paginado |
| GET | `/capabilities` | informe doctor |
| GET | `/schema/rule` | JSON Schema (GUI y futuro asistente IA) |
| WS | `/events` | `warning_started`, `tick`, `cancelled`, `postponed`, `run_started`, `run_finished`, `rule_changed`, `wake_changed` |

Solo escucha en 127.0.0.1. El acceso remoto (fase 5) será opt-in. Sin `/docs` ni `/openapi.json`. El WebSocket acepta el token en la cabecera o en `?token=` (para clientes que no pueden poner cabeceras). Todas las rutas son `async` para ejecutarse en el bucle del motor.

`/quick` recibe `{"action" | "command", "in" | "at", "mode", "warning", "dry_run"}`; `at` admite `"23:30"` (su próxima aparición), `"2026-09-24 07:30"` (hora local del demonio) o ISO con zona. Crea una regla `one_shot` con id `quick-…` que se borra sola al terminar (o al cancelarse); sin `in`/`at` se ejecuta ya.

## 9. CLI
```
kse shutdown --in 30m
kse suspend --at 23:30 --wake 07:30
kse shutdown --when-idle 20m
kse shutdown --when-exits ffmpeg
kse reboot --when-cpu-below 10 --for 5m
kse shutdown --when-net-below 50 --for 5m        # descarga terminada
kse wake --at "2026-09-24 07:30"
kse run --at 03:00 --wake -- /home/pc/bin/backup.sh
kse status | kse cancel | kse postpone 10m
kse rules list|show|add <f.json>|edit <id>|enable|disable|rm|export|import
kse doctor [--json] [--test-wake 120]
kse service install [--linger] | uninstall | status
kse helper install [--unattended] [--print] | uninstall [--print]
kse gui
```
Los comandos rápidos crean reglas `one_shot` vía API (`kse shutdown|reboot|suspend|hibernate|hybrid-sleep|lock|logout|screen-off [--in|--at] [--force] [--warning]`). Si el demonio no está activo, lo indican y sugieren `kse service install`. Opción global `--dry-run`. `kse service install --dry-run` instala el servicio en modo dry-run (pruebas). `--wake` (M5) y `--when-*` (M6) llegan en sus hitos.

## 10. GUI (PySide6)
- **Bandeja**: icono según estado (inactivo / programado / cuenta atrás); menú con acciones rápidas, próxima acción, cancelar y abrir.
- **Rápido** (estilo KShutdown): Acción + Cuándo (a la hora / dentro de / inactividad / al terminar un proceso / CPU baja / descarga terminada) + casilla "Encender a las …" → Aceptar.
- **Reglas**: lista con activar/desactivar, editor por formularios (disparador, condiciones, guardas, pasos) y vista JSON.
- **Historial** y **Diagnóstico** (capabilities con botones "Instalar helper" y "Probar despertar en 2 min").
- **Diálogo de cuenta atrás** siempre encima: Cancelar / Posponer 10 min (vía WS).
- Autoarranque; i18n es/en.

## 11. Instalación
```
pipx install "kse[gui]"     # escritorio
pipx install kse            # servidor / VPS
kse service install         # servicio de usuario + autoarranque
kse helper install          # opcional: encender/despertar (sudo una vez)
```
- Linux: `~/.config/systemd/user/kse.service` (`ExecStart=<venv>/bin/kse-daemon --foreground`, `Restart=on-failure`; `systemctl --user enable --now`; linger opcional con `loginctl enable-linger`, sin sudo) · `~/.config/autostart/kse-gui.desktop` (M7). Una parada por SIGTERM es limpia: guarda la marca de vida y conserva las acciones rápidas pendientes.
- Windows: tarea "al iniciar sesión" para el demonio · acceso directo de Inicio para la GUI.
- macOS: `~/Library/LaunchAgents/org.kse.daemon.plist` · helper como LaunchDaemon.
- Flatpak descartado: el sandbox impide logind de sistema, polkit y el helper.

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
├── src/kse/
│   ├── models.py        # Rule, Trigger*, Predicate*, Action*, parse_duration
│   ├── config.py        # rutas platformdirs (KSE_HOME), daemon.json, token, escritura atómica
│   ├── timeparse.py     # "23:30" / "2026-09-24 07:30" → instante
│   ├── doctor.py        # kse doctor: informe del backend + comprobaciones genéricas
│   ├── i18n.py          # textos traducibles (catálogos es/en en M7)
│   ├── engine/          # core.py (Engine) clock.py scheduler.py evaluator.py executor.py runs.py processes.py wake.py (M5)
│   ├── sensors/         # base.py (SensorReader) system.py (psutil) fake.py registry.py (M6)
│   ├── platform/        # __init__.py (get_backend) base.py fake.py dryrun.py
│   │   ├── linux/       # backend.py logind.py idle.py wayland.py desktop.py notify.py network.py dbus.py commands.py host.py capabilities.py service.py (systemd)
│   │   ├── windows/     # fase 3
│   │   └── macos/       # fase 4
│   ├── helper/          # kse_helper_linux.py org.kse.helper.policy 50-kse-unattended.rules.in (plantilla por usuario)
│   ├── daemon/          # main.py (kse-daemon) core.py (Daemon) api.py store.py (reglas + historial) events.py
│   ├── cli/             # main.py client.py format.py
│   ├── install/         # service.py (fachada por SO) autostart.py helper.py
│   └── gui/             # app.py tray.py quick.py rules.py countdown.py doctor.py client.py
└── tests/               # unit/ + real/ (@pytest.mark.real, excluidos por defecto)
```

## 14. Límites conocidos y decisiones
- El encendido desde S5 no está garantizado (BIOS); en portátil, con AC.
- En Wayland, idle vía D-Bus del escritorio; `xprintidle` solo en X11.
- Nombre público: no usar "KShutdown" (es un proyecto ajeno). `kse` es provisional; comprobar disponibilidad en PyPI antes de publicar.
