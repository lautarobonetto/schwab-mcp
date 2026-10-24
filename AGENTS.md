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

## Análisis de trades

Al analizar trades de un periodo determinado, si algún trade o cadena de
trades no tiene sentido (posición o saldo que no cierra, venta sin compra
previa, etc.), **no tratarlo como dato faltante o erróneo**: la cadena
probablemente comenzó **antes** del periodo analizado. Proceder así:

1. Identificar el trade huérfano dentro del periodo.
2. Buscar la apertura con el historial **filtrado por el instrumento**
   (`symbol`), en ventanas de tiempo **anteriores**, sucesivamente hacia
   atrás (la tool acepta hasta 1 año por pedido).
3. Declarar la estrategia de búsqueda **antes** de cada pedido (filtro,
   ventana y por qué), para que el proceso sea auditable.
4. Escalar a un pedido **sin filtro** solo si el barrido filtrado agotó
   su alcance sin encontrar la apertura: puede tratarse de un roll con
   símbolo distinto, una asignación o una transferencia entre cuentas,
   que el filtro por símbolo no captura.
5. Repetir hasta reconstruir la transacción de apertura que explique el
   estado inicial (compra, asignación, depósito, transferencia, etc.).
6. Re-analizar el periodo con el contexto completo, de modo que la cadena
   tenga sentido de punta a punta antes de concluir.

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