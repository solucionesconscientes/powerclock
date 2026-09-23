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
 logind D-Bus   Win32/schtasks  pmset/osascript  (tests, dry-run)
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
- `on_missed`: `skip` | `run_once` (el instante pasó con el equipo apagado).

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

**Almacenamiento** (`platformdirs`): `rules.json` en user_config_dir (editable a mano, validado al cargar, escritura atómica, recarga en caliente) · `history.sqlite` en user_data_dir · `daemon.json` (puerto y ajustes) · `api.token` (permisos 0600).

## 5. Motor
- **Scheduler**: bucle asyncio. Los disparadores de tiempo calculan `next_fire` (croniter + zoneinfo). Duerme hasta el más cercano, como mucho 30 s, para resincronizar tras suspensiones, saltos de reloj y cambios de horario.
- **Sensores bajo demanda**: solo se sondean los que usa alguna regla activa (idle 5 s, CPU/red 5 s con media móvil, procesos 3 s).
- **Evaluator**: evalúa conditions/guards contra un snapshot de sensores.
- **Executor**: cada ejecución es un `Run` (id, estado: `warning|running|waiting|done|failed|cancelled|skipped|postponed`), cancelable por API. Solo una acción de energía activa a la vez.
- **Dry-run (kill-switch)**: con `KSE_DRY_RUN=1` se usa el backend **real** envuelto en `DryRunPlatform`: las lecturas (inactividad, multimedia, capacidades…) son reales, pero `power`, `wake_set` y `wake_clear` solo se registran. `dry_run: true` en una regla hace lo mismo con sus acciones `power`. `run`, `open`, `close_app` y `notify` sí se ejecutan.
- **Resume/arranque**: detecta la reanudación (PrepareForSleep(false) o salto de reloj), reevalúa y aplica `on_missed`.

## 6. Encendido/despertar — WakePlanner (diferenciador)
- El RTC guarda UNA sola alarma. WakePlanner calcula el instante más próximo entre las reglas con `wake: true` y los `set_wake`, le resta un margen (120 s por defecto, para que el demonio esté listo) y lo programa.
- Se reprograma en tres momentos: (a) al cambiar reglas, (b) tras cada disparo, (c) justo antes de apagar/suspender. Para (c), el demonio toma un inhibidor logind `delay` (`shutdown:sleep`); en `PrepareForShutdown`/`PrepareForSleep(true)` reescribe la alarma y libera el inhibidor. Así se cubren también los apagados manuales del usuario.
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
- `notify` sin `actions` vuelve enseguida; con `actions` espera a que el usuario elija una (devuelve su clave) o cierre la notificación (`None`), así que se lanza como tarea y se cancela cuando deja de hacer falta.
- `subscribe_power_events` recibe un `PowerEvent` (`before_sleep`, `after_resume`, `before_shutdown`).
- Lo genérico (CPU, red, procesos, batería, usuarios) va en `sensors/` con psutil, no en el backend.
- `FakePlatform`: en memoria, registra todas las llamadas. Se usa en TODOS los tests (el dry-run usa el backend real, ver §5). Se selecciona con `KSE_BACKEND=fake`.

**Linux (detalle)**
- Energía: logind `org.freedesktop.login1.Manager` → `CanPowerOff/CanSuspend/CanHibernate…` y luego `PowerOff/Reboot/Suspend/Hibernate/HybridSleep(interactive=true)`.
- Graceful: en KDE, `org.kde.Shutdown` (`logoutAndShutdown`, `logoutAndReboot`, `logout`) para que las apps pidan guardar; en GNOME, `gnome-session-quit`. Verificar por introspección en tiempo de ejecución y recurrir a logind si no existe.
- Bloquear: `loginctl lock-session`. Apagar pantalla: `kscreen-doctor --dpms off` (KDE) con alternativas.
- Idle (debe funcionar en Wayland), estrategias en cadena: `org.freedesktop.ScreenSaver.GetSessionIdleTime` (KDE) → `org.gnome.Mutter.IdleMonitor.GetIdletime` (GNOME) → logind `IdleSinceHint` → `xprintidle` (X11).
- Multimedia: MPRIS (`PlaybackStatus == "Playing"`). Notificaciones: `org.freedesktop.Notifications` con acción "Cancelar".
- Eventos: señales `PrepareForSleep`/`PrepareForShutdown`; inhibidor `Inhibit("shutdown:sleep", "kse", motivo, "delay")`.
- Helper: `/usr/local/libexec/kse-helper` (root:root 0755, `#!/usr/bin/python3` del sistema, solo stdlib) + `/usr/share/polkit-1/actions/org.kse.helper.policy` (acción `org.kse.helper.wake`) con `allow_active=yes` y la anotación `org.freedesktop.policykit.exec.path` → `pkexec /usr/local/libexec/kse-helper wake-set <epoch>` sin contraseña en sesión activa. Valida que el epoch sea entero, futuro y < 1 año. Nunca ejecuta nada arbitrario.
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
| GET | `/pending` | próximos disparos + despertar programado |
| POST | `/runs/{id}/cancel` · `/cancel` | cancelar ejecución · cuenta atrás actual |
| POST | `/runs/{id}/postpone` | posponer (p. ej. 10 min) |
| GET | `/history` | historial paginado |
| GET | `/capabilities` | informe doctor |
| GET | `/schema/rule` | JSON Schema (GUI y futuro asistente IA) |
| WS | `/events` | `warning_started`, `tick`, `cancelled`, `postponed`, `run_started`, `run_finished`, `rule_changed`, `wake_changed` |

Solo escucha en 127.0.0.1. El acceso remoto (fase 5) será opt-in.

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
kse doctor [--test-wake 120]
kse service install [--linger] | uninstall | status
kse helper install [--unattended] | uninstall
kse gui
```
Los comandos rápidos crean reglas `one_shot` vía API. Si el demonio no está activo, lo indican y sugieren `kse service install`. Opción global `--dry-run`.

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
- Linux: `~/.config/systemd/user/kse.service` (+ linger opcional) · `~/.config/autostart/kse-gui.desktop`.
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
│   ├── config.py        # rutas platformdirs, daemon.json
│   ├── engine/          # scheduler.py evaluator.py executor.py wake.py
│   ├── sensors/         # base.py system.py (psutil) registry.py
│   ├── platform/        # __init__.py (get_backend) base.py fake.py
│   │   ├── linux/       # backend.py logind.py idle.py desktop.py notify.py
│   │   ├── windows/     # fase 3
│   │   └── macos/       # fase 4
│   ├── helper/          # kse_helper_linux.py org.kse.helper.policy 50-kse-unattended.rules
│   ├── daemon/          # main.py api.py store.py events.py
│   ├── cli/             # main.py
│   ├── install/         # service.py autostart.py helper.py
│   └── gui/             # app.py tray.py quick.py rules.py countdown.py doctor.py client.py
└── tests/               # unit/ + real/ (@pytest.mark.real, excluidos por defecto)
```

## 14. Límites conocidos y decisiones
- El encendido desde S5 no está garantizado (BIOS); en portátil, con AC.
- En Wayland, idle vía D-Bus del escritorio; `xprintidle` solo en X11.
- Nombre público: no usar "KShutdown" (es un proyecto ajeno). `kse` es provisional; comprobar disponibilidad en PyPI antes de publicar.
