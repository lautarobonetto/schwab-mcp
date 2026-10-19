# Changelog

Registro del progreso del código de `schwab-mcp`.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/)
y el versionado es [SemVer](https://semver.org/lang/es/): MAJOR para
cambios incompatibles, MINOR por feature nueva, PATCH por correcciones.

## [0.2.0] - 2026-10-19

Feature 002 — **Renovación automática de tokens** para agentes de AI
desatendidos (spec: `specs/002-automated-token-renewal/`).

### Added

- **`schwab-mcp renew`**: renovación explícita no interactiva con
  resultado clasificado en una línea JSON (≤ 300 bytes) y exit codes
  `0/2/3/6/7` — el agente distingue éxito, `not_needed`, fallo
  transitorio (reintentable) y `reauth_required` (acción humana) sin
  interpretar texto libre.
- **`schwab-mcp auth-status`**: consulta de salud de autenticación en
  una request — estado (`valid`/`reauth_required`), vida útil restante
  del access y del refresh token. Lectura estrictamente local, sin red,
  ≤ 2 s; nunca dispara renovaciones.
- **Clasificación de outcomes** (`renewal.py`): tipos `RenewalOutcome` /
  `AuthHealth` con enums cerrados (`renewed|not_needed|
  transient_failure|reauth_required`), serialización compacta y cero
  secretos.
- **Camino automático transparente (US1)**: toda operación autenticada
  con validez por debajo del margen preventivo (61 s, provisto por
  schwabdev) renueva solo, sin browser ni interacción; la forma del
  resultado de la operación no cambia.
- **Eventos de auditoría de renovación**: `renew_start` →
  `renewal_success`/`renewal_failure` en stderr, con trigger
  `margin_trigger` (automático) o `explicit_command` (CLI), sin secretos.
- **Estado "re-autorización requerida" detectable (US3)**: cuando el
  refresh token es rechazado, todas las rutas reportan la misma
  clasificación consistente y acotan los intentos contra el proveedor
  (sin retry storms).
- **Guía para agentes de AI**: `docs/tools.md` — referencia detallada de
  la interfaz consumible por agentes.

### Changed

- `retry_once` generalizado a `retry_call(fn, retries=2)` en
  `tokens.py`: implementación única de reintento acotado del proyecto
  (DRY), reutilizada por validación de arranque y renovación.
- `server.py`: validación de arranque usa el reintento generalizado y
  emite eventos de ciclo de vida de renovación.

### Fixed

- **Regresión ISO-8601** en el lector de vida útil: schwabdev guarda
  `*_token_issued` como texto ISO (`2026-10-19T22:00:27.004577+00:00`),
  no como epoch numérico; el lector hacía `float - str` y crasheaba con
  exit 1. Ahora parsea ISO (asumiendo UTC si falta zona), tolera epochs
  numéricos y degrada a `reauth_required` ante timestamps no parseables
  en lugar de crashear. Cubierto con pruebas de regresión sobre el
  esquema real de la DB.

### Validación

- 294 tests pasando, 0 skipped (gates de rendimiento ≤ 10 s y de
  token-usage ≤ 300 bytes incluidos).
- Smoke manual verificado: `renew` (`not_needed` exit 0),
  `auth-status` (`valid` exit 0), fail-fast de configuración (exit 2).

## [0.1.0] - 2026-10-19

Feature 001 — **Capa de acceso OAuth a Schwab** (spec:
`specs/001-schwab-oauth-access/`).

### Added

- **`schwab-mcp auth`**: autorización interactiva one-shot con flujo
  paste-the-redirect-URL (browser del dueño + paste de la URL de
  redirect). Sin sockets de entrada.
- **`schwab-mcp serve`**: servidor MCP stdio headless con validación
  proactiva de acceso al arrancar (< 5 s). Registra 0 tools en esta
  versión (reservado para features futuras).
- **Token store** local SQLite (vía schwabdev 4.0.0) en
  `~/.schwab-mcp/tokens.db` con permisos `0o600`.
- **Taxonomía de errores** con exit codes accionables por falla
  (configuración, autorización, store, conectividad) — sin tracebacks.
- **Filtro de redacción** en logs: app secret, tokens y códigos de
  autorización jamás aparecen en la salida.
- **Lock de autorización** para evitar corridas concurrentes.
- Documentación: `docs/instalacion.md`, `docs/uso.md`; artefactos de
  spec en `specs/001-schwab-oauth-access/`.
- Suite de tests (unit/integration/performance) con gates TDD.

[0.2.0]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/lautarobonetto/schwab-mcp/releases/tag/v0.1.0