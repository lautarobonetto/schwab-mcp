# AGENTS.md

Punto de entrada para agentes de AI trabajando **en el código** de este
repo. (Si buscás cómo *usar* el MCP como agente, andá a
[docs/tools.md](docs/tools.md).)

## Autoridad

La constitución del proyecto es
[`.specify/memory/constitution.md`](.specify/memory/constitution.md) —
**leerla antes de planificar o implementar cualquier cosa**. No es
negociable y prima sobre cualquier otra práctica. Resumen no normativo:

- **TDD obligatorio**: tests primero (Red → Green → Refactor); los bug
  fixes empiezan con un test de regresión que reproduzca el defecto.
- **DRY / Reuse Before Creation / KISS**: una sola implementación por
  conocimiento; reusar antes de crear; lo más simple que cumpla.
- **Presupuestos medibles**: tests de performance y de token-usage por
  feature; los crecimientos requieren justificación registrada.
- **Layout fijo**: código en `src/`, tests en `tests/`, documentación en
  `docs/`, scratch **solo** en `tmp/` (git-ignored). Nada fuera.
- **Credential safety**: tokens/secretos jamás en logs, outputs o git.
- **Commits**: suite completa verde y sin tests skipped; mensaje que
  enumere los cambios; **documentación afectada actualizada e incluida
  en el mismo commit**.

## Flujo de trabajo

Spec Kit: `/speckit.specify` → `/speckit.plan` → `/speckit.tasks` →
`/speckit.implement` → `/speckit.converge`. Los artefactos de cada
feature viven en `specs/<NNN-feature>/` (spec, plan, tasks, contracts,
quickstart). Antes de implementar, correr `/speckit.analyze` para
detectar inconsistencias entre spec/plan/tasks.

## Comandos

```sh
uv sync                        # instalar entorno
uv run pytest                  # suite completa (gate de commit: verde, 0 skipped)
uv run schwab-mcp --help       # CLI: auth, serve, renew, auth-status
```

## Fuentes de verdad (no duplicar aquí)

| Tema | Dónde |
|------|-------|
| Gobernanza y gates | [`.specify/memory/constitution.md`](.specify/memory/constitution.md) |
| Interfaz para agentes de AI que consumen el MCP | [`docs/tools.md`](docs/tools.md) |
| Uso e instalación (humanos) | [`docs/uso.md`](docs/uso.md) · [`docs/instalacion.md`](docs/instalacion.md) |
| Historia de cambios | [`docs/CHANGELOG.md`](docs/CHANGELOG.md) |
| Contratos de comandos/eventos | [`specs/*/contracts/`](specs/) |