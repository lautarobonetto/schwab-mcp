---
title: Filter Server-Side Before Fetching Full History
impact: HIGH
tags: [mcp, schwab, tool-usage, efficiency]
---

# Filter Server-Side Before Fetching Full History

When tracing a single instrument, position chain, or entity through transaction
history, use the tool's server-side filter parameters (e.g. `symbol` in
`get_transaction_history`) before falling back to unfiltered requests with
manual pagination. Unfiltered fetches multiply API calls and context usage
(5 paginated requests / 200+ movements where 1 filtered request / 13 movements
sufficed) and force client-side filtering that the server already does.

## Incorrect

This includes the "preemptive batch" rationalization: do not fetch one broad
unfiltered window "to resolve several chains at once". Resolve each suspected
orphan with a targeted filtered query first; widen only per-chain if it stays
unresolved.

Fetching the entire date range unfiltered and filtering locally, paginating
until exhaustion:

```js
// 5 requests, 204 movements, all instruments — only 13 were needed
for (let off = 0; ; off += 50) {
  const r = await tools.schwab.get_transaction_history({
    start_date: "2026-01-01", end_date: "2026-07-22", offset: off
  });
  // ... filter m.symbol.includes("NOK") client-side
}
```

## Correct

Check the tool signature for a filter parameter and use it first. Only fetch
unfiltered history if the filtered result still leaves the chain unresolved.

```js
// 1 request, only the relevant movements
const r = await tools.schwab.get_transaction_history({
  start_date: "2026-01-01", end_date: "2026-07-22",
  symbol: "NOK"
});
```

## Reference

- `docs/tools.md` — documented MCP interface for agents
- AGENTS.md orphan-chain rule: extend the window with targeted queries, not brute force
