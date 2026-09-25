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
**DoD:** en el Kubuntu del usuario, con el paquete local: doble clic en el lanzador → contraseña → PowerClock en la bandeja, en el menú y con el servicio en marcha; desinstalar lo deja todo como estaba. ✅ (24-09-2026: probado por el usuario en su Latitude, en dry-run y desde el código local)

### M9 — Textos y vocabulario (rediseño, fase 1)
Decidido el 25-09-2026 (ver ARCHITECTURE §10, «Rediseño»). Todo lo nuevo añade textos: fijar antes el vocabulario evita reescribirlos.
- [x] Tabla de vocabulario aplicada en es/en: GUI, textos compartidos (`labels.py`, motivos, capacidades) y los mensajes de la CLI que ve el usuario
- [x] Rápido: botón con verbo y objeto («Programar apagado», «Apagar ahora»), «Programado», condiciones con nombres del usuario, «Avisar antes», «Volver a encenderlo a las»
- [x] Editor: «Cuándo», «Solo si…», «Esperar mientras…», «Qué hará»
- [x] Cuenta atrás, bandeja y avisos con frases completas («El equipo se apagará en 42 s · Puedes cancelarlo hasta el último segundo»)
- [x] Diagnóstico con nombres claros (lo técnico, en el detalle) e Historial con «Origen»
- [x] Subtítulo nuevo en la instalación, la bienvenida, el README y el instalador
**DoD:** ninguna de estas palabras a la vista en la GUI: demonio, simulacro, ayudante, desatendido, guarda, disparador; tests y traducciones al día; revisado por el usuario.

### M10 — Abrir aplicaciones
Decidido el 25-09-2026 a partir de 32 casos de uso (lo piden 13). Diseño en ARCHITECTURE §4 («Paso `launch`»). Hecho el 25-09-2026: además, el disparador y la condición `desktop_session`, y `close_app` por `app` o con señal.
- [x] Modelo: paso `launch` (app, receta, argumentos, ventana, mantener abierta) y variables `{date}`, `{time}`… en órdenes, rutas y avisos
- [x] Linux: catálogo de aplicaciones instaladas (menú, Flatpak, Snap) leyendo sus `.desktop`
- [x] Linux: entorno de la sesión gráfica desde el gestor de servicios del usuario; lanzar como unidad transitoria `app-powerclock-…` (también `run`, que hoy no ve la pantalla si el servicio arrancó antes que la sesión)
- [x] Esperar a la ventana y colocarla con guiones de KWin (pantalla, escritorio, pantalla completa…); mantener abierta; cerrar con la señal elegida
- [x] Recetas como datos (JSON en el paquete) para los programas del catálogo
- [x] GUI: selector de aplicaciones con icono y recetas; CLI: `powerclock apps`
**DoD:** en el Latitude, una regla abre Chrome en modo app en la pantalla elegida, VLC con una lista y FreeFileSync (Flatpak) con un trabajo, también con el servicio arrancado antes que la sesión.

### M11 — Publicación 0.1.0
- [x] README (es/en) con capturas; `examples/` documentados (`README.md`, `README.es.md`; capturas con `scripts/screenshots.py`. Al publicar en PyPI, las imágenes necesitan URL absolutas)
- [x] Comprobar el nombre en PyPI; `pipx install powerclock` y `pipx install "powerclock[gui]"` limpios desde PyPI en Kubuntu (25-09-2026, en una carpeta aislada). Falta el VPS (sin GUI).
- [x] GitHub Actions: lint + tests (Linux), build sdist/wheel (`ci.yml` con Python 3.11–3.14, en verde; `release.yml` publica en PyPI con Trusted Publishing al etiquetar `vX.Y.Z`). Repositorio público: https://github.com/solucionesconscientes/powerclock · **0.1.0 publicada el 25-09-2026** en https://pypi.org/project/powerclock/ con el instalador en https://github.com/solucionesconscientes/powerclock/releases/tag/v0.1.0
- [ ] Prueba real del instalador (`install-powerclock.sh` de la release) en el Latitude
- [x] CHANGELOG; licencia definitiva (GPL-3.0-or-later, `LICENSE`)

## Empaquetado (opcional, cuando se decida)
De momento la distribución es el instalador (lanzador + uv, M8) y `pipx`. Opciones estudiadas, por ganancia:
- Windows: instalador firmado + winget (evita instalar Python antes).
- macOS: `.app` firmada vía Homebrew cask (necesaria para notificaciones con botones y un icono propio en el Dock).
- Linux: paquetes `powerclock` + `powerclock-gui` (PPA, AUR, COPR/OBS): instalación en un paso, actualizaciones del sistema y Breeze nativo. Ubuntu 26.04 tiene todas las dependencias, pero más antiguas que los mínimos actuales: habría que bajar los mínimos y probarlas, o llevar las propias dentro del paquete.

## Fase 2 — Sesión, escritorio y avisos (entra en la 0.1.0: se hizo antes de publicar)
Orden decidido el 25-09-2026: lo que desbloquea más casos de uso, primero.
- **M12 — Encender y entrar** (✅ hecho el 25-09-2026 con SDDM y LightDM; falta la prueba real en el Latitude: reinstalar el permiso de encendido y un apagado con encendido programado): llave de un solo uso (entrada automática solo en el arranque que provoca la alarma de PowerClock, con bloqueo inmediato; ARCHITECTURE §6); quiosco con usuario dedicado; margen de 3 min cuando hay que entrar.
- **M13 — Sonido, reproductores y escritorio** (✅ hecho el 25-09-2026; pasos `media`, `volume`, `sound`, `desktop`, `network`, `inhibit` y `screenshot`): MPRIS (lista, emisora, pausa), volumen y fundidos, sonidos y voz, tema y fondo, brillo, perfil de energía, VPN, No molestar, pantalla siempre encendida, capturas para el historial.
- **M14 — Rediseño, fases 2 y 3** (✅ hecho el 25-09-2026; ventana 987×610 en vez de 800×494, ver ARCHITECTURE §10): sistema visual (colores de estado, escala φ, fuente del escritorio, iconos de bandeja) y pantallas (franja «Próximo», acciones en botones, tarjetas, anillo de cuenta atrás).
- **M15 — Rediseño, fase 4** (✅ hecho el 25-09-2026): editor que se lee como una frase, horarios sin cron, galería de recetas por caso de uso.
- **M16 — Avisos y respuestas** (✅ hecho el 25-09-2026: `push` con ntfy, Telegram y webhooks; `ask`; `on_failure`; secretos): ntfy primero (sin cuenta ni dependencias nuevas), después Telegram y webhooks de salida; avisos con botones que esperan respuesta; pasos «si algo falla».
- **M17 — Más disparadores** (✅ hecho el 25-09-2026; falta «franjas propias» para tarifas de otros países): amanecer y anochecer, calendario (ICS) y festivos, tiempo de uso, ficheros y carpetas, dispositivos, `wifi_ssid` como disparador, `temperature`; tarifa de la luz como **ajuste opcional** (desactivado por defecto; España 2.0TD o franjas propias) con la condición «tramo de la luz».
- **M18 — Varios equipos** (✅ hecho el 25-09-2026: paso `wake_lan` y `powerclock wake-lan`; `powerclock stats`, resumen en Historial y caja Electricidad en Diagnóstico): Wake-on-LAN; estadísticas de uso y ahorro (horas apagado, kWh y € estimados).
Pendiente de decidir más adelante: navegador automatizado (Playwright, dependencia nueva), accesibilidad AT-SPI, teclado y ratón virtuales, sesión fantasma.

## Fase 3 — Windows (v0.3)
Backend Windows (shutdown.exe, SetSuspendState, LockWorkStation, GetLastInputInfo, toasts); wake con Task Scheduler `WakeToRun`; `doctor` con Modern Standby y temporizadores de reactivación; servicio al iniciar sesión; CI Windows.

## Fase 4 — macOS experimental (v0.4)
pmset, osascript, idle vía IOKit, LaunchAgent + helper LaunchDaemon, CI macOS, DMG con firma ad-hoc.

## Fase 5 — Remoto e IA (v1.0)
Bot de Telegram (control y disparador), web UI, multi-equipo (portátil + VPS), MQTT/Home Assistant, KDE Connect, asistente en lenguaje natural → regla JSON validada contra `/schema/rule`.
