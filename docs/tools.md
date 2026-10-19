# Interfaz para agentes de AI

Referencia completa de la superficie consumible por un agente de AI
(por ejemplo, OpenClaw). Documenta **cada comando y cada campo** de la
salida, con semántica exacta para que el agente pueda decidir sin
intervención humana.

**Versión del documento**: 0.2.0 (ver [CHANGELOG](./CHANGELOG.md)).

## Cómo se consume este MCP

El proyecto expone **dos superficies**, con roles distintos:

| Superficie | Cómo se invoca | Estado en esta versión |
|------------|----------------|------------------------|
| Servidor MCP `serve` | Cliente MCP conecta por **stdio** | Transporte activo; **registra 0 tools** todavía |
| CLI one-shot | El agente corre `schwab-mcp <comando>` por shell | **Superficie principal del agente** hoy |

La superficie de tools MCP está reservada para features futuras. En la
versión 0.2.0 todo lo que un agente necesita —verificar salud de
autenticación y forzar renovación— se hace con los comandos one-shot
descritos abajo.

Garantías transversales de **todos** los comandos agent-facing:

- **No interactivos**: nunca abren browser, nunca leen stdin, nunca
  escuchan en sockets. Seguros para ejecución desatendida.
- **Salida parseable**: exactamente **una línea JSON** en stdout;
  nada más en stdout. Mensajes auxiliares y eventos van a stderr.
- **Sin secretos**: ningún campo contiene tokens, app keys/secretos ni
  URLs de autorización. Hay un filtro de redacción activo como defensa
  adicional (stderr incluido).
- **Tiempo acotado**: ningún comando se cuelga; presupuestos por comando.
- **Seguros ante concurrencia**: coordinación por lock; corrompen nada.

---

## `schwab-mcp renew`

Renovación explícita del access credential usando el refresh credential
almacenado. Es la palanca de recuperación del agente cuando detecta
problemas de autenticación, independiente del camino automático.

```sh
uv run schwab-mcp renew
```

- **Argumentos**: ninguno. **stdin**: nunca se lee.
- **Requiere**: `SCHWAB_APP_KEY` y `SCHWAB_APP_SECRET` en el entorno.
- **Puede llamar a la API de Schwab** (solo si el token está dentro del
  margen preventivo de 61 s de expirar).
- **Presupuesto**: ≤ 10 s en el peor caso (3 intentos × 3 s de timeout
  HTTP + 2 esperas de 0.5 s entre reintentos).

### Comportamiento interno (en orden)

1. Carga y valida la configuración — falla **antes** de cualquier red.
2. Inspecciona el token store: ausente o corrupto → resultado
   `reauth_required` sin intentar renovar.
3. Lee la validez restante del store; si está por encima del margen →
   `not_needed` **sin llamar a la API** y sin invalidar nada.
4. Adquiere el lock de autorización (no bloqueante): ocupado → exit 6.
5. Ejecuta el refresh vía schwabdev con hasta **2 reintentos** ante
   fallos transitorios (red/proveedor). Los tokens válidos existentes
   **jamás se descartan** por un fallo transitorio.
6. Clasifica el resultado y emite **una línea JSON** en stdout.
7. Emite eventos de auditoría en stderr (`renew_start` → terminal).

### Salida (stdout, una línea JSON, ≤ 300 bytes)

```json
{"outcome": "renewed", "expires_in_seconds": 1800, "retryable": false, "detail": "access_renewed"}
```

| Campo | Tipo | Valores |
|-------|------|---------|
| `outcome` | enum cerrado | `renewed` · `not_needed` · `transient_failure` · `reauth_required` |
| `expires_in_seconds` | int ≥ 0 o `null` | Nueva vida útil del access token; `null` salvo en `renewed` |
| `retryable` | bool | `true` **solo** cuando `outcome == "transient_failure"` |
| `detail` | enum cerrado | `access_renewed` · `still_valid` · `provider_unreachable` · `refresh_rejected` · `reauth_needed` · `store_absent` · `store_corrupted` |

### Códigos de salida

| Código | `outcome` | Significado para el agente |
|--------|-----------|---------------------------|
| 0 | `renewed` o `not_needed` | Éxito: el token está renovado o seguía vigente |
| 2 | — | Configuración faltante o mal formada (acción del dueño) |
| 3 | `reauth_required` | Refresh credential rechazado o store ausente/corrupto: **re-autorización humana requerida** |
| 6 | — | Otra renovación o autorización ya está en curso |
| 7 | `transient_failure` | Fallo transitorio de red/proveedor: reintentar más tarde es seguro |

### Semántica de cada resultado

- **`renewed`** (`detail: access_renewed`): el access token se renovó;
  `expires_in_seconds` trae la nueva vida útil (~1800 s). Si el
  proveedor rotó el refresh token, ya fue persistido en el store.
- **`not_needed`** (`detail: still_valid`): el token sigue vigente por
  encima del margen; **no hubo llamada de red** y no se invalidó nada.
  Tratar como éxito, no como error.
- **`transient_failure`** (`detail: provider_unreachable`, `retryable:
  true`): red o proveedor no disponibles tras agotar los 2 reintentos.
  Los tokens vigentes siguen intactos. Reintentar más tarde.
