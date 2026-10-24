# Quickstart: `get_option_chain` (008)

Guía de validación end-to-end. Contrato completo:
[contracts/mcp-tools.md](contracts/mcp-tools.md). Modelo de datos:
[data-model.md](data-model.md).

## Prerrequisitos

```sh
uv sync                        # entorno
uv run schwab-mcp auth         # solo humanos; una vez, si no hay token
uv run schwab-mcp auth-status  # debe reportar token vigente
```

## S1 — Cadena por defecto (US1)

1. `uv run schwab-mcp serve` en una terminal.
2. Invocar la tool con solo `symbol` (p. ej. `"AAPL"`), sin filtros.
3. Verificar en la respuesta:
   - `filters.dte_max_effective == 60` y todos los `expiration.dte ≤ 60`;
   - ambas piernas (`call` y `put`) presentes por fila de strike;
   - ≤ `2 × max_strikes` (100) filas de strike por vencimiento, ordenadas
     por strike, centradas en `atm_strike`;
   - cada pierna con las columnas de `contract_fields` y las 5 griegas
     (`delta`..`rho`) informadas o `null` explícito;
   - una sola respuesta (sin paginación) y `underlying_price` presente.

## S2 — Delta objetivo + tipo (US2)

1. Invocar con `symbol`, `option_type="puts"`, `delta_target=0.20`.
2. Verificar: solo piernas `put`; por vencimiento ≤ 5 strikes alrededor
   del contrato con delta ≈ -0.20 (|delta| ≈ 0.20); sin strikes fuera de
   esa ventana.
3. Repetir con `option_type="both"` y `delta_target=0.20`: hasta 5
   strikes de CALLs **y** hasta 5 de PUTs por vencimiento (ventana por
   tipo, clarificación 2026-10-23).
4. **Validación live (SC-005)**: repetir los pasos 1–3 contra la cadena
   real de un subyacente líquido (con token vigente) y confirmar los
   mismos invariantes; los fixtures de la suite cubren los bordes (delta
   en el límite de la curva, strikes faltantes).

## S3 — Límites explícitos (US3)

1. `max_strikes=10`: máximo 10 filas de strike por lado del dinero por
   vencimiento.
2. `dte_max=7`: solo vencimientos con `dte ≤ 7`; si el vencimiento más
   próximo vence más lejos → resultado `no_expirations_in_range`
   estructurado, no error genérico.
3. `dte_max=120`: incluye vencimientos más lejanos que el default.

## S4 — Edge cases

| Invocación | Esperado |
|---|---|
| `symbol="ZZZZZZ"` (sin opciones) | `no_options_listed` estructurado |
| `delta_target=1.5` | error de validación antes de upcall |
| `max_strikes=0` | error de validación |
| `option_type="strangles"` | error de validación |
| Fuente caída (ver `tests/integration/test_failures.py` para el patrón) | error estructurado sin cadena parcial (FR-013) |
| Vencimiento entero sin datos en payload | error estructurado sin cadena parcial |

## Gates de tests

```sh
uv run pytest tests/unit/test_options_chain_validation.py \
              tests/unit/test_options_chain_mapping.py \
              tests/unit/test_options_chain_filters.py \
              tests/unit/test_options_chain_delta.py   # unit
uv run pytest tests/integration/test_options_chain.py  # integración
uv run pytest tests/performance/test_options_chain_budgets.py -m performance  # presupuestos
uv run pytest                                          # suite completa: verde, 0 skipped
```

## Referencias

- Registro de la tool: `src/schwab_mcp/server.py` (patrón wrapper de
  `get_open_positions` / `get_transaction_history`).
- Consumo para agentes: `docs/tools.md` (sección nueva de la tool,
  incluida en el commit de la feature).
