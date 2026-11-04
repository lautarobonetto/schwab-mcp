# Graph-First Code Discovery (codebase-memory-mcp)

When analyzing code structure — who calls what, blast radius, duplicated
patterns, dead code, diff impact — query the codebase-memory knowledge
graph **before** any grep/glob/file-read. AGENTS.md already mandates
this; this rule exists because a real session skipped it end to end.

Trigger phrases that must route to the graph: "who calls X", "what uses
X", "is it safe to change X", "does this pattern exist elsewhere",
"what does this refactor touch", "find duplicated logic".

## Incorrect

TD-010 (price_history DRY refactor): the entire assess → fix → test
cycle ran on raw `read`/`grep`. The blast-radius question ("is
`_selection_detail` used outside `price_history.py`?") was answered by
grepping the whole repo, and "does the same fail-event pattern live in
`transactions.py`?" was left as an open question instead of being
answered with one directed query. The graph was only touched at the end
to re-index, i.e. used as a warehouse, never as a discovery tool.

```sh
grep -rn "_selection_detail(" src/          # blast radius by brute force
grep -rn "detail=f\"{detail} \"" src/       # duplication hunt by hand
```

## Correct

One `trace_path` call answers the blast-radius question (~500 tokens vs
~80K of grep+reads), `search_graph` with degree filters finds sibling
duplication structurally, and `detect_changes()` maps a diff to affected
symbols before a refactor or commit.

```js
// who calls it / is it safe to change
await tools["codebase-memory-mcp"].trace_path({
  project: "<project-name>", function_name: "_selection_detail",
  direction: "inbound",
});

// structural duplication hunt (high fan-in / fan-out)
await tools["codebase-memory-mcp"].search_graph({
  project: "<project-name>", min_degree: 10,
  relationship: "CALLS", direction: "outbound",
});

// what does this diff touch
await tools["codebase-memory-mcp"].detect_changes({});
```

Rules of engagement:

1. **Session start / after compaction**: `list_projects` or
   `index_status` first; pick the project whose `root_path` contains the
   working directory and pass its `name`.
2. **Grep fallback is legitimate** only for string literals, error
   messages, config values, and non-code files — not for structural
   questions.
3. **Verify material claims**: graph results mix CALLS with docstring
   MENTIONS; confirm with `get_code_snippet` before claiming behavior,
   and call `check_index_coverage` once with the evidence paths.
4. **Tiered evidence** (Scout/Verify/Auditor) per the codebase-memory
   skill; never make absence or exhaustive claims from a Scout lookup.

## Reference

- `.config/opencode/skills/codebase-memory/` — decision matrix and workflows
- `AGENTS.md` § Codebase Knowledge Graph — priority order (search_graph → trace_path → get_code_snippet)
- Session evidence: `.specify/bugs/td-010-price-history-fail-dry/` (the session that skipped all of this)