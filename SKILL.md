---
name: graveyard-skill
description: >-
  Scans local project folders for abandoned or unfinished Git repositories,
  autopsies likely causes from Git metadata, identifies recurring abandonment
  patterns, and selects one project worth resurrecting. Use when the user asks
  what project to finish, mentions old or abandoned side projects, wants to
  revive or finally ship something, asks why projects stall, says "run the
  graveyard", or proposes a new project that may duplicate an older attempt.
license: Apache-2.0
compatibility: Python 3.8+ and Git; scanner is local, offline, and stdlib-only.
metadata:
  author: "Shubham Saboo"
  version: "1.1.0"
  source: "https://github.com/aikanii/graveyard-skill"
---

# Project Graveyard

Find abandoned local projects, explain what the history can actually support,
and help the user finish one rather than start another.

The scanner is offline and reads Git metadata: commit dates, author emails,
messages, tracked filenames, remotes, and tags. It does not read source-file
contents or contact remotes. The later resurrection review may read the chosen
project and use web research, but only after the user agrees.

## Locate this skill

Commands below are relative to the directory containing this `SKILL.md`, not
necessarily the current working directory. Resolve that directory first and run:

```bash
python3 <skill-directory>/scripts/graveyard.py /path/to/projects
```

Do not assume `scripts/graveyard.py` exists in the user's current directory.

## When to use it

Use this skill when the user:

- asks about abandoned, unfinished, stale, or old side projects;
- asks what they should finish or why they rarely finish projects;
- wants to revive, resurrect, or finally ship a project;
- says “run the graveyard”; or
- proposes a new project that may overlap with an earlier attempt.

Do not use it merely to free disk space, delete dependencies, archive GitHub
repositories, or deeply analyze one already-selected repository.

## Safety and scope

1. Prefer explicit roots supplied by the user. If none are known, ask one short
   question rather than scanning a broad home directory. Running with no roots
   scans only the fixed common locations listed by `--help`.
2. Never pass `/`, the whole home directory, or unrelated work directories
   without explicit permission.
3. The scanner does not modify scanned repositories. `--json` and `--state`
   write only to the paths the user names.
4. Do not use `--include-foreign` by default. Clones, forks, and work checkouts
   are not automatically the user's abandoned projects.
5. Offer `--redact` before producing a report intended for sharing.

## Run the scan

Typical command:

```bash
python3 <skill-directory>/scripts/graveyard.py \
  ~/dev ~/projects \
  --json /tmp/project-graveyard-report.json \
  --state ~/.project-graveyard.json
```

Useful flags:

- `--days 90`: set the silence threshold (default: 45 days).
- `--me EMAIL`: recognize another commit identity; repeat as needed.
- `--include-foreign`: include repositories where recognized identities made
  fewer than 20 percent of commits.
- `--max N` and `--max-depth N`: bound a large scan.
- `--json PATH`: save structured scan results for reliable interpretation.
- `--redact`: replace project names and paths in shareable output.
- `--state FILE`: remember the scan and enable relapse watch.
- `--no-art`: omit decorative scanner output.

If the ownership filter skips a real project, rerun with the relevant
`--me` value. Do not silently turn on `--include-foreign` for every repository.

Before interpreting causes, read `references/causes-of-death.md`. Causes are
heuristics. Repeat their evidence, not just their labels.

## Autopsy interview

Git shows a timeline, not motivation. For a primary `unknown` or `slow_fade`
result, ask at most two or three short questions total, for example:

> `recipe-scraper` only shows a gradual fade. Do you remember what actually
> stopped it?

Mark scanner-derived conclusions **(forensic)** and user testimony
**(confirmed)**. A confirmed answer supersedes a speculative classifier result.
Do not interrogate the user about every repository.

## Write the report

Turn the scan into four concise sections:

1. **Census** — scanned, alive, finished, dead, skipped, and unversioned counts;
   include combined dead-project lifespan and oldest corpse when available.
2. **Tombstones** — one line per corpse with lifespan, commits, primary cause,
   and quoted evidence. For more than about ten corpses, give detail only to
   the six to eight most informative and group the rest.
3. **Patterns** — report only patterns supported by counts or timelines.
4. **Resurrection** — recommend one project, or plainly recommend none.

Order tombstones from weaker to stronger pulse so the recommendation lands
last. Every epitaph must be traceable to scan evidence. Be dry rather than
wacky, criticize the pattern rather than the person, and treat substantial work
with respect.

Only the single resurrection candidate earns an ASCII tombstone card. Keep it
under 44 columns so it does not wrap. Do not create decorative cards for every
project.

## Choose one resurrection

The highest pulse is a starting point, not an automatic winner.

1. Ask before opening or changing the candidate repository.
2. After permission, read its README, inspect the working tree, and confirm the
   project still matches the user's goal.
3. Run its documented install/test/entry point without making broad upgrades.
4. Perform a current **world-check**: determine whether the blocker is now
   easier and whether the idea has been superseded. Web research is separate
   from the offline scan; say when it is being used and cite current sources.
5. Apply the per-cause resurrection angle in
   `references/causes-of-death.md`.

Recommend leaving it buried when the user no longer cares, the useful window
closed, the world already solved it better, or all candidates have weak pulse.
Closure is a valid outcome.

## Make the resurrection plan

Write no more than seven concrete steps:

- **Step 0 is always “confirm it still runs.”** Dependencies rot.
- Step 1 must be finishable today and create visible progress.
- Freeze the stack for rewrite spirals.
- Prefer a managed integration for auth/payment walls.
- Extract one shippable feature from scope explosions.
- End at **shipped**: a URL, release, published package, or other observable
  deliverable—not “continue development.”

Ask before touching the project, then offer to begin step 1 immediately.

When the user commits to the resurrection, record it:

```bash
python3 <skill-directory>/scripts/graveyard.py \
  --state ~/.project-graveyard.json \
  --mark-resurrected /absolute/path/to/project
```

Future scans with the same `--state` file show whether it is holding. If it
falls silent again, ask the user to recommit or bury it honestly rather than
prescribing endless retries.

## Necromancer mode

Before scaffolding a newly proposed side project, inspect a fresh JSON report or
the state file for a plausible earlier attempt. Names are hints, not proof; ask
before reading old project contents. If there is a match, mention it once:

> You may already have part of this in `project-name`; it stopped near the auth
> work. Would you rather inspect that before starting over?

Let the user choose and drop the point if they decline.

## Common gotchas

- A broad folder such as `~/Desktop` may itself be a Git repository while also
  containing nested repositories. The scanner intentionally detects both.
- Ownership is based on commit email. Use repeatable `--me` values for work,
  GitHub, or automation identities.
- “Dead” means silent past a threshold, not worthless. Stable deployed tools
  and tagged releases are separated as finished, but the heuristic is rough.
- Unversioned project folders can be counted but cannot be autopsied.
- One-day projects are often experiments that served their purpose. Surface the
  aggregate pattern instead of pretending each is a tragedy.

## Files

- `scripts/graveyard.py` — offline scanner, classifier, and state handling.
- `references/causes-of-death.md` — evidence, confidence, and resurrection
  guidance for every cause.
- `tests/test_graveyard.py` — stdlib integration and regression tests.
