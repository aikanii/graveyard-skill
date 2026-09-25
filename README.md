<div align="center">

# 🪦 Project Graveyard

**A local-first agent skill and CLI for finding abandoned projects, explaining why they stalled, and identifying the one most worth shipping.**

[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
![Dependencies: stdlib only](https://img.shields.io/badge/dependencies-stdlib%20only-success)
![Network: offline](https://img.shields.io/badge/scanner-offline-success)

[Quick start](#quick-start) · [How it works](#how-it-works) · [CLI reference](#cli-reference) · [Agent skill](#agent-skill) · [Development](#development)

</div>

---

Project Graveyard scans local Git repositories, separates active and completed
work from abandoned projects, and derives evidence-based causes from repository
history. It then assigns each abandoned project a **pulse score** representing
how close it may be to shipping.

The scanner is intentionally small and auditable:

- **Local only** — no API calls, telemetry, or remote Git access.
- **Read-only repository analysis** — source repositories are never mutated.
- **Metadata based** — source-file contents are not read.
- **Zero runtime dependencies** — one Python file using only the standard library.
- **Agent ready** — includes a complete [`SKILL.md`](SKILL.md) workflow for
  interviews, reports, resurrection planning, and relapse tracking.

> [!IMPORTANT]
> Causes of death are forensic heuristics, not statements about motivation.
> Always consider the reported evidence and confirm ambiguous conclusions with
> the project owner.

## Table of contents

- [Features](#features)
- [Quick start](#quick-start)
- [Project classification](#project-classification)
- [Cause detection](#cause-detection)
- [How it works](#how-it-works)
- [Pulse score](#pulse-score)
- [CLI reference](#cli-reference)
- [Structured JSON output](#structured-json-output)
- [Resurrection state](#resurrection-state)
- [Agent skill](#agent-skill)
- [Privacy and security](#privacy-and-security)
- [Limitations](#limitations)
- [Development](#development)
- [Project structure](#project-structure)
- [License](#license)

## Features

- Discovers Git repositories below one or more explicitly selected roots.
- Detects nested repositories without traversing dependency and build caches.
- Filters cloned or foreign repositories using commit-author email ownership.
- Recognizes additional identities through repeatable `--me` options.
- Separates active, finished, abandoned, empty, and unversioned projects.
- Detects eight common abandonment patterns from Git metadata.
- Names likely “shiny object” handoffs when a newer project immediately follows
  an older project’s final commit.
- Ranks abandoned projects with a transparent 0–100 pulse score.
- Produces human-readable terminal output and versioned JSON reports.
- Redacts project names, paths, remotes, and relapse labels for sharing.
- Records chosen resurrections and reports when they go quiet again.
- Recovers safely from malformed state files and writes output atomically.

## Quick start

### Requirements

- Python **3.8 or newer**
- Git available on `PATH`
- macOS or Linux

### Clone

```bash
git clone https://github.com/aikanii/graveyard-skill.git
cd graveyard-skill
```

No package installation is required.

### Scan project directories

```bash
python3 scripts/graveyard.py ~/dev ~/projects
```

### Save JSON and enable relapse tracking

```bash
python3 scripts/graveyard.py ~/dev ~/projects \
  --json graveyard-report.json \
  --state ~/.project-graveyard.json
```

### Example output (abbreviated)

```text
GRAVEYARD REPORT · 2026-09-25
============================================================
repos scanned: 12   alive: 3   finished: 2   dead: 6   not yours (skipped): 1
combined lifespan of the dead: ~184 days of your life
oldest corpse: invoice-lab (silent since Mar 2025)

THE DEAD                        lived      commits  cause of death
------------------------------------------------------------
checkout-demo                     18d        14   payments wall
recipe-scraper                    41d         9   slow fade
invoice-lab                       67d        31   deploy fear

STRONGEST PULSE --------/\_/\-------- (most resurrectable)
------------------------------------------------------------
invoice-lab                    pulse 72/100
   evidence: has a README; has tests; real code outweighs config; 31 commits of momentum; already on a remote
   cause:    README written, 31 commits in, tests present, and no deploy config anywhere.
   to ship:  needs deploy config
```

The example is illustrative; results depend entirely on local repository
metadata.

## Project classification

Every discovered project is placed into one of the following groups:

| Classification | Meaning |
|---|---|
| **Alive** | The latest commit is newer than the configured silence threshold. |
| **Finished** | Silent, but has a README, an `origin` remote, and either deployment configuration or a tagged release. |
| **Dead** | Silent beyond the threshold and not recognized as finished. |
| **Empty** | A Git repository exists but has no readable commits. |
| **Unversioned** | A directory contains a project marker such as `package.json`, `pyproject.toml`, or `go.mod`, but no Git repository. |
| **Foreign** | Fewer than 20% of commits belong to a recognized email identity; skipped unless explicitly included. |

The default silence threshold is **45 days** and can be changed with `--days`.

## Cause detection

The primary cause is the first matching signal. All matching causes and their
supporting evidence are included in JSON output.

| Cause | Signal |
|---|---|
| **Shiny object** | Another owned repository began within 14 days after this project stopped. |
| **Payments wall** | Files touched by the final three commits contain payment-related paths such as Stripe, billing, or checkout. |
| **Auth wall** | Files touched by the final three commits contain authentication-related paths such as OAuth, login, or sessions. |
| **Boilerplate wall** | At least 60% of historical file touches were recognized configuration files. |
| **Deploy fear** | README present, at least 20 commits, code outweighing configuration, and no deployment or release marker. |
| **Rewrite spiral** | At least two commit subjects mention a rewrite, migration, port, or stack switch. |
| **Scope explosion** | At least 100 tracked files, a lifespan over 30 days, and no deployment marker. |
| **Slow fade** | With no stronger signal, the final commit gap is at least three times the median gap. |
| **Unknown** | No supported signal is visible in Git metadata. |

See [`references/causes-of-death.md`](references/causes-of-death.md) for
confidence guidance and cause-specific resurrection strategies.

## How it works

```text
Selected roots
     │
     ▼
Repository discovery ──────► Unversioned project detection
     │
     ▼
Git metadata extraction
(commits, authors, paths, tags, remotes)
     │
     ▼
Ownership filtering
     │
     ▼
Alive / Finished / Dead classification
     │
     ├────────► Cause-of-death analysis
     │
     └────────► Pulse scoring
                      │
                      ▼
          Terminal report / JSON / State
```

For each repository, the scanner uses read-only Git commands to collect:

- committer timestamps and author emails;
- commit subjects and commit gaps;
- tracked filenames and historical file touches;
- the files touched by the final three commits;
- tags and the configured `origin` URL; and
- project signals such as README, tests, and deployment configuration.

It does not execute project code, install dependencies, inspect source-file
contents, or contact remote repositories.

## Pulse score

Pulse estimates resurrection potential. It does not measure code quality or
market value.

| Signal | Points |
|---|---:|
| README present | +15 |
| Tests present | +20 |
| Non-configuration work outweighs configuration | +20 |
| Commit momentum | Up to +15 |
| `origin` remote configured | +10 |
| Last commit is less than 180 days old | +10 |
| Deployment configuration present | +10 |
| **Maximum** | **100** |

The report also identifies missing README, tests, and deployment configuration
as concrete shipping gaps.

## CLI reference

```text
python3 scripts/graveyard.py [ROOT ...] [OPTIONS]
```

### Scan controls

| Option | Default | Description |
|---|---:|---|
| `ROOT ...` | Common project directories | One or more directories to scan. |
| `--days N` | `45` | Mark a repository dead after `N` days without commits. |
| `--max N` | `60` | Read at most `N` discovered repositories. |
| `--max-depth N` | `4` | Search this many directory levels below each root. |
| `--me EMAIL` | — | Recognize another commit email. Repeat as needed. |
| `--include-foreign` | Off | Include repositories below the 20% ownership threshold. |

### Output controls

| Option | Description |
|---|---|
| `--json PATH` | Atomically write a machine-readable report. |
| `--redact` | Replace identifying project information in terminal and JSON output. |
| `--no-art` | Disable decorative terminal output. |
| `--version` | Print the scanner version. |

### State controls

| Option | Description |
|---|---|
| `--state FILE` | Persist the latest scan and resurrection records. |
| `--mark-resurrected PATH` | Record a Git project as resurrected; requires `--state`. |

Run the built-in help for the authoritative option list:

```bash
python3 scripts/graveyard.py --help
```

### Default roots

When no roots are supplied, only these fixed locations are checked:

```text
~/dev
~/projects
~/code
~/src
~/Desktop
~/Documents/GitHub
~/Downloads
```

The scanner never defaults to `/` or the entire home directory.

### Exit codes

| Code | Meaning |
|---:|---|
| `0` | Scan or state operation completed successfully. |
| `1` | No Git repositories were found under the selected roots. |
| `2` | Invalid arguments, invalid resurrection target, or output write failure. |

## Structured JSON output

Use `--json` when another tool or agent needs reliable access to all evidence.
The report includes a schema version and complete census:

```json
{
  "schema_version": 1,
  "generated": "2026-09-25T10:30:00",
  "days_threshold": 45,
  "census": {
    "scanned": 12,
    "alive": 3,
    "finished": 2,
    "dead": 6,
    "foreign_skipped": 1,
    "ownership_unknown": 0,
    "unversioned": 1,
    "empty": 0
  },
  "alive": [],
  "finished": [],
  "unversioned": [],
  "empty": [],
  "skipped": [],
  "dead": []
}
```

Dead-project entries include repository facts, all matched causes, pulse score,
pulse evidence, and missing shipping signals. Raw commit subjects, final touched
paths, and commit-gap arrays are intentionally excluded from exported JSON.

Reports are written even when no dead projects are found. Parent directories for
explicit output paths are created automatically.

## Resurrection state

After choosing a project to revive, record it in a private state file:

```bash
python3 scripts/graveyard.py \
  --state ~/.project-graveyard.json \
  --mark-resurrected /absolute/path/to/project
```

A later scan with the same state file adds a **RELAPSE WATCH** section:

```bash
python3 scripts/graveyard.py ~/dev \
  --state ~/.project-graveyard.json
```

The scanner distinguishes between:

- awaiting the first commit after resurrection;
- holding with recent activity;
- silent for more than 14 days; and
- no longer present at the recorded path.

State writes are atomic. Malformed state is reported as a warning and does not
prevent a fresh scan.

> [!WARNING]
> `--redact` protects terminal and JSON reports, but the state file intentionally
> retains real project names and paths for future matching. Do not publish it.

## Agent skill

This repository follows the open Agent Skills layout. The
[`SKILL.md`](SKILL.md) manifest teaches a compatible coding agent when and how
to use Project Graveyard.

Install it by copying or linking the repository directory into the skills
location supported by your agent, preserving this structure:

```text
graveyard-skill/
├── SKILL.md
├── scripts/graveyard.py
└── references/causes-of-death.md
```

Example prompts:

```text
Run the graveyard on ~/dev and ~/projects.
```

```text
Which abandoned project is closest to shipping?
```

```text
Before I build this new tool, check whether I already attempted something similar.
```

The skill directs the agent to:

1. obtain a bounded scan scope;
2. run the local scanner;
3. label Git-derived conclusions as **forensic**;
4. ask only a few questions for ambiguous results;
5. select at most one resurrection candidate;
6. verify that candidate still runs before planning changes;
7. perform a current world-check with cited sources when appropriate; and
8. produce no more than seven steps ending in a real shipment.

The scanner itself remains offline. Any later web research is a separate,
explicit agent action.

## Privacy and security

### Data read

- Commit timestamps, author emails, and subjects
- Tracked filenames and historical path touches
- Tags and configured remote URLs
- Repository-local Git identity configuration

### Data not read or transmitted

- Source-file contents
- Environment variables or secrets
- Untracked file contents
- Remote repository data
- Network services or analytics

### Data written

Nothing is written unless `--json` or `--state` is explicitly supplied. The
scanner writes only those requested paths and never commits to or reconfigures a
scanned repository.

For a report intended for sharing, use:

```bash
python3 scripts/graveyard.py ~/dev --redact --json public-report.json
```

## Limitations

- “Dead” means silent past a threshold; it does not mean valueless or incomplete.
- A configured remote does not prove that every local commit was pushed.
- Deployment markers do not prove that a production deployment is healthy.
- Filename heuristics can produce false positives in examples, fixtures, or
  monorepos.
- Commit history can show where work stopped, but not personal motivation.
- Unversioned and empty projects have insufficient history for an autopsy.
- The scanner analyzes the checked-out branch rather than contacting or merging
  remote branches.
- Generated files and large vendored trees may inflate scope measurements.

The agent workflow addresses these limits by quoting evidence, requesting user
confirmation, and inspecting only the single chosen candidate with permission.

## Development

The project has no dependency installation step.

### Run the test suite

```bash
python3 -m unittest discover -s tests -v
```

Tests create temporary Git repositories with controlled commit histories. They
cover classifier boundaries, project classification, ownership filtering,
redaction, JSON output, state recovery, relapse detection, nested deployment
markers, and no-corpse scans. Real project directories are never touched.

### Additional checks

```bash
python3 -m py_compile scripts/graveyard.py tests/test_graveyard.py
git diff --check
```

### Run the scanner against this repository

```bash
python3 scripts/graveyard.py --include-foreign --days 0 .
```

## Project structure

```text
.
├── SKILL.md                       # Agent discovery metadata and workflow
├── README.md                      # Developer documentation
├── LICENSE                        # Apache License 2.0
├── scripts/
│   └── graveyard.py               # Scanner, classifiers, report, and state
├── references/
│   └── causes-of-death.md         # Evidence and resurrection strategies
└── tests/
    └── test_graveyard.py          # Stdlib unit and integration tests
```

## Contributing

Contributions should preserve the project’s core constraints:

1. no runtime dependencies;
2. no network access in the scanner;
3. no source-content inspection during the initial scan;
4. no mutation of scanned repositories;
5. evidence-first classifier output; and
6. Python 3.8 compatibility.

Add or update synthetic repository fixtures for every classifier or behavior
change, then run the complete test suite before submitting a pull request.

## License

Licensed under the [Apache License 2.0](LICENSE).
