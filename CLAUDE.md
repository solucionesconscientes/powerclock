# CLAUDE.md — PowerClock (paquete `powerclock`)

Antes de escribir código lee SIEMPRE: `docs/ARCHITECTURE.md` (diseño) y `docs/ROADMAP.md` (hitos y estado).

## Contexto
- El usuario (Ser) no programa a mano: tú escribes todo el código. Explica decisiones en español, breve y directo.
- Máquina de desarrollo: Kubuntu, KDE Plasma (Wayland), Dell Latitude 5480. También se usará en un VPS Kubuntu sin GUI.
- Distribución final: `pipx install powerclock` / `pipx install "powerclock[gui]"`.

## 🚨 Reglas de seguridad (innegociables)
1. NUNCA ejecutes acciones reales de energía (apagar, reiniciar, suspender, hibernar, cerrar sesión, bloquear, apagar pantalla) en esta máquina. Tests y pruebas manuales siempre con `POWERCLOCK_BACKEND=fake` o `POWERCLOCK_DRY_RUN=1`.
2. NUNCA escribas en `/sys/class/rtc` ni ejecutes `rtcwake` salvo petición explícita del usuario en ese momento.
3. NUNCA ejecutes `sudo` ni `pkexec`. Si hace falta, muestra al usuario los comandos exactos en UN único bloque y espera a que confirme.
4. Tests que tocan el sistema real: marcados `@pytest.mark.real` y excluidos por defecto (`-m "not real"`).
5. No instales paquetes del sistema (apt). Dependencias Python solo con `uv add`, y solo las de ARCHITECTURE §3; para cualquier otra, pregunta antes.

## Reglas de arquitectura
- Código específico de SO SOLO en `src/powerclock/platform/<os>/`. `models`, `engine`, `sensors`, `daemon`, `cli` no importan módulos de un SO concreto.
- Todo acceso al SO pasa por `PlatformBackend`. Lo no soportado lanza `NotSupported` con explicación; nunca falla en silencio.
- Orden para cada funcionalidad: modelo → motor → API → CLI → (GUI) → tests → docs.
- Los modelos pydantic son la fuente de verdad; el JSON Schema de reglas se genera de ellos.
- Demonio y backends asíncronos (asyncio). La GUI habla con el API sin bloquear el hilo de Qt (qasync o QThread).
- Tiempo: datetimes siempre con zona (zoneinfo). UTC interno, hora local solo en presentación.

## Flujo de trabajo
- Trabaja hito a hito según `docs/ROADMAP.md`. Al terminar cada hito ejecuta:
  `uv run ruff check --fix . && uv run ruff format . && uv run pytest -m "not real"`
  Todo verde → marca los checkboxes del hito → commit (Conventional Commits, en inglés).
- Si un hito revela un problema de diseño, propón el cambio en `docs/ARCHITECTURE.md` antes de implementarlo.
- Código, identificadores, comentarios y commits en inglés. Textos de interfaz traducibles (es, en). Mensajes al usuario en español.
- Type hints completos, funciones pequeñas, cero dependencias innecesarias.
- Al dar comandos al usuario: siempre listos para copiar, agrupados en un único bloque.

## Comandos útiles
- Entorno: `uv sync --all-extras`
- Tests: `uv run pytest -m "not real"`
- Demonio en primer plano (seguro): `POWERCLOCK_DRY_RUN=1 uv run powerclock-daemon --foreground`
- CLI: `uv run powerclock --help`
