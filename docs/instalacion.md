# Guía de instalación

Instalación y configuración de `schwab-mcp`, el servidor MCP stdio local
para acceder a la API de Schwab.

## Requisitos

- **Python 3.11 o superior** (lo exige la librería `schwabdev`).
- **[uv](https://docs.astral.sh/uv/)** para gestionar el entorno y las
  dependencias.
- Una **aplicación registrada y aprobada** en
  [developer.schwab.com](https://developer.schwab.com). La aprobación
  manual de Schwab puede tardar varios días: empezá este trámite primero.
- macOS o Linux (el lock de autorización usa `fcntl`).

## 1. Instalar el proyecto

```sh
git clone <repository-url> schwab-mcp
cd schwab-mcp
uv sync
```

`uv sync` crea el entorno virtual e instala `schwabdev`, el SDK de MCP y
las herramientas de test.

## 2. Configurar la aplicación en el portal de Schwab

En [developer.schwab.com](https://developer.schwab.com) → **My Apps**:

1. La app debe estar en estado **`Ready for Use`**. Los estados
   `Approved - Pending` significan "en revisión manual": mientras dure,
   el login OAuth falla con errores poco claros (por ejemplo
   `4001 Session rejected`).
2. Agregá **ambas APIs** a la app: *Accounts and Trading Production* y
   *Market Data Production*.
3. Callback URL: `https://127.0.0.1` **sin barra final**. La librería
   `schwabdev` rechaza callbacks que terminan en `/`. Si el portal muestra
   la URL con barra, ignorá el detalle visual: en tu configuración local
   va siempre sin barra.
4. Copiá el **App Key** y el **App Secret** de esta misma app. Si tenés
   varias apps en el portal, verificá que key y secret pertenezcan a la
   misma: mezclarlas produce fallos difíciles de diagnosticar.

## 3. Credenciales

Las credenciales se leen **exclusivamente de variables de entorno**
(FR-008). Guardalas en un archivo **fuera del repositorio**, nunca
commiteado:

```sh
mkdir -p ~/.schwab-mcp && chmod 700 ~/.schwab-mcp
cat > ~/.schwab-mcp/env <<'EOF'
export SCHWAB_APP_KEY=TU_APP_KEY
export SCHWAB_APP_SECRET=TU_APP_SECRET
export SCHWAB_CALLBACK_URL=https://127.0.0.1
EOF
chmod 600 ~/.schwab-mcp/env
```

| Variable | Obligatoria | Default | Descripción |
|----------|-------------|---------|-------------|
| `SCHWAB_APP_KEY` | sí | — | App key (client ID) de tu app de Schwab |
| `SCHWAB_APP_SECRET` | sí | — | App secret, de la **misma** app |
| `SCHWAB_CALLBACK_URL` | no | `https://127.0.0.1` | Callback registrado en el portal. Sin barra final, `https` |
| `SCHWAB_TOKEN_DB` | no | `~/.schwab-mcp/tokens.db` | Ruta del store de tokens (SQLite). Fuera del repo; permisos forzados a `0o600` |

## 4. Cargar las credenciales en el shell

El programa **no lee el archivo** `~/.schwab-mcp/env`: lee variables de
entorno del proceso. El archivo es solo el mecanismo para cargarlas:

```sh
set -a; source ~/.schwab-mcp/env; set +a
```

> **Regla de oro**: cada vez que edites el archivo, o en **cada terminal
> nueva**, volvé a hacer `source`. La shell conserva los valores viejos
> de sesiones anteriores y mezclarlos produce errores confusos. Antes de
> correr cualquier comando, verificá:
>
> ```sh
> echo "$SCHWAB_APP_KEY"       # la key correcta
> echo "$SCHWAB_CALLBACK_URL"  # sin barra final
> ```

## 5. Verificar la instalación

```sh
uv run schwab-mcp --help      # debe listar los subcomandos: auth, serve
uv run pytest -q              # suite completa: todos los tests en verde
```

## Siguiente paso

- [Guía de uso](./uso.md) — primera autorización, `serve`, conexión de
  un cliente MCP y solución de problemas.