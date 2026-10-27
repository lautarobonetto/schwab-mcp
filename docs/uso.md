# Guía de uso

Cómo autorizar, operar y diagnosticar `schwab-mcp`. Asumimos la
instalación completada según la [guía de instalación](./instalacion.md).

## Comandos

| Comando | Para qué |
|---------|----------|
| `uv run schwab-mcp --help` | Ayuda; **muestra la versión instalada** — incluila siempre al reportar un problema |
| `uv run schwab-mcp auth` | Autorización interactiva (browser + paste de URL) |
| `uv run schwab-mcp serve` | Servidor MCP sobre stdio, headless |

## Primera autorización

```sh
set -a; source ~/.schwab-mcp/env; set +a
uv run schwab-mcp auth
```

El flujo es **paste-the-redirect-URL**: el servidor nunca abre sockets de
entrada; el redirect del browser se captura a mano.

1. El CLI valida la configuración y adquiere el lock de autorización.
2. Imprime la **URL de autorización completa** (incluye el client_id —
   es público por diseño de OAuth) y abre el browser.
3. Iniciás sesión en Schwab con tus credenciales de **brokerage** (no las
   del portal de developers) y aprobás la app; completá el 2FA si lo pide.
4. El browser intenta ir a `https://127.0.0.1/?code=...&session=...` y
   **falla la conexión**. Es lo esperado: no hay nada escuchando.
5. Copiá la **URL completa de la barra de direcciones** y pegala en el
   prompt `Paste the redirect URL:` de la terminal.
6. El CLI hace el exchange del código y guarda el token set.

**Resultado esperado**: `Authorization successful. Schwab API access is
configured.` y exit code `0`.

Verificación:

```sh
ls -l ~/.schwab-mcp/tokens.db   # existe, permisos -rw------- (600)
```

### Reglas de oro del flujo

- **Una sola corrida**: la URL que abrís en el browser y la terminal donde
  pegás el redirect deben ser **la misma corrida** de `auth`. Mezclar URLs
  de corridas anteriores produce `invalid_grant: RedirectURI does not
  match` en el exchange.
- **Sin pestañas viejas**: cerrá todas las pestañas de Schwab antes de
  empezar; URLs de intentos previos contaminan el flujo.
- **Si el login rechaza la sesión** (`error_code: 4001`, `Session
  rejected` / `assertion_rejected`) con la app en `Ready for Use`: son
  cookies viejas del browser. Copiá la URL impresa en la terminal y
  abrila en una **ventana incógnita**, o borrá las cookies de
  `schwab.com` / `schwabapi.com`.

## Uso diario: el servidor MCP

```sh
uv run schwab-mcp serve
```

Al arrancar, el servidor:

1. Valida la configuración (fail fast).
2. Verifica el token store: ausente o corrupto → exit con mensaje claro.
3. Renueva el access token si está vencido (evento `renewal_success`).
4. Valida el acceso con una lectura real a la API (proactivo, < 5 s).
5. Conecta el transporte stdio y **queda esperando un cliente MCP**.

En una terminal sin cliente, el proceso simplemente queda vivo esperando
stdin — es el comportamiento correcto. Cortalo con `Ctrl+C`.

`serve` nunca abre browser, nunca pide input y nunca arranca un flujo de
autorización implícito. Si hace falta re-autorizar, sale con exit code
`4` y el mensaje `Run schwab-mcp auth`.

### Conectar un cliente MCP

Configurá el servidor en tu cliente MCP (Claude Desktop, opencode, etc.):

```json
{
  "mcpServers": {
    "schwab": {
      "command": "uv",
      "args": [
        "run", "--directory", "/ruta/a/schwab-mcp", "schwab-mcp", "serve"
      ],
      "env": {
        "SCHWAB_APP_KEY": "TU_APP_KEY",
        "SCHWAB_APP_SECRET": "TU_APP_SECRET",
        "SCHWAB_CALLBACK_URL": "https://127.0.0.1"
      }
    }
  }
}
```

El bloque `env` reemplaza al archivo `~/.schwab-mcp/env` para el proceso
del servidor: el cliente MCP lanza `serve` con su propio entorno.

## Ciclo de tokens

- **Access token**: ~30 minutos. Se renueva solo, sin intervención
  (eventos `renewal_success` / `renewal_failure` en stderr).
- **Refresh token**: ~7 días. Vencido, hay que re-autorizar:

```sh
uv run schwab-mcp auth
```

Un intento de re-auth fallido no toca el token set existente: si la
autorización nueva no se completa, los tokens vigentes siguen intactos.

## Comandos de renovación

Diseñados para agentes no interactivos. Ninguno abre browser, lee stdin
ni abre sockets. Ambos imprimen exactamente **una línea JSON** en stdout
y usan stderr para mensajes auxiliares.

