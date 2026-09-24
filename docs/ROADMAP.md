# Roadmap — PowerClock

Marca `[x]` al completar. Cada hito termina con ruff + pytest en verde y un commit.

## Fase 1 — Linux MVP (v0.1.0)

### M1 — Esqueleto y modelos
- [x] `pyproject.toml` (hatchling, src/, entry points powerclock/powerclock-daemon/powerclock-gui, extra `gui` + grupo `dev`, marcadores de plataforma)
- [x] `uv sync --all-extras` funciona; ruff y pytest configurados (marker `real` excluido por defecto)
- [x] `models.py`: Rule, disparadores, predicados (all/any/not), guardas, acciones (uniones discriminadas pydantic), `parse_duration`
- [x] `platform/base.py` (PlatformBackend, Capability, NotSupported, enums) y `platform/fake.py`
- [x] `get_backend()` con override `POWERCLOCK_BACKEND=fake`
- [x] `examples/` con 5 reglas de ejemplo válidas
- [x] Tests: reglas válidas/inválidas, round-trip JSON, exportación de JSON Schema, ejemplos validan
**DoD:** `uv run pytest` verde; `uv run powerclock --version` funciona.

### M2 — Motor
- [x] Scheduler: `at`, `countdown`, `cron` (zoneinfo + croniter), `next_fire`, resincronización ≤ 30 s, saltos de reloj
- [x] Evaluator: conditions y guards con retry/max_wait
- [x] Executor: secuencias, `on_error`, `Run` con estados, cuenta atrás cancelable/posponible, una sola acción de energía a la vez
- [x] Acciones: `run`, `notify`, `wait`, `wait_until`, `power` (vía backend), `open`, `close_app`
- [x] Dry-run global (`POWERCLOCK_DRY_RUN`) y por regla; `on_missed`
- [x] Tests con reloj falso + FakePlatform (cancelar cuenta atrás, guardas que posponen, cron a través del cambio de hora DST)
**DoD:** tests verdes para cada disparador de tiempo y cada acción.

### M3 — Backend Linux: energía, idle, sensores, doctor
- [x] logind vía dbus-fast (Can* + acciones)
- [x] Graceful KDE (`org.kde.Shutdown`) / GNOME con introspección y alternativa logind
- [x] lock, logout, screen_off
- [x] `idle_seconds` con cadena de estrategias (Wayland ext-idle-notify → GNOME → logind → xprintidle)
- [x] `media_playing` (MPRIS); notificaciones con acción "Cancelar"
- [x] `sensors/` con psutil: CPU, red, procesos, batería, AC, sesiones SSH
- [x] `capabilities()` completo (ver ARCHITECTURE §7) y `powerclock doctor` con tabla rich
- [x] Zona horaria IANA del sistema (para reglas sin `timezone`; en Linux, `/etc/localtime`)
- [x] Tests con D-Bus simulado; tests reales marcados `real`
**DoD:** `POWERCLOCK_DRY_RUN=1 uv run powerclock doctor` da un informe correcto en Kubuntu/KDE Wayland.

### M4 — Demonio, API, almacenamiento, CLI
- [x] Store: rules.json (validación, escritura atómica, recarga en caliente), history.sqlite, token 0600
- [x] Demonio asyncio + FastAPI/uvicorn en 127.0.0.1, auth por token, WS `/events`
- [x] Todos los endpoints de ARCHITECTURE §8
- [x] CLI typer completo (comandos rápidos, rules, status, cancel, postpone, doctor)
- [x] `powerclock service install/uninstall/status` (systemd --user) con `--linger` opcional
- [x] Tests de API (TestClient + FakePlatform)
**DoD:** con el servicio en dry-run: `powerclock shutdown --in 2m` crea la regla, `powerclock status` la muestra, `powerclock cancel` la cancela y el historial lo registra.

### M5 — Encendido/despertar ⚠ requiere sudo del usuario
- [x] Helper stdlib: wake-set/clear/get con `rtcwake -m no` (alternativa sysfs con valor relativo `+<segundos>`) y validación estricta
- [x] Política polkit `allow_active=yes`; `powerclock helper install/uninstall` (muestra los comandos sudo y pide confirmación)
- [x] Regla polkit opcional `--unattended` (login1 power-* y acción del helper `org.powerclock.helper.wake`, sin sesión activa)
- [x] WakePlanner: próximo despertar, margen, reprogramación (cambios, disparos, PrepareForSleep/Shutdown con inhibidor delay)
- [x] `powerclock wake --at`, `powerclock doctor --test-wake 120` (solo con confirmación explícita)
**DoD:** el usuario verifica en su Latitude el despertar desde suspensión ✅ (24-09-2026: despertó sola a los 2 s de la alarma); el resultado desde S5 queda documentado ✅ (24-09-2026: con AC, se encendió sola; el kernel arrancó 14 s después de la alarma).

### M6 — Disparadores por condición y guardas
- [x] `idle`, `process_exit`, `cpu_below`, `net_below` (media móvil + `for`), `battery`, `power_source`, `startup`
- [x] Sensores bajo demanda (solo los usados por reglas activas)
- [x] Guardas: `process_running`, `media_playing`, `ssh_session`, `time_window`, `weekday`
- [x] CLI: `--when-idle`, `--when-exits`, `--when-cpu-below`, `--when-net-below`
**DoD:** tests con sensores falsos para cada disparador y guarda ✅ (`FakeReadings` + reloj falso: `test_sensor_hub.py`, `test_watcher.py`, `test_watch_api.py`). Probado además en dry-run en el Latitude con sensores reales (CPU, red y un `ffmpeg` falso).

### M7 — GUI PySide6
- [x] Bandeja con estado y menú
- [x] Pestaña Rápido (estilo KShutdown) + "Encender a las…"
- [x] Pestaña Reglas (lista + editor por formularios + JSON)
- [x] Historial y Diagnóstico (instalar helper, probar despertar)
- [x] Diálogo de cuenta atrás (Cancelar / Posponer 10 min) vía WS
- [x] Autoarranque; i18n es/en
**DoD:** flujo completo desde la GUI en KDE Wayland ✅ (24-09-2026: probado por el usuario en su Latitude, en dry-run: bandeja, Rápido, cuenta atrás con Cancelar/Posponer, editor de reglas con JSON, Diagnóstico y entrada en el menú; además, tests con Qt offscreen contra un demonio simulado).

### M8 — Instalador para todos (Linux)
- [x] Lanzador `installers/install-powerclock.sh`: se abre en una terminal, descarga uv (versión fija, SHA-256 comprobado), instala PowerClock con Python gestionado y abre la ventana de instalación
- [x] Pasos de instalación y desinstalación comunes (`install/steps.py`); `powerclock setup`, `powerclock update` y `powerclock uninstall`
- [x] Ventana de instalación (`powerclock-gui --setup`): casillas, una sola contraseña, abrir PowerClock al terminar
- [x] Bienvenida la primera vez; Diagnóstico: versión, buscar/instalar actualizaciones, desinstalar
- [x] Tests (lanzador con uv falso, pasos con fachadas falsas, ventana en offscreen) y README; la publicación en GitHub adjunta el lanzador
**DoD:** en el Kubuntu del usuario, con el paquete local: doble clic en el lanzador → contraseña → PowerClock en la bandeja, en el menú y con el servicio en marcha; desinstalar lo deja todo como estaba. ⏳ (pendiente de la prueba del usuario)

### M9 — Publicación 0.1.0
- [x] README (es/en) con capturas; `examples/` documentados (`README.md`, `README.es.md`; capturas con `scripts/screenshots.py`. Al publicar en PyPI, las imágenes necesitan URL absolutas)
- [ ] Comprobar el nombre en PyPI (PowerClock ✅, libre); `pipx install .` limpio en Kubuntu y en el VPS (sin GUI)
- [ ] GitHub Actions: lint + tests (Linux), build sdist/wheel (`ci.yml` con Python 3.11–3.14 y `release.yml`, que publica en PyPI con Trusted Publishing al etiquetar `vX.Y.Z`; falta verlos en verde en GitHub)
- [x] CHANGELOG; licencia definitiva (GPL-3.0-or-later, `LICENSE`)

## Empaquetado (opcional, cuando se decida)
De momento la distribución es `pipx` en los tres SO. Opciones estudiadas, por ganancia:
- Windows: instalador firmado + winget (evita instalar Python antes).
- macOS: `.app` firmada vía Homebrew cask (necesaria para notificaciones con botones y un icono propio en el Dock).
- Linux: paquetes `powerclock` + `powerclock-gui` (PPA, AUR, COPR/OBS): instalación en un paso, actualizaciones del sistema y Breeze nativo. Ubuntu 26.04 tiene todas las dependencias, pero más antiguas que los mínimos actuales: habría que bajar los mínimos y probarlas, o llevar las propias dentro del paquete.

## Fase 2 — Workflows y más disparadores (v0.2)
`file`, `wifi_ssid`, `usb`, `temperature`; webhook de entrada y salida; Telegram (notificar); editor visual de condiciones; plantillas/recetas; estadísticas de uso y ahorro.

## Fase 3 — Windows (v0.3)
Backend Windows (shutdown.exe, SetSuspendState, LockWorkStation, GetLastInputInfo, toasts); wake con Task Scheduler `WakeToRun`; `doctor` con Modern Standby y temporizadores de reactivación; servicio al iniciar sesión; CI Windows.

## Fase 4 — macOS experimental (v0.4)
pmset, osascript, idle vía IOKit, LaunchAgent + helper LaunchDaemon, CI macOS, DMG con firma ad-hoc.

## Fase 5 — Remoto e IA (v1.0)
Bot de Telegram (control y disparador), web UI, multi-equipo (portátil + VPS), Wake-on-LAN, MQTT/Home Assistant, KDE Connect, asistente en lenguaje natural → regla JSON validada contra `/schema/rule`.
