---
description: Actualizar docs → commit local → push → nuevo release en GitHub
---

Ejecuta siempre la siguiente secuencia completa, en orden, sin saltear pasos.
Contexto o notas adicionales del usuario (puede estar vacío): $ARGUMENTS

Antes de empezar, lee `AGENTS.md` y respeta sus reglas (constitución en
`.specify/memory/constitution.md`, fuentes de verdad en la tabla de docs,
`docs/release-maintenance.md` para releases). Nunca incluyas secretos, tokens
ni API keys en commits, mensajes, docs o outputs.

## 1. Actualizar toda la documentación

- Revisa los cambios del working tree (`git status`, `git diff`, archivos sin
  trackear) e identifica qué afectan.
- Actualiza **toda** la documentación afectada según la tabla "Sources of
  truth" de `AGENTS.md` (docs/, README si aplica, contratos en
  `specs/*/contracts/`, `docs/CHANGELOG.md`), en el mismo change set que el
  código.
- No inventes cambios de comportamiento: documenta solo lo que el diff muestra.

## 2. Commit local

- Ejecuta primero el gate del proyecto (`uv sync && uv run pytest`): el commit
  solo procede con la suite **verde y 0 tests skipeados**. Si falla, detente,
  reporta los fallos y no commitees.
- Los archivos de scratch van solo en `tmp/` (git-ignored): nunca los commitees.
- Stage de código + docs juntos, y crea el commit con mensaje conventional
  (tipo + alcance + descripción de los cambios), incluyendo los archivos de
  documentación actualizados.

## 3. Push

- `git push` de la branch actual a su remote. Si el push es rechazado, haz
  `git pull --rebase`, resuelve si hay conflicto y reintenta.
- Verifica que el push quedó arriba (`git status` / `git log origin/<branch>`).

## 4. Nuevo release en GitHub

- Sigue el procedimiento de `docs/release-maintenance.md`:
  1. Confirma que `pyproject.toml` (versión) y la sección tope de
     `docs/CHANGELOG.md` están consistentes; si el change set lo requiere,
     decide el bump de versión (SemVer) y ajusta ambos antes del commit del
     paso 2 — no después.
  2. Crea el tag anotado con la versión (p. ej. `v0.9.4`) y pushealo.
  3. Crea el release en GitHub con `gh release create <tag> --title ... --notes
     ...`, usando como notas el contenido de la sección correspondiente del
     `CHANGELOG.md` (o el artefacto de release que defina
     `docs/release-maintenance.md`).
- Si `gh` no está autenticado o falla, reporta el error y detente en este paso.

## Reporte final

Cierra resumiendo: archivos commiteados, hash del commit, branch/remote
pusheado, tag y URL del release creado (o el punto exacto donde se detuvo y
por qué).