El contrato completo está en
[specs/002-automated-token-renewal/contracts/cli.md](../specs/002-automated-token-renewal/contracts/cli.md).
La referencia detallada para agentes de AI (campos JSON, semántica de
cada resultado, playbook de decisión) está en
[docs/tools.md](./tools.md).

### `schwab-mcp renew`

Renueva el token de acceso de forma no interactiva. Carga configuración,
verifica el store, e intenta el refresh con hasta 2 reintentos ante
fallos transitorios.

```sh
uv run schwab-mcp renew
```

**Códigos de salida:**

| Código | Significado |
|--------|------------|
| 0 | `renewed` o `not_needed` (aún vigente) |
| 2 | Configuración faltante o mal formada |
| 3 | Requiere re-autorización: `reauth_required` (correr `schwab-mcp auth`) |
| 6 | Otra renovación o autorización ya en curso (`busy`) |
| 7 | Error transitorio: `transient_failure` (el agente puede reintentar más tarde) |

### `schwab-mcp auth-status`

Consulta de salud de autenticación **local** (sin red). Lee el store de
tokens y devuelve el estado en ≤ 2 segundos.

```sh
uv run schwab-mcp auth-status
```

**Códigos de salida:**

| Código | Significado |
|--------|------------|
| 0 | `valid` (los campos indican tiempo restante) |
| 2 | Configuración faltante o mal formada |
| 3 | Requiere re-autorización: `reauth_required` (store ausente o corrupto) |

## Modos de falla

Cada falla imprime su mensaje propio, accionable, y sale con código
específico. Ninguna se cuelga ni muestra tracebacks.

| Falla | Exit | Recuperación |
|-------|------|--------------|
| Falta `SCHWAB_APP_KEY` / `SCHWAB_APP_SECRET` | 2 | Completá `~/.schwab-mcp/env` y re-sourceá |
| Valores de configuración inválidos | 2 | Corregí los valores en el env |
| Autorización cancelada | 3 | Re-corré `schwab-mcp auth` |
| Re-autorización requerida | 4 | Corré `schwab-mcp auth` para renovar tokens |
| Token store corrupto | 5 | Corré `schwab-mcp auth` (el store se trata como ausente) |
| Autorización concurrente | 6 | Otra autorización ya está corriendo; esperala |
| Fallo de conectividad | 7 | Revisá la red y reintentá; el store no se toca |

## Solución de problemas

| Síntoma | Causa | Solución |
|---------|-------|---------|
| `ValueError: callback_url cannot be a path (endswith "/")` | Versión vieja del paquete: la barra final ya se normaliza en `load_config()` | Actualizá el código; con la versión actual ambas formas funcionan |
| `invalid_grant: RedirectURI does not match` | Mezclaste URLs de corridas distintas | Corrida fresca: abrí la URL impresa por **esa** corrida y pegá el redirect en **esa misma** terminal |
| `4001 Session rejected` en el login | Cookies viejas del browser (con app `Ready for Use`) | Ventana incógnito con la URL impresa, o limpiá cookies de `schwab.com` |
| El CLI usa valores que ya cambiaste en el env | La shell conserva las variables viejas | `set -a; source ~/.schwab-mcp/env; set +a` y verificá con `echo` |
| `invalid_client` en el exchange | App key y app secret de apps distintas | Copiá **ambos** de la misma app en el portal |
| Revisión que no termina | Estado `Approved - Pending` | Esperá a `Ready for Use` en el portal; si persiste, `traderapi@schwab.com` |

## Seguridad

- Credenciales solo por entorno, en memoria, jamás escritas a disco.
- Token store y env con permisos `0o600`; directorio `0o700`.
- Filtro de redacción en todos los logs: app secret, tokens y códigos de
  autorización nunca aparecen en la salida.
- Sin sockets de entrada: el diseño paste-the-redirect-URL elimina el
  listener HTTP local.
- Alcance read-only: el token autorizado tiene el mínimo privilegio
  necesario.

## Referencias

- [Interfaz para agentes de AI](./tools.md) — referencia completa de
  comandos y campos JSON para consumo por agentes
- [Changelog](./CHANGELOG.md) — progreso del código por versión
- [Guía de instalación](./instalacion.md)
- [Quickstart del spec](../specs/001-schwab-oauth-access/quickstart.md)
  — escenarios de validación end-to-end
- [Contrato CLI](../specs/001-schwab-oauth-access/contracts/cli.md)
- [Contrato de configuración](../specs/001-schwab-oauth-access/contracts/configuration.md)
- [Contrato de eventos](../specs/001-schwab-oauth-access/contracts/events.md)