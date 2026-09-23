# KShutdown Evolution (`kse`)

> 🚧 En desarrollo — fase 1 (Linux). / Work in progress — phase 1 (Linux).

Automatiza apagar, suspender, hibernar y **encender** el equipo, y ejecuta programas o scripts por hora o por condición, con reglas persistentes que funcionan aunque la interfaz esté cerrada.

- Diseño: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Hoja de ruta: [docs/ROADMAP.md](docs/ROADMAP.md)
- Reglas de ejemplo: [examples/](examples/)

## Desarrollo

```bash
uv sync --all-extras
uv run pytest
uv run kse --version
```
