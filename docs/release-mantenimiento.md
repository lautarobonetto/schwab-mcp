# Release y mantenimiento del paquete de distribución

Cómo empaquetar `schwab-mcp` para entregarlo a destinatarios que **no**
trabajan con el repo. La audiencia de esta guía es el **mantenedor** del
proyecto; los destinatarios usan los manuales en inglés que viajan dentro
del paquete (`docs/release/`).

## El comando

```sh
uv run schwab-mcp-release build [--allow-dirty] [--output-dir DIR]
```

| Argumento | Default | Qué hace |
|-----------|---------|----------|
| `--allow-dirty` | off | Permite buildear con cambios sin commitear; el manifest registra `build_dirty: true` |
| `--output-dir` | `dist/` | Destino del archive y su checksum |

El tooling vive en `src/schwab_mcp_release/` y **no** se incluye en el
wheel entregado (`packages = ["schwab_mcp"]` en `pyproject.toml`).

## Qué produce

En `dist/`, exactamente dos archivos:

- `schwab-mcp-<version>.zip` — el paquete de distribución.
- `schwab-mcp-<version>.zip.sha256` — checksum exterior
  (`<sha256>  schwab-mcp-<version>.zip`).

El archive envuelve todo bajo `schwab-mcp-<version>/` y contiene: el
wheel del runtime (solo el package `schwab_mcp`), el `README.md` del
paquete, los 4 manuales en `manuals/`, `install.sh`, `manifest.json` y
`SHA256SUMS`. La salida por stdout es un contrato estable (tests):

```text
BUILD schwab-mcp <version>
WHEEL  schwab_mcp-<version>-py3-none-any.whl
ARCHIVE members=<n> bytes=<size>
CHECKS completeness=PASS exclusion=PASS secrets=PASS
OUT    dist/schwab-mcp-<version>.zip
OUT    dist/schwab-mcp-<version>.zip.sha256
OK     build complete in <s>s
```

## Checks incluidos (el build falla en voz alta)

Antes de emitir nada, el comando verifica el archive final:

1. **Completitud** — todos los miembros del allowlist presentes y no
   vacíos, sin entradas extra (`MISSING: …` / `UNEXPECTED: …`).
2. **Material de desarrollo** — nada de `tests/`, `specs/`, `plans/`,
   `.git*`, `__pycache__/`, `*.egg-info/`, source editable ni configs de
   dev, tampoco dentro del wheel (`DEV-MATERIAL: …`).
3. **Secretos** — ni archivos `.env`/`*.pem`/`*token*db*`/`*secret*`/
   `*credential*` ni contenido con forma de credencial (`SECRET: …`,
   solo el nombre — el contenido jamás se imprime).

Exit codes: `0` ok · `1` validación (nombra el miembro) · `2` árbol
sucio sin `--allow-dirty` · `3` prerequisito de build (toolchain o
fuente faltante). En fallo no queda archive válido ni checksum.

## Flujo de entrega

1. Commit limpio y suite verde (`uv run pytest`).
2. `uv run schwab-mcp-release build`
3. Enviar **ambos** archivos (`zip` + `zip.sha256`) al destinatario.
4. El destinatario sigue `docs/release/` (verifico checksum →
   `./install.sh` → `schwab-mcp auth` → conectar cliente de IA).

Los upgrades de destinatarios son re-instalación desde un archive nuevo:
`~/.schwab-mcp/tokens.db` queda fuera de la instalación y se preserva
automáticamente.

## Reproducibilidad

Mismo version + mismos inputs ⇒ archive byte-idéntico (FR-011). El build
normaliza timestamps (miembros del archive y del wheel vía
`SOURCE_DATE_EPOCH`) y fija el orden de miembros; dos builds seguidos
deben dar el mismo `shasum -a 256` del zip.

## Historial de validación

**2026-10-26** (quickstart de `specs/009-mcp-release-packaging/`):

| Escenario | Resultado |
|-----------|-----------|
| 1 — build completo | OK — stdout contrato, exit 0, < 60 s |
| 2 — contenido completo y limpio | OK — 9 entradas exactas, manifest correcto, checksums verifican |
| 3 — checks fallan en voz alta | OK — `MISSING:`/`SECRET:` con exit 1, sin checksum (cubierto por tests + validación manual) |
| 4 — guard de árbol sucio | OK — exit 2 + mensaje; `--allow-dirty` registra `build_dirty: true` |
| 5 — reproducibilidad | OK — digest idéntico entre builds separados |
| 6 — install recipiente (solo paquete) | OK pasos 1–2 (checksum → `install.sh` → `schwab-mcp --help` con versión, `HOME` intacto). Pasos 3–4 (auth + cliente de IA) requieren credenciales Schwab del destinatario — no ejecutables por el mantenedor |
| 7 — upgrade preserva credenciales | OK — validado por tests (`test_install_script.py`); tokens fuera de la instalación |
| 8 — suite completa | OK — verde, 0 skipped |
