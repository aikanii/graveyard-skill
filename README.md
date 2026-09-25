# 🪦 Project Graveyard Agent Skill

Every developer has a folder of abandoned projects. Project Graveyard turns
local Git history into an evidence-based inventory:

- **Why did each project stop?** It identifies likely walls such as auth,
  payments, deployment, configuration, rewrites, and scope growth.
- **What pattern keeps recurring?** It measures lifespans, abrupt handoffs to
  newer projects, repeated blockers, and one-day bursts.
- **Which project is closest to shipping?** It assigns a pulse score from
  concrete repository signals and gives an agent a protocol for choosing and
  planning one resurrection.

The repository is both an installable [Agent Skill](SKILL.md) and a standalone
Python CLI. The scanner is stdlib-only, offline, and compatible with Python
3.8+ on macOS and Linux.

## Quick start

```bash
python3 scripts/graveyard.py ~/dev ~/projects
```

With structured output and relapse tracking:

```bash
python3 scripts/graveyard.py ~/dev ~/projects \
  --json graveyard-report.json \
  --state ~/.project-graveyard.json
```

Run `python3 scripts/graveyard.py --help` for all options. Useful controls:

| Option | Purpose |
|---|---|
| `--days 90` | Change the silence threshold from its 45-day default. |
| `--me you@work.example` | Recognize another commit identity; repeatable. |
| `--include-foreign` | Include clones where recognized identities authored under 20% of commits. |
| `--max N` | Bound the number of repositories read. |
| `--max-depth N` | Change how deeply each root is searched. |
| `--redact` | Mask project names, paths, remotes, and relapse labels in shareable output. |
| `--no-art` | Suppress decorative terminal output. |

With no roots, the scanner checks a fixed set of common project locations such
as `~/dev`, `~/projects`, and `~/code`. Explicit roots are safer and faster.

## What it detects

| Cause | Evidence used |
|---|---|
| **shiny object** | Another owned repository began within 14 days after this one stopped. |
| **deploy fear** | README, 20+ commits, real code, and no deployment or release marker. |
| **payments / auth wall** | The final three commits touched payment or authentication paths. |
| **boilerplate wall** | At least 60% of historical file touches were configuration files. |
| **rewrite spiral** | Multiple rewrite, migration, port, or stack-switch commits. |
| **scope explosion** | 100+ tracked files, a month-long lifespan, and no deploy marker. |
| **slow fade** | The final commit gap grew to at least three times the median gap. |
| **unknown** | No supported cause is visible in Git metadata. |

These are forensic heuristics, not claims about motivation. The CLI reports the
supporting evidence, while [`references/causes-of-death.md`](references/causes-of-death.md)
documents confidence and a resurrection strategy for every cause.

The census also separates:

- **alive** repositories with recent commits;
- **finished** silent repositories with a README, an origin remote, and either
  deployment config or a tagged release;
- **empty** Git repositories with no commits; and
- **unversioned** marker-bearing project folders with no Git history.

## Agent workflow

An agent discovers the skill through `SKILL.md`. Its instructions cover:

1. bounded, permission-aware scanning;
2. a short interview for ambiguous deaths;
3. evidence-labeled tombstones and pattern reporting;
4. a present-day check of the strongest candidate;
5. a resurrection plan of no more than seven steps ending at a real shipment;
6. state recording and relapse watch; and
7. checking old work before scaffolding a duplicate new project.

Copy this repository directory into any agent environment that supports the
open Agent Skills format, preserving `SKILL.md`, `scripts/`, and `references/`.
The script path in the skill is resolved relative to `SKILL.md`, so it does not
depend on the user's current working directory.

## Resurrection state

Record a project only after the user chooses to resurrect it:

```bash
python3 scripts/graveyard.py \
  --state ~/.project-graveyard.json \
  --mark-resurrected /absolute/path/to/project
```

A later scan with the same state file reports whether the project has received
new commits and whether it has gone quiet for more than 14 days. State writes
are atomic, and malformed state files are handled with a warning instead of
breaking the scan.

## Privacy and limits

The scanner reads Git metadata: commit timestamps, author emails, commit
subjects, tracked filenames, tags, and configured remotes. It does **not** read
source-file contents, access network remotes, or modify scanned repositories.
It writes only explicitly requested `--json` and `--state` files.

`--redact` protects the shareable terminal and JSON report; the state file stays
private and intentionally retains real paths so future scans can match a
project. Do not publish the state file.

A repository with no commits has no history to diagnose. “Dead” also means only
“silent longer than the selected threshold”; stable tools and experiments may
be complete even when a heuristic cannot prove it. The agent instructions
therefore require evidence labels and user confirmation.

## Test

The tests build temporary repositories with dated commits and exercise every
major integration path. They do not touch real projects.

```bash
python3 -m unittest discover -s tests -v
```

## Files

```text
.
├── SKILL.md
├── README.md
├── LICENSE
├── scripts/
│   └── graveyard.py
├── references/
│   └── causes-of-death.md
└── tests/
    └── test_graveyard.py
```

Licensed under Apache-2.0.
