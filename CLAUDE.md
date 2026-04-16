# CLAUDE.md

## Project: paced

A three-layer MCP server for endurance training data analysis using Strava API.

## Architecture

- `mcp-server/` — Layer 1 (Strava API) + Layer 2 (data processing), single Python package `paced_mcp`
- `agent-core/` — Layer 3 (AI agent logic), Python package `paced_agent`
- `docs/contracts/` — Interface contracts between layers (tools.yaml, athlete_profile.yaml, training_state.yaml)
- `examples/` — Sample config files

## Key Design Decisions

- Layer 2 is embedded inside Layer 1 (not a separate service). Raw Strava data never enters LLM context.
- Safety limits are enforced in code (`safety_guard.py`), not by LLM prompts.
- Cardiac drift uses Joe Friel's definition: HR/pace ratio change between halves. >5% = aerobic base deficit.
- Token persistence uses SQLite (`~/.paced/paced.db`).
- User config is `~/.paced/athlete_profile.yaml` (user-editable). System state is `~/.paced/training_state.yaml` (auto-maintained).

## Development

```bash
# MCP server
cd mcp-server && pip install -e ".[dev]"

# Agent
cd agent-core && pip install -e ".[dev]"

# Run tests
pytest mcp-server/tests/
pytest agent-core/tests/
```

## Current Phase

Phase 1: Strava OAuth + activity summary fetch. See `docs/SPEC.md` for full roadmap.

## Style

- Python 3.11+
- Type hints everywhere
- Docstrings on public functions
- Tests in `tests/` directories alongside each package
