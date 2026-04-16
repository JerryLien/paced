# paced — System Specification

**Project Codename:** paced (Open-source AI Endurance Training Data System)

## 1. Project Overview

This project builds an automated AI training data analysis tool. By integrating
the Strava API, a data processing pipeline, and a large language model (LLM),
the system automatically fetches a user's historical training records (including
running, cycling, swimming, and other cross-training data), filters and cleans
the data, and provides customized training suggestions and race preparation
reference schedules.

- **License:** Apache License 2.0
- **Disclaimer (Core Principle):** This system is a "data analysis assistance
  tool." Its output constitutes training suggestions, never medical or
  professional sport prescriptions. Users should prioritize their own
  perceived exertion before executing any training and seek help from a
  qualified coach or medical professional when necessary.

## 2. Architecture Design

The system uses a three-tier decoupled architecture, combining existing
open-source solutions:

### Layer 1: Data Fetching & Interface Layer

- **Technology:** Model Context Protocol (MCP) Server
- **Reference:** `strava-activity-mcp-server`
- **Responsibilities:**
  - Handle Strava API OAuth 2.0 authorization and automatic Refresh Token renewal.
  - Wrap Strava API endpoints (e.g. `/activities`, `/streams`) as standard MCP Tools.
  - Handle API Rate Limit (100 req/15 min, 1000 req/day) retry and queuing.

### Layer 2: Processing & Context Layer (embedded in Layer 1)

- **Technology:** Data preprocessing and feature extraction (ETL).
- **Reference:** `strava-langchain`
- **Deployment:** Imported as a Python module by Layer 1's MCP server. Layer 2
  does not run as a separate service (Architecture Decision: Option A).
- **Responsibilities:**
  - Convert raw JSON (per-second HR, pace, GPS) into Pandas DataFrames.
  - Noise reduction and compression: remove GPS anomalies, calculate HR zone
    time ratios (Z1–Z5), average cadence, cardiac drift rate, etc.
  - Compress large time-series data into token-friendly summary reports to
    avoid exceeding the LLM's context window.

### Layer 3: Orchestration & Agent Layer

- **Technology:** AI Agent (recommended: Claude via MCP)
- **Reference:** `coachleo` high-level logic.
- **Responsibilities:**
  - **State management:** Track target race dates and current training phase
    (base, build, peak, taper, recovery).
  - **Reasoning and generation:** Synthesize data insights from Layer 2,
    combine with built-in periodization prompt logic, dynamically adjust
    next week's paces and mileage, and output a reference schedule.

## 3. Directory Structure

Monorepo structure for version control and local quick start:

```
paced/
├── .env.example
├── README.md
├── LICENSE                       # Apache 2.0
├── docs/
│   ├── SPEC.md
│   ├── DISCLAIMER.md
│   └── contracts/
│       ├── tools.yaml
│       ├── athlete_profile.yaml
│       └── training_state.yaml
├── mcp-server/                   # [Layer 1 + Layer 2]
│   ├── pyproject.toml
│   └── src/paced_mcp/
│       ├── server.py
│       ├── auth/
│       ├── strava/
│       ├── processing/           # Layer 2 embedded module
│       └── tools/
├── agent-core/                   # [Layer 3]
│   ├── pyproject.toml
│   └── src/paced_agent/
│       ├── main.py
│       ├── state_manager.py
│       ├── safety_guard.py
│       └── prompts/
│           ├── base_system.md
│           ├── disclaimers.md
│           └── periodization/
└── examples/
```

## 4. Core Workflow

1. **Trigger:** User sends a command via terminal or Claude Desktop:
   "Analyze my last two weeks and plan next week's race prep schedule."
2. **Call:** Agent (Layer 3) determines it needs data, sends an MCP request
   to the MCP Server (Layer 1).
3. **Fetch:** MCP Server uses a valid token to fetch the past 14 days of
   activity records and detailed segment data from the Strava API.
4. **Clean:** Raw data is processed by the embedded Layer 2, producing a
   structured summary such as: "Last week total 45 km, weekend long run at
   5:30/km pace with HR staying in Z2, but cadence dropped 5% in the final 3 km."
5. **Reason:** Agent receives the summary, determines fitness status is good,
   calculates that next week's long run mileage can increase by 10%, and
   generates a suggested schedule including recovery-day cross-training
   (e.g. easy cycling).
6. **Output:** Returns a Markdown reference schedule to the user.

## 5. Implementation Phases

### Phase 0: Contract Definition (complete)
- MCP Tool schemas defined (`docs/contracts/tools.yaml`)
- User profile schema defined (`docs/contracts/athlete_profile.yaml`)
- System state schema defined (`docs/contracts/training_state.yaml`)

### Phase 1: Foundation
- Complete Strava API application registration.
- Implement OAuth authorization flow; ensure stable fetching of basic
  activity summaries.

### Phase 2: Data Refinement
- Implement activity streams (detailed time-series) fetching.
- Pandas data cleaning pipeline; validate correct calculation of valuable
  training metrics; significantly reduce tokens fed to the LLM.

### Phase 3: Agent Integration
- Write system prompts for endurance sport periodization.
- Complete three-layer integration; ensure users can drive the entire
  data-fetch-and-schedule flow via natural language.
- Finalize GitHub README disclaimer and usage guide.

### Phase 4: Triathlon Support
- Bike and swim metrics parity with running.

### Phase 5: Multi-user / Household Mode
- Support multiple athlete profiles under one installation.

## 6. Key Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Layer 2 deployment | Embedded in Layer 1 (Option A) | Raw streams data (100k+ points) never enters LLM context. Agent sees only cleaned summaries. Simpler deployment. |
| License | Apache 2.0 | Maximizes community adoption. Core value is in prompts and training logic, not code. |
| Token persistence | SQLite | Consistent with rate limit logging; single-file, zero-config. |
| State files | YAML (split into 2 files) | `athlete_profile.yaml` is user-editable intent; `training_state.yaml` is system-maintained observation. Separation prevents user edits from corrupting computed state. |
| Cardiac drift definition | Joe Friel (HR/pace ratio, second half vs first half) | One definition, documented. >5% indicates aerobic base deficit. |
| Safety enforcement | Code-level post-processing | `safety_guard.py` enforces hard limits after agent output. Not reliant on LLM prompt compliance. |