- **`reauth_required`** (`detail: refresh_rejected` / `reauth_needed` /
  `store_absent` / `store_corrupted`): la renovación automática es
  **imposible**. El agente NO debe seguir reintentando: debe notificar
  al dueño para que corra `schwab-mcp auth` (único paso que requiere
  humano, por constraint del proveedor). El estado persiste hasta la
  re-autorización.

### Eventos en stderr (auditoría)

```text
2026-10-19T14:00:00Z+00:00 auth_event=renew_start outcome=initiated detail=explicit_command
2026-10-19T14:00:02Z+00:00 auth_event=renewal_success outcome=ok detail=access token renewed
```

Cada intento emite exactamente un `renew_start` seguido de exactamente
un evento terminal (`renewal_success` | `renewal_failure`). Nunca
contienen secretos.

---

## `schwab-mcp auth-status`

Consulta de salud de autenticación en **una sola request**: estado,
vida útil del access token y del refresh token, y si hace falta
re-autorización. **Lectura estrictamente local**: no llama a la API,
nunca dispara una renovación.

```sh
uv run schwab-mcp auth-status
```

- **Argumentos**: ninguno. **stdin**: nunca se lee.
- **Presupuesto**: ≤ 2 s (lectura local de SQLite).

### Salida (stdout, una línea JSON)

```json
{"state": "valid", "access_expires_in_seconds": 1520, "refresh_expires_in_seconds": 412000}
```

| Campo | Tipo | Valores |
|-------|------|---------|
| `state` | enum cerrado | `valid` · `reauth_required` |
| `access_expires_in_seconds` | int ≥ 0 o `null` | Segundos restantes del access token; `null` si desconocido |
| `refresh_expires_in_seconds` | int ≥ 0 o `null` | Segundos restantes del refresh token (~7 días de vida); `null` si desconocido |

### Códigos de salida

| Código | `state` | Significado |
|--------|---------|-------------|
| 0 | `valid` | Credenciales utilizables; los campos indican cuánto resta (aunque sea poco) |
| 2 | — | Configuración faltante o mal formada |
| 3 | `reauth_required` | Store ausente o corrupto → re-autorización humana requerida |

> Nota: el rechazo del refresh token por el proveedor (`refresh_rejected`)
> **no es detectable localmente** — se manifiesta al usar `renew` o el
> servidor. Si `auth-status` dice `valid` pero una operación falla con
> `reauth_required`, creéle a la operación.

### Uso recomendado

Es la verificación **barata y previa**: consultala antes de operaciones
largas, después de una pausa larga del agente, o ante el primer síntoma
de fallo de autenticación. No consume cuota del proveedor.

---

## `schwab-mcp serve` (servidor MCP)

Servidor MCP de tipo **stdio**, headless. No registra tools en esta
versión, pero es el proceso que un cliente MCP (opencode, Claude
Desktop, etc.) lanza y con el que habla por stdio.

Al arrancar:

1. Valida la configuración (fail fast).
2. Verifica el token store: ausente/corrupto → sale con código
   específico **antes** del handshake MCP.
3. Renueva el access token si está vencido o dentro del margen
   (eventos `renew_start` → `renewal_success`/`renewal_failure` en
   stderr, trigger `margin_trigger`).
4. Valida el acceso real con `linked_accounts()` (< 5 s).
5. Conecta el transporte stdio y queda a la espera del cliente.

Si el refresh credential está rechazado, `serve` **no arranca**: sale
con mensaje claro pidiendo `schwab-mcp auth`. En ese estado, la
recuperación del agente es: notificar al dueño, y monitorear con
`auth-status` hasta que el estado vuelva a `valid` — a partir de ahí
todo funciona sin más acciones del agente.

En operación, la renovación automática es **transparente**: las
operaciones del agente no cambian de forma ni requieren pasos extra.

---

## `schwab-mcp auth` — solo para humanos

Flujo interactivo de autorización (browser + paste de URL). **Un agente
no debe intentar ejecutarlo**: requiere login humano en Schwab por
constraint del proveedor. Cuando un comando devuelve
`reauth_required`, la acción correcta del agente es notificar al dueño.

---

## Playbook de decisión para el agente

```text
Ante un fallo de autenticación en una operación:
1. uv run schwab-mcp auth-status        # diagnóstico barato, local
2. uv run schwab-mcp renew              # palanca de recuperación

Interpretación:
- exit 0 + renewed/not_needed  → continuar normalmente
- exit 7 + transient_failure   → reintentar luego (backoff); nada se perdió
- exit 6 (lock busy)           → esperar y reintentar
- exit 3 + reauth_required     → DETENER reintentos; notificar al dueño:
                                 "corré schwab-mcp auth"; monitorear con
                                 auth-status hasta state=valid
- exit 2 (configuración)       → acción del dueño (env del proceso)
```

## Referencias normativas

- Contrato CLI completo:
  [specs/002-automated-token-renewal/contracts/cli.md](../specs/002-automated-token-renewal/contracts/cli.md)
- Contrato de eventos de renovación:
  [specs/002-automated-token-renewal/contracts/events.md](../specs/002-automated-token-renewal/contracts/events.md)
- Modelo de datos (enums cerrados):
  [specs/002-automated-token-renewal/data-model.md](../specs/002-automated-token-renewal/data-model.md)
- [Guía de uso](./uso.md) · [Guía de instalación](./instalacion.md)