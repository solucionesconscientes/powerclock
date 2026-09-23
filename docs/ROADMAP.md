# Roadmap — KShutdown Evolution

Marca `[x]` al completar. Cada hito termina con ruff + pytest en verde y un commit.

## Fase 1 — Linux MVP (v0.1.0)

### M1 — Esqueleto y modelos
- [x] `pyproject.toml` (hatchling, src/, entry points kse/kse-daemon/kse-gui, extra `gui` + grupo `dev`, marcadores de plataforma)
- [x] `uv sync --all-extras` funciona; ruff y pytest configurados (marker `real` excluido por defecto)
- [x] `models.py`: Rule, disparadores, predicados (all/any/not), guardas, acciones (uniones discriminadas pydantic), `parse_duration`
- [x] `platform/base.py` (PlatformBackend, Capability, NotSupported, enums) y `platform/fake.py`
- [x] `get_backend()` con override `KSE_BACKEND=fake`
- [x] `examples/` con 5 reglas de ejemplo válidas
- [x] Tests: reglas válidas/inválidas, round-trip JSON, exportación de JSON Schema, ejemplos validan
**DoD:** `uv run pytest` verde; `uv run kse --version` funciona.

### M2 — Motor
- [x] Scheduler: `at`, `countdown`, `cron` (zoneinfo + croniter), `next_fire`, resincronización ≤ 30 s, saltos de reloj
- [x] Evaluator: conditions y guards con retry/max_wait
- [x] Executor: secuencias, `on_error`, `Run` con estados, cuenta atrás cancelable/posponible, una sola acción de energía a la vez
- [x] Acciones: `run`, `notify`, `wait`, `wait_until`, `power` (vía backend), `open`, `close_app`
- [x] Dry-run global (`KSE_DRY_RUN`) y por regla; `on_missed`
- [x] Tests con reloj falso + FakePlatform (cancelar cuenta atrás, guardas que posponen, cron a través del cambio de hora DST)
**DoD:** tests verdes para cada disparador de tiempo y cada acción.

### M3 — Backend Linux: energía, idle, sensores, doctor
- [x] logind vía dbus-fast (Can* + acciones)
- [x] Graceful KDE (`org.kde.Shutdown`) / GNOME con introspección y alternativa logind
- [x] lock, logout, screen_off
- [x] `idle_seconds` con cadena de estrategias (Wayland ext-idle-notify → GNOME → logind → xprintidle)
- [x] `media_playing` (MPRIS); notificaciones con acción "Cancelar"
- [x] `sensors/` con psutil: CPU, red, procesos, batería, AC, sesiones SSH
- [x] `capabilities()` completo (ver ARCHITECTURE §7) y `kse doctor` con tabla rich
- [x] Zona horaria IANA del sistema (para reglas sin `timezone`; en Linux, `/etc/localtime`)
- [x] Tests con D-Bus simulado; tests reales marcados `real`
**DoD:** `KSE_DRY_RUN=1 uv run kse doctor` da un informe correcto en Kubuntu/KDE Wayland.

### M4 — Demonio, API, almacenamiento, CLI
- [ ] Store: rules.json (validación, escritura atómica, recarga en caliente), history.sqlite, token 0600
- [ ] Demonio asyncio + FastAPI/uvicorn en 127.0.0.1, auth por token, WS `/events`
- [ ] Todos los endpoints de ARCHITECTURE §8
- [ ] CLI typer completo (comandos rápidos, rules, status, cancel, postpone, doctor)
- [ ] `kse service install/uninstall/status` (systemd --user) con `--linger` opcional
- [ ] Tests de API (TestClient + FakePlatform)
**DoD:** con el servicio en dry-run: `kse shutdown --in 2m` crea la regla, `kse status` la muestra, `kse cancel` la cancela y el historial lo registra.

### M5 — Encendido/despertar ⚠ requiere sudo del usuario
- [ ] Helper stdlib: wake-set/clear/get con `rtcwake -m no` (alternativa sysfs con valor relativo `+<segundos>`) y validación estricta
- [ ] Política polkit `allow_active=yes`; `kse helper install/uninstall` (muestra los comandos sudo y pide confirmación)
- [ ] Regla polkit opcional `--unattended` (login1 power-* y acción del helper `org.kse.helper.wake`, sin sesión activa)
- [ ] WakePlanner: próximo despertar, margen, reprogramación (cambios, disparos, PrepareForSleep/Shutdown con inhibidor delay)
- [ ] `kse wake --at`, `kse doctor --test-wake 120` (solo con confirmación explícita)
**DoD:** el usuario verifica en su Latitude el despertar desde suspensión; el resultado desde S5 queda documentado.

### M6 — Disparadores por condición y guardas
- [ ] `idle`, `process_exit`, `cpu_below`, `net_below` (media móvil + `for`), `battery`, `power_source`, `startup`
- [ ] Sensores bajo demanda (solo los usados por reglas activas)
- [ ] Guardas: `process_running`, `media_playing`, `ssh_session`, `time_window`, `weekday`
- [ ] CLI: `--when-idle`, `--when-exits`, `--when-cpu-below`, `--when-net-below`
**DoD:** tests con sensores falsos para cada disparador y guarda.

### M7 — GUI PySide6
- [ ] Bandeja con estado y menú
- [ ] Pestaña Rápido (estilo KShutdown) + "Encender a las…"
- [ ] Pestaña Reglas (lista + editor por formularios + JSON)
- [ ] Historial y Diagnóstico (instalar helper, probar despertar)
- [ ] Diálogo de cuenta atrás (Cancelar / Posponer 10 min) vía WS
- [ ] Autoarranque; i18n es/en
**DoD:** flujo completo desde la GUI en KDE Wayland.

### M8 — Publicación 0.1.0
- [ ] README (es/en) con capturas; `examples/` documentados
- [ ] Comprobar el nombre en PyPI; `pipx install .` limpio en Kubuntu y en el VPS (sin GUI)
- [ ] GitHub Actions: lint + tests (Linux), build sdist/wheel
- [ ] CHANGELOG; licencia definitiva

## Fase 2 — Workflows y más disparadores (v0.2)
`file`, `wifi_ssid`, `usb`, `temperature`; webhook de entrada y salida; Telegram (notificar); editor visual de condiciones; plantillas/recetas; estadísticas de uso y ahorro.

## Fase 3 — Windows (v0.3)
Backend Windows (shutdown.exe, SetSuspendState, LockWorkStation, GetLastInputInfo, toasts); wake con Task Scheduler `WakeToRun`; `doctor` con Modern Standby y temporizadores de reactivación; servicio al iniciar sesión; CI Windows.

## Fase 4 — macOS experimental (v0.4)
pmset, osascript, idle vía IOKit, LaunchAgent + helper LaunchDaemon, CI macOS, DMG con firma ad-hoc.

## Fase 5 — Remoto e IA (v1.0)
Bot de Telegram (control y disparador), web UI, multi-equipo (portátil + VPS), Wake-on-LAN, MQTT/Home Assistant, KDE Connect, asistente en lenguaje natural → regla JSON validada contra `/schema/rule`.
