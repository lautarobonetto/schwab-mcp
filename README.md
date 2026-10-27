# schwab-mcp

Servidor **MCP local (stdio)** para acceder a la información de cuenta
de [Charles Schwab](https://www.schwab.com) desde un cliente de IA:
posiciones, historial de transacciones y cadenas de opciones. Todo corre
en tu máquina: sin sockets entrantes y con credenciales que nunca salen
de tu equipo.

## Documentación

| Tema | Dónde |
|------|-------|
| Instalación y configuración | [docs/instalacion.md](docs/instalacion.md) |
| Uso, autorización y diagnóstico | [docs/uso.md](docs/uso.md) |
| Referencia de tools para agentes de AI | [docs/tools.md](docs/tools.md) |
| Historia de cambios | [docs/CHANGELOG.md](docs/CHANGELOG.md) |
| **Release / distribución a destinatarios** | [docs/release-mantenimiento.md](docs/release-mantenimiento.md) |

## Comandos

```sh
uv sync                        # instalar entorno
uv run pytest                  # suite completa
uv run schwab-mcp auth         # autorización interactiva
uv run schwab-mcp serve        # servidor MCP sobre stdio
uv run schwab-mcp auth-status  # diagnóstico local de credenciales
uv run schwab-mcp renew        # renovación explícita
```

## Paquete para destinatarios

Los destinatarios que solo reciben el paquete de distribución siguen los
manuales en inglés incluidos dentro del archive (también en
[docs/release/](docs/release/README.md)). El paquete se construye con
`uv run schwab-mcp-release build` — ver
[docs/release-mantenimiento.md](docs/release-mantenimiento.md).

## Seguridad de credenciales

Las credenciales de Schwab y los tokens viven únicamente en
`~/.schwab-mcp/tokens.db` (configurable), jamás en logs, outputs ni
repositorio. La constitución del proyecto gobierna todos los cambios:
[.specify/memory/constitution.md](.specify/memory/constitution.md).
