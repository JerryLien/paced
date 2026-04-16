# paced

A three-layer MCP server for endurance training data analysis.

Fetches your Strava data, compresses it into LLM-friendly context,
and lets an AI agent help you reason about training load and periodization.

> **This is not coaching. This is not medical advice.**
> See [Disclaimer](#disclaimer) before reading further.

## What it does

`paced` gives an AI agent structured access to your training history
without blowing up its context window. Raw time-series data
(per-second heart rate, pace, GPS) stays in the data layer;
the agent only sees distilled metrics like Z2 time ratio,
cardiac drift, and acute-to-chronic workload ratio.

You ask questions like:

- "Analyze my last two weeks. Am I ready to increase volume?"
- "Plan next week's workouts toward my March marathon."
- "Why did my easy run yesterday feel hard?"

The agent reads your data through MCP tools, applies a periodization
style you chose (Daniels / Pfitzinger / Friel / Hanson / custom),
and returns a reference schedule — bounded by safety limits
you define in your profile.

## Architecture

Three layers, decoupled by contracts:

```
┌─────────────────────────────────────────┐
│  Layer 3: Agent (Claude, local or API)  │
│  - Reads prompts + state                │
│  - Calls MCP tools                      │
│  - Produces reference schedule          │
└──────────────┬──────────────────────────┘
               │ MCP protocol
┌──────────────┴──────────────────────────┐
│  Layer 1+2: paced-mcp server            │
│  ┌────────────────────────────────────┐ │
│  │ Processing (pandas, metrics)       │ │
│  └────────────────────────────────────┘ │
│  ┌────────────────────────────────────┐ │
│  │ Strava client (OAuth, rate limit)  │ │
│  └────────────────────────────────────┘ │
└──────────────┬──────────────────────────┘
               │ HTTPS
        ┌──────┴──────┐
        │ Strava API  │
        └─────────────┘
```

Full spec: [`docs/SPEC.md`](docs/SPEC.md)
Contracts: [`docs/contracts/`](docs/contracts/)

## Requirements

- Python 3.11+
- Strava API application (free, [register here](https://www.strava.com/settings/api))
- An LLM with MCP support (Claude Desktop, Claude Code, or any MCP-capable client)

## Quick start

```bash
git clone https://github.com/JerryLien/paced.git
cd paced

# Install MCP server
cd mcp-server
pip install -e .

# Install agent (optional — you can use Claude Desktop/Code directly)
cd ../agent-core
pip install -e .

# Copy config
cp ../.env.example ../.env
# Edit .env: add STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET

# First-time OAuth (must be on a machine with a browser)
paced-mcp auth init

# Copy profile template
mkdir -p ~/.paced
cp ../examples/sample_athlete_profile.yaml ~/.paced/athlete_profile.yaml
# Edit athlete_profile.yaml with your races, zones, preferences
```

Then register the server with your MCP client. For Claude Desktop,
add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "paced": {
      "command": "paced-mcp",
      "args": ["serve"]
    }
  }
}
```

## Configuration

Two files control behavior:

- `~/.paced/athlete_profile.yaml` — **you edit this**.
  Races, zones, periodization style, safety limits.
  See [schema](docs/contracts/athlete_profile.yaml).

- `~/.paced/training_state.yaml` — **system maintains this**.
  Fitness snapshot, phase state, decision log. Don't hand-edit.
  See [schema](docs/contracts/training_state.yaml).

## MCP tools exposed to the agent

| Tool | Purpose |
|------|---------|
| `get_recent_training_summary` | Aggregated metrics over N days |
| `get_activity_detail` | Deep analysis of a single activity |
| `get_athlete_baseline` | Personal HR zones, pace baselines, fitness trend |
| `get_race_calendar` | Target races and current training phase |

Full schemas in [`docs/contracts/tools.yaml`](docs/contracts/tools.yaml).

## Design principles

1. **Raw data never touches the LLM.** Layer 2 pre-computes all
   metrics, flags notable events, and returns structured summaries.
2. **Safety limits are code, not prompts.** Weekly volume caps,
   long-run percentages, recovery day minimums are enforced by
   `safety_guard.py` after the agent produces output. Agent output
   that violates limits is rewritten, not trusted.
3. **Periodization is pluggable.** Swap training philosophies by
   changing one YAML field. New styles are markdown files —
   contributions welcome.
4. **Cardiac drift uses Joe Friel's definition** (HR/pace ratio
   change between halves). Other definitions exist; we pick one
   and document it.

## Roadmap

- [x] Phase 0: Contracts defined
- [ ] Phase 1: Strava OAuth + activity summary fetch
- [ ] Phase 2: Streams fetch, pandas pipeline, metrics calculation
- [ ] Phase 3: Agent integration, prompt library, safety guard
- [ ] Phase 4: Triathlon support (bike/swim metrics parity)
- [ ] Phase 5: Multi-user / household mode

## Disclaimer

**`paced` is a data analysis tool. It is not a coach.
It is not a medical device. It does not prescribe training.**

Output from `paced` is a *reference schedule* derived from your
own historical data and a periodization template you selected.
It has no knowledge of your sleep, stress, illness, injury history,
family obligations, or how your body feels today.

Before following any suggestion from this tool:

- Listen to your body. Perceived exertion always overrides any
  number this tool produces.
- Consult a qualified coach or medical professional for anything
  beyond recreational training planning.
- If you have any cardiac, metabolic, or musculoskeletal condition,
  talk to a physician before using output from this tool to
  structure your training.

The authors accept no responsibility for injury, illness, or
underperformance resulting from use of this software. See
[`docs/DISCLAIMER.md`](docs/DISCLAIMER.md) for the full statement.

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Contributing

Contributions welcome — especially new periodization styles,
metric definitions, and sport-specific processing. Open an
issue before starting significant work so we can align on
the contract first.
