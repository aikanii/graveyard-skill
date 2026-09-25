#!/usr/bin/env python3
"""
graveyard.py — find your dead side projects and figure out why they died.

Scans directories for git repos, separates the living from the dead, runs a
cause-of-death analysis on each corpse from its git history, detects your
personal death patterns, and ranks the dead by resurrection potential.

Everything runs locally. Nothing leaves your machine.

Usage:
    python3 graveyard.py ~/dev ~/projects            # scan these roots
    python3 graveyard.py                              # scan default roots
    python3 graveyard.py --json report.json           # full data for tooling
    python3 graveyard.py --days 90                    # custom "dead" threshold
    python3 graveyard.py --include-foreign             # include repos you didn't author

Python 3.8+, stdlib only. Never mutates repositories; writes only explicit
--json and --state paths.
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

__version__ = "1.1.0"

DEFAULT_ROOTS = ["~/dev", "~/projects", "~/code", "~/src", "~/Desktop", "~/Documents/GitHub", "~/Downloads"]
SKIP_DIRS = {"node_modules", ".venv", "venv", ".tox", "vendor", ".cache", "Library",
             "__pycache__", ".npm", ".cargo", "go", ".local", ".Trash", "dist", "build"}
MAX_DEPTH = 4

CONFIG_FILES = {
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock",
    "bun.lockb", "tsconfig.json", "webpack.config.js", "vite.config.js",
    "vite.config.ts", "vite.config.mjs", "babel.config.js", ".eslintrc",
    ".eslintrc.js", ".eslintrc.json", "eslint.config.js", "eslint.config.mjs",
    ".prettierrc", "jest.config.js", "requirements.txt", "pyproject.toml",
    "setup.py", "setup.cfg", "Pipfile", "poetry.lock", "uv.lock", "go.mod",
    "go.sum", "Cargo.toml", "Cargo.lock", "Dockerfile", "compose.yml",
    "compose.yaml", "docker-compose.yml", "docker-compose.yaml", ".gitignore",
    "Makefile", ".env.example", "tailwind.config.js", "tailwind.config.ts",
    "postcss.config.js", "next.config.js", "next.config.mjs",
}
DEPLOY_MARKERS = ["vercel.json", "netlify.toml", "fly.toml", "render.yaml", "Procfile",
                  "app.yaml", "wrangler.toml", "railway.json", "firebase.json",
                  "serverless.yml", "serverless.yaml", ".github/workflows"]
AUTH_HINTS = ("auth", "oauth", "login", "signup", "session", "clerk", "passport",
              "jwt", "next-auth", "supabase-auth")
PAYMENT_HINTS = ("stripe", "billing", "payment", "checkout", "subscription", "paddle",
                 "lemonsqueezy", "paywall")


def sh(args, cwd=None):
    """Run a command, return stdout or '' on any failure. Never raises."""
    try:
        # Decode git output as UTF-8. With text=True and no encoding, Python uses
        # the locale default (cp1252 on Windows), which raises UnicodeDecodeError
        # on non-Latin-1 bytes in commit messages (emoji, em-dashes, …).
        out = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=30)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def find_repos(roots, max_depth=MAX_DEPTH):
    """Find Git worktrees below roots without traversing metadata/cache dirs."""
    repos = []
    for root in roots:
        root = Path(os.path.expanduser(str(root)))
        if not root.is_dir():
            continue
        base_depth = len(root.parts)
        for dirpath, dirs, _files in os.walk(str(root)):
            p = Path(dirpath)
            if len(p.parts) - base_depth > max_depth:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            # .git can be a file (worktrees) — and we keep walking below a repo,
            # because real machines have accidental repos (a git-inited ~/Desktop)
            # with real projects nested inside them.
            if (p / ".git").exists():
                repos.append(p)
    # de-dup (same repo reachable from two roots) and keep paths resolved so
    # they compare equal everywhere (macOS tempdirs and symlinked dev folders
    # otherwise produce /var vs /private/var mismatches in the state file)
    seen, out = set(), []
    for r in repos:
        key = r.resolve()
        if key not in seen:
            seen.add(key)
            out.append(key)
    # Sorted so nothing downstream ever depends on filesystem walk order —
    # APFS and ext4 enumerate directories differently.
    return sorted(out)


PROJECT_MARKERS = {"package.json", "pyproject.toml", "requirements.txt", "go.mod",
                   "Cargo.toml", "Gemfile", "composer.json", "index.html"}


def find_unversioned(roots, repo_paths, max_depth=MAX_DEPTH):
    """Find marker-bearing project folders that are not inside a Git repo.

    A directory counts if it has a project marker file, is not inside any Git
    repository, and is not nested inside another unversioned project already
    found. Symlinked trees are not followed.
    """
    found = []
    repo_strs = [str(r) for r in repo_paths]
    for root in roots:
        root = Path(os.path.expanduser(str(root)))
        if not root.is_dir():
            continue
        base_depth = len(root.parts)
        for dirpath, dirs, files in os.walk(str(root)):
            p = Path(dirpath)
            if len(p.parts) - base_depth > max_depth:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            rp = str(p.resolve())
            if any(rp == r or rp.startswith(r + os.sep) for r in repo_strs):
                dirs[:] = []  # inside a git repo; its files belong to that story
                continue
            if PROJECT_MARKERS & set(files) and not (p / ".git").exists():
                found.append(p.resolve())
                dirs[:] = []  # don't count a project's subfolders as more projects
    return sorted(set(found))


def has_path_marker(files, marker):
    """Return whether marker exists at the root or in a nested package."""
    marker = marker.strip("/")
    for filename in files:
        clean = filename.strip("/")
        if clean == marker or clean.startswith(marker + "/"):
            return True
        if clean.endswith("/" + marker) or ("/" + marker + "/") in ("/" + clean):
            return True
    return False


def read_repo(path, my_emails):
    """Pull facts out of one repository using fast, read-only Git commands."""
    # Committer time represents when work landed in this repository; author
    # time can remain years old after a recent cherry-pick or rebase.
    log = sh(["git", "log", "--format=%ct|%ae|%s", "--no-merges"], cwd=path)
    if not log:
        return None
    commits = []
    for line in log.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            try:
                commits.append({"at": int(parts[0]), "email": parts[1], "msg": parts[2]})
            except ValueError:
                continue
    if not commits:
        return None
    commits.sort(key=lambda c: c["at"])

    # A repository may intentionally override the global Git identity. Treat
    # that local-only address as another identity belonging to the user; this
    # avoids dropping old work-account projects unless --include-foreign is
    # used. Do not use inherited config here because it is already collected
    # once by main().
    recognized_emails = set(my_emails)
    local_email = sh(["git", "config", "--local", "--get", "user.email"], cwd=path)
    if local_email:
        recognized_emails.add(local_email.strip().lower())
    mine = (sum(1 for c in commits if c["email"].strip().lower() in recognized_emails)
            if recognized_emails else len(commits))
    remote = sh(["git", "remote", "get-url", "origin"], cwd=path)

    files = sh(["git", "ls-files"], cwd=path).splitlines()
    file_names = {Path(f).name for f in files}
    top_dirs = {f.split("/")[0] for f in files if "/" in f}

    # files touched by the last 3 commits — where it died
    last_touched = sh(["git", "log", "-3", "--name-only", "--format="], cwd=path).lower()

    has_deploy = any(has_path_marker(files, marker) for marker in DEPLOY_MARKERS)
    has_tests = any("test" in f.lower() or "spec" in f.lower() for f in files)
    has_tags = bool(sh(["git", "tag", "--list"], cwd=path))
    has_readme = any(n.lower().startswith("readme") for n in file_names)

    # how much of the history is config-shuffling vs actual code
    # (--format= keeps the output to file paths only, one per touch)
    touches = [l for l in
               sh(["git", "log", "--name-only", "--format=", "--no-merges"], cwd=path).splitlines()
               if l.strip()]
    config_touches = sum(1 for l in touches if Path(l).name in CONFIG_FILES)
    total_touches = len(touches)

    return {
        "path": str(path),
        "name": path.name,
        "first": commits[0]["at"],
        "last": commits[-1]["at"],
        "commits": len(commits),
        "mine": mine,
        "ownership_known": bool(recognized_emails),
        "messages": [c["msg"] for c in commits],
        "remote": remote,
        "files": len(files),
        "top_dirs": len(top_dirs),
        "last_touched": last_touched,
        "has_deploy": has_deploy,
        "has_tags": has_tags,
        "has_tests": has_tests,
        "has_readme": has_readme,
        "config_ratio": (config_touches / total_touches) if total_touches else 0.0,
        "gaps": [b["at"] - a["at"] for a, b in zip(commits, commits[1:])],
    }


def lifespan_days(r):
    return max(1, (r["last"] - r["first"]) // 86400)


def autopsy(repo, all_repos):
    """Cause of death, with evidence. Returns (cause, evidence) — best guess first.

    These are forensic reads of the git history, not certainties. The evidence
    string is the part that matters: it has to be true even if the verdict is
    debatable.
    """
    findings = []

    # killed by a newer project: another repo you own was born right after this
    # one died. Several can qualify; the nearest in time is the likeliest
    # killer — and picking it keeps the verdict deterministic regardless of
    # filesystem discovery order (name breaks exact-timestamp ties).
    killer, kgap = None, None
    for other in all_repos:
        if other is repo:
            continue
        gap = other["first"] - repo["last"]
        if 0 <= gap <= 14 * 86400:
            if kgap is None or (gap, other["name"]) < (kgap, killer["name"]):
                killer, kgap = other, gap
    if killer:
        findings.append((
            "shiny_object",
            "killed by `%s`, whose first commit came %d day(s) after this repo's last"
            % (killer["name"], max(0, kgap // 86400)),
        ))

    last = repo["last_touched"]
    if any(h in last for h in PAYMENT_HINTS):
        findings.append(("payments_wall", "the final commits touch payment code — died at the checkout"))
    elif any(h in last for h in AUTH_HINTS):
        findings.append(("auth_wall", "the final commits touch auth code — died at the login screen"))

    if repo["config_ratio"] >= 0.6 and repo["commits"] >= 5:
        findings.append((
            "boilerplate_wall",
            "%d%% of all file touches were config files — more time configuring than building"
            % round(repo["config_ratio"] * 100),
        ))

    if (repo["has_readme"] and repo["commits"] >= 20 and repo["config_ratio"] < 0.6
            and not repo["has_deploy"] and not repo["has_tags"]):  # a tagged release shipped
        findings.append((
            "deploy_fear",
            "README written, %d commits in, tests %s, and no deploy config anywhere. "
            "It worked. It just never shipped." % (repo["commits"], "present" if repo["has_tests"] else "absent"),
        ))

    rewrite_msgs = [m for m in repo["messages"]
                    if any(w in m.lower() for w in ("rewrite", "migrate to", "port to", "switch to"))]
    if len(rewrite_msgs) >= 2:
        findings.append((
            "rewrite_spiral",
            "history contains %d rewrite/migration commits — it kept being rebuilt instead of finished"
            % len(rewrite_msgs),
        ))

    if repo["files"] >= 100 and not repo["has_deploy"] and lifespan_days(repo) > 30:
        findings.append((
            "scope_explosion",
            "%d files across %d top-level directories, zero deploy config — it grew instead of shipping"
            % (repo["files"], repo["top_dirs"]),
        ))

    if not findings and len(repo["gaps"]) >= 3:
        med = statistics.median(repo["gaps"])
        if med and repo["gaps"][-1] >= 3 * med:
            findings.append((
                "slow_fade",
                "the last gap between commits was %dx the median — it didn't die, it drifted"
                % (repo["gaps"][-1] // max(1, int(med))),
            ))

    if not findings:
        findings.append(("unknown", "no clear wound. Sometimes a project just stops."))
    return findings


def pulse(repo):
    """0-100: how resurrectable is this corpse. Higher = closer to shipping."""
    score = 0
    why = []
    if repo["has_readme"]:
        score += 15; why.append("has a README")
    if repo["has_tests"]:
        score += 20; why.append("has tests")
    if repo["config_ratio"] < 0.5:
        score += 20; why.append("real code outweighs config")
    score += min(15, repo["commits"] // 4)
    if repo["commits"] >= 20:
        why.append("%d commits of momentum" % repo["commits"])
    if repo["remote"]:
        score += 10; why.append("already on a remote")
    age_days = (datetime.now().timestamp() - repo["last"]) / 86400
    if age_days < 180:
        score += 10; why.append("corpse is still warm (<6 months)")
    if repo["has_deploy"]:
        score += 10; why.append("deploy config already exists")
    missing = []
    if not repo["has_deploy"]:
        missing.append("deploy config")
    if not repo["has_tests"]:
        missing.append("tests")
    if not repo["has_readme"]:
        missing.append("README")
    return min(100, score), why, missing


def fmt_date(ts):
    return datetime.fromtimestamp(ts).strftime("%b %Y")


def load_state(path):
    """Load and validate the small persistent state file.

    A bad state file must not make the read-only scan unusable. Invalid entries
    are ignored with a warning and the rest of the state is preserved.
    """
    state = {"resurrections": [], "last_scan": None}
    if not path:
        return state
    expanded = os.path.expanduser(path)
    if not os.path.exists(expanded):
        return state
    try:
        with open(expanded, encoding="utf-8") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, dict):
            raise ValueError("top level must be an object")
        if isinstance(loaded.get("last_scan"), dict) or loaded.get("last_scan") is None:
            state["last_scan"] = loaded.get("last_scan")
        raw_resurrections = loaded.get("resurrections", [])
        if not isinstance(raw_resurrections, list):
            raise ValueError("resurrections must be a list")
        for item in raw_resurrections:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                continue
            target = str(Path(os.path.expanduser(item["path"])).resolve())
            date = item.get("date") if isinstance(item.get("date"), str) else "unknown"
            name = item.get("name") if isinstance(item.get("name"), str) else Path(target).name
            resurrection = {"path": target, "name": name, "date": date}
            if isinstance(item.get("marked_at"), (int, float)):
                resurrection["marked_at"] = item["marked_at"]
            state["resurrections"].append(resurrection)
    except (OSError, ValueError, TypeError) as exc:
        print("warning: could not read state file %s (%s); starting fresh"
              % (path, exc), file=sys.stderr)
    return state


def atomic_json_dump(path, data):
    """Atomically write JSON, creating an explicitly requested parent dir."""
    target = Path(os.path.expanduser(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(target.parent),
                                         prefix=".%s." % target.name, suffix=".tmp",
                                         delete=False) as handle:
            temp_name = handle.name
            json.dump(data, handle, indent=1, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, str(target))
    except Exception:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
        raise


def public_repo(repo, fields):
    """Pick JSON-safe public fields from an analyzed repository."""
    return {key: repo[key] for key in fields if key in repo}


def build_report(args, alive, finished, dead, unversioned, skipped, empty):
    """Build the stable machine-readable report payload."""
    alive_fields = ("name", "path", "first", "last", "commits", "mine", "ownership_known")
    dead_exclusions = {"messages", "gaps", "last_touched", "real_name", "real_path"}
    redacted_unversioned = [
        {"name": "unversioned-%d" % i, "path": "(redacted)"}
        for i, _item in enumerate(unversioned, 1)
    ]
    public_dead = []
    for repo in dead:
        item = {key: value for key, value in repo.items() if key not in dead_exclusions}
        # A remote normally contains the owner and original repository name, so
        # retaining it would undo --redact even when name/path are masked.
        if args.redact and item.get("remote"):
            item["remote"] = "(redacted)"
        public_dead.append(item)
    return {
        "schema_version": 1,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "days_threshold": args.days,
        "census": {
            "scanned": len(alive) + len(finished) + len(dead) + len(skipped) + len(empty),
            "alive": len(alive),
            "finished": len(finished),
            "dead": len(dead),
            "foreign_skipped": len(skipped),
            "ownership_unknown": sum(
                1 for repo in alive + finished + dead if not repo.get("ownership_known")
            ),
            "unversioned": len(unversioned),
            "empty": len(empty),
        },
        "alive": [public_repo(repo, alive_fields) for repo in alive],
        "finished": [public_repo(repo, alive_fields) for repo in finished],
        "unversioned": (redacted_unversioned if args.redact else
                          [{"name": item.name, "path": str(item)} for item in unversioned]),
        "empty": ([{"name": "empty-%d" % i, "path": "(redacted)"}
                   for i, _item in enumerate(empty, 1)] if args.redact else
                  [{"name": item.name, "path": str(item)} for item in empty]),
        "skipped": ([{"name": "not-yours-%d" % i} for i, _item in enumerate(skipped, 1)]
                    if args.redact else [{"name": item["name"], "mine": item["mine"],
                                          "commits": item["commits"]} for item in skipped]),
        "dead": public_dead,
    }


def scan_snapshot(roots, alive, finished, dead, unversioned, empty):
    """Create the private, unredacted scan snapshot stored for later matching."""
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "roots": [str(root) for root in roots],
        "dead": [{"name": repo.get("real_name", repo["name"]),
                  "path": repo.get("real_path", repo["path"]),
                  "cause": repo["causes"][0][0], "pulse": repo["pulse"]}
                 for repo in dead],
        "alive": [{"name": repo.get("real_name", repo["name"]),
                   "path": repo.get("real_path", repo["path"])} for repo in alive],
        "finished": [{"name": repo.get("real_name", repo["name"]),
                      "path": repo.get("real_path", repo["path"])} for repo in finished],
        "unversioned": [{"name": item.name, "path": str(item)} for item in unversioned],
        "empty": [{"name": item.name, "path": str(item)} for item in empty],
    }


def resurrection_reference_time(resurrection):
    """Return an exact mark time while remaining compatible with legacy state."""
    try:
        day_time = datetime.strptime(resurrection.get("date", ""), "%Y-%m-%d").timestamp()
    except (TypeError, ValueError, OverflowError):
        day_time = None
    marked_at = resurrection.get("marked_at")
    if isinstance(marked_at, (int, float)):
        # If somebody edited an old state's date, honor that explicit change.
        # Otherwise use the exact timestamp to avoid treating a commit from the
        # morning of resurrection day as post-resurrection activity.
        marked_day = datetime.fromtimestamp(marked_at).strftime("%Y-%m-%d")
        if marked_day == resurrection.get("date"):
            return marked_at
    if day_time is not None:
        return day_time
    return datetime.now().timestamp()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Find your dead side projects and why they died.")
    ap.add_argument("roots", nargs="*", default=None, help="directories to scan (default: common dev dirs)")
    ap.add_argument("--version", action="version", version="%(prog)s " + __version__)
    ap.add_argument("--days", type=int, default=45, help="no commits in N days = dead (default 45)")
    ap.add_argument("--json", metavar="PATH", help="write full machine-readable report")
    ap.add_argument("--include-foreign", action="store_true",
                    help="include repos where you authored <20%% of commits (clones, forks, work checkouts)")
    ap.add_argument("--max", type=int, default=60, dest="max_repos", help="stop after N repos (default 60)")
    ap.add_argument("--max-depth", type=int, default=MAX_DEPTH,
                    help="directory levels below each root to inspect (default %d)" % MAX_DEPTH)
    ap.add_argument("--redact", action="store_true",
                    help="replace project names with project-1..n (for sharing the report)")
    ap.add_argument("--me", action="append", default=[], metavar="EMAIL",
                    help="extra email(s) you commit under (work address, web edits, "
                         "builder tools). Repeatable. Repos authored by these count as yours.")
    ap.add_argument("--no-art", action="store_true",
                    help="skip the headstone (for piping, or for people who hate fun)")
    ap.add_argument("--state", metavar="FILE",
                    help="remember scans and resurrections in FILE. Enables relapse "
                         "detection (a resurrected project going silent again) and "
                         "gives necromancer mode something to grep.")
    ap.add_argument("--mark-resurrected", metavar="PATH",
                    help="record that PATH was resurrected today (requires --state); "
                         "future scans call it out if it starts dying again.")
    args = ap.parse_args(argv)
    if args.days < 0:
        ap.error("--days must be zero or greater")
    if args.max_repos < 1:
        ap.error("--max must be at least 1")
    if args.max_depth < 0:
        ap.error("--max-depth must be zero or greater")
    if (args.json and args.state
            and Path(os.path.expanduser(args.json)).resolve()
            == Path(os.path.expanduser(args.state)).resolve()):
        ap.error("--json and --state must use different files")

    state = load_state(args.state)

    if args.mark_resurrected:
        if not args.state:
            print("error: --mark-resurrected needs --state FILE to write into", file=sys.stderr)
            return 2
        candidate = Path(os.path.expanduser(args.mark_resurrected)).resolve()
        if not candidate.is_dir():
            print("error: resurrection path is not a directory: %s" % candidate,
                  file=sys.stderr)
            return 2
        top_level = sh(["git", "rev-parse", "--show-toplevel"], cwd=candidate)
        if not top_level:
            print("error: resurrection path is not inside a Git worktree: %s" % candidate,
                  file=sys.stderr)
            return 2
        target = str(Path(top_level).resolve())
        state["resurrections"] = [item for item in state["resurrections"]
                                  if item["path"] != target]
        marked_now = datetime.now()
        state["resurrections"].append({
            "path": target,
            "name": Path(target).name,
            "date": marked_now.strftime("%Y-%m-%d"),
            "marked_at": int(marked_now.timestamp()),
        })
        try:
            atomic_json_dump(args.state, state)
        except OSError as exc:
            print("error: could not write state file %s: %s" % (args.state, exc),
                  file=sys.stderr)
            return 2
        display_name = "project" if args.redact else Path(target).name
        print("recorded: %s resurrected %s. The next scan holds it to that."
              % (display_name, state["resurrections"][-1]["date"]))
        return 0

    roots = args.roots or DEFAULT_ROOTS
    configured = []
    for command in (["git", "config", "--global", "--get-all", "user.email"],
                    ["git", "config", "--get-all", "user.email"]):
        configured.extend(sh(command).splitlines())
    my_emails = {email.strip().lower() for email in configured + args.me if email.strip()}

    paths = find_repos(roots, args.max_depth)
    unversioned = find_unversioned(roots, paths, args.max_depth)
    if not paths:
        if args.redact:
            print("No git repos found under the configured scan roots.")
        else:
            print("No git repos found under: %s" % ", ".join(str(root) for root in roots))
        if unversioned:
            if args.redact:
                print("But %d project folder(s) with no git at all." % len(unversioned))
            else:
                print("But %d project folder(s) with no git at all: %s"
                      % (len(unversioned), ", ".join(p.name for p in unversioned[:8])))
            print("No history means no autopsy — get them under git before they rot further.")
        print("Pass the directories where your projects actually live.")
        report = build_report(args, [], [], [], unversioned, [], [])
        try:
            if args.json:
                atomic_json_dump(args.json, report)
                print("full report written" if args.redact else "full report: %s" % args.json)
            if args.state:
                state["last_scan"] = scan_snapshot(roots, [], [], [], unversioned, [])
                atomic_json_dump(args.state, state)
        except OSError as exc:
            print("error: could not write requested output: %s" % exc, file=sys.stderr)
            return 2
        return 1
    if len(paths) > args.max_repos:
        print("(found %d repos; reading the first %d — raise --max to widen)"
              % (len(paths), args.max_repos), file=sys.stderr)
        paths = paths[: args.max_repos]

    if len(paths) > 15:
        print("reading %d repos (a few seconds each on big histories)..." % len(paths),
              file=sys.stderr)
    repos, skipped, empty = [], [], []
    for path in paths:
        repo = read_repo(path, my_emails)
        if repo is None:
            empty.append(path)
            continue
        if (not args.include_foreign and repo["ownership_known"]
                and repo["mine"] / repo["commits"] < 0.2):
            skipped.append({"name": repo["name"], "path": repo["path"],
                            "mine": repo["mine"], "commits": repo["commits"]})
            continue  # someone else's repo you cloned; not your corpse to bury
        repos.append(repo)
    foreign = len(skipped)

    if args.redact:
        for i, r in enumerate(sorted(repos, key=lambda r: r["first"]), 1):
            # Keep the real identifiers so relapse-watch matching and the local
            # --state resume file stay correct; only the shareable report is
            # redacted (see by_path / --state / --json below).
            r["real_name"] = r["name"]
            r["real_path"] = r["path"]
            r["name"] = "project-%d" % i
            r["path"] = "(redacted)"

    cutoff = datetime.now().timestamp() - args.days * 86400
    silent = [r for r in repos if r["last"] < cutoff]
    alive = [r for r in repos if r["last"] >= cutoff]
    # A silent repo that shipped (deploy config + pushed + README) isn't dead —
    # it's a finished tool that reached stability. Don't eulogize it.
    # Shipped means deployed (deploy config) OR released (tags) — an
    # open-sourced library with releases is finished, not deploy-fearful.
    finished = [r for r in silent
                if r["remote"] and r["has_readme"] and (r["has_deploy"] or r["has_tags"])]
    dead = [r for r in silent if r not in finished]
    dead.sort(key=lambda r: r["last"], reverse=True)

    for r in dead:
        r["causes"] = autopsy(r, repos)
        s, w, m = pulse(r)
        r["pulse"], r["pulse_why"], r["missing"] = s, w, m
        r["lifespan_days"] = lifespan_days(r)

    # ---- census ----
    total_days = sum(repo["lifespan_days"] for repo in dead)
    print()
    if not args.no_art:
        print("          .--------.")
        print("         /          \\")
        print("        |   R.I.P.   |")
        print("        |    your    |")
        print("        |    side    |")
        print("        |  projects  |")
        print("     ___|____________|___")
        print("    ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~")
        print()
    print("GRAVEYARD REPORT · %s" % datetime.now().strftime("%Y-%m-%d"))
    print("=" * 60)
    print("repos scanned: %d   alive: %d   finished: %d   dead: %d   not yours (skipped): %d"
          % (len(repos) + foreign + len(empty), len(alive), len(finished), len(dead), foreign))
    ownership_unknown = sum(1 for repo in repos if not repo["ownership_known"])
    if ownership_unknown and not args.include_foreign:
        print("ownership unknown for %d repo(s): no matching Git email was configured; "
              "included them (use --me EMAIL for reliable filtering)" % ownership_unknown)
    if empty:
        if args.redact:
            print("empty repositories (no commits): %d" % len(empty))
        else:
            print("empty repositories (no commits): %s"
                  % ", ".join(path.name for path in empty[:8])
                  + (" …" if len(empty) > 8 else ""))
    if finished:
        print("finished (shipped, just stable — not corpses): %s"
              % ", ".join(repo["name"] for repo in finished[:8]))
    if skipped:
        if args.redact:
            print("skipped as not-yours (by commit email): %d repository(s)" % len(skipped))
        else:
            print("skipped as not-yours (by commit email): %s"
                  % ", ".join(item["name"] for item in skipped[:10])
                  + (" …" if len(skipped) > 10 else ""))
        print("  (yours under another email? rerun with --me that@email.com, or --include-foreign)")
    if unversioned:
        if args.redact:
            print("unversioned (no git — died before their first commit): %d project folder(s)"
                  % len(unversioned))
        else:
            print("unversioned (no git — died before their first commit): %s"
                  % ", ".join(path.name for path in unversioned[:8])
                  + (" …" if len(unversioned) > 8 else ""))
        print("  no history means no autopsy; `git init` is the only medicine here")

    if dead:
        print("combined lifespan of the dead: ~%d day%s of your life"
              % (total_days, "" if total_days == 1 else "s"))
        oldest = min(dead, key=lambda repo: repo["last"])
        print("oldest corpse: %s (silent since %s)"
              % (oldest["name"], fmt_date(oldest["last"])))

        # ---- the dead ----
        print("\nTHE DEAD" + " " * 24 + "lived      commits  cause of death")
        print("-" * 60)
        for repo in dead:
            cause = repo["causes"][0][0].replace("_", " ")
            print("%-30s %4dd %9d   %s"
                  % (repo["name"][:30], repo["lifespan_days"], repo["commits"], cause))

        # ---- patterns ----
        print("\nPATTERNS")
        print("-" * 60)
        spans = [repo["lifespan_days"] for repo in dead]
        med_span = statistics.median(spans)
        med_text = (str(int(med_span)) if med_span == int(med_span)
                    else "%.1f" % med_span)
        print("- median lifespan of a dead project: %s day%s"
              % (med_text, "" if med_span == 1 else "s"))
        burst = [repo for repo in dead
                 if repo["lifespan_days"] <= 1 and repo["commits"] >= 5]
        if len(burst) >= 2:
            print("- %d projects lived exactly one day: built in a single burst, never reopened."
                  % len(burst))
        shiny = [repo for repo in dead if repo["causes"][0][0] == "shiny_object"]
        if shiny:
            print("- %d of %d were killed by a newer project. You don't abandon projects;"
                  % (len(shiny), len(dead)))
            print("  you leave them for younger ones.")
        walls = [repo for repo in dead
                 if repo["causes"][0][0] in ("auth_wall", "payments_wall")]
        if len(walls) >= 2:
            print("- %d projects died at the same wall (auth/payments). That wall isn't moving;"
                  % len(walls))
            print("  your approach to it has to.")
        fear = [repo for repo in dead
                if any(cause[0] == "deploy_fear" for cause in repo["causes"])]
        if fear:
            print("- %d finished project(s) never shipped. Building was never the problem."
                  % len(fear))
    else:
        print("\nNo corpses. Either you finish everything or you delete the evidence.")

    # ---- relapse watch: hold past resurrections to their promise ----
    if state["resurrections"]:
        by_path = {repo.get("real_path", repo["path"]): repo for repo in repos}
        lines = []
        now = datetime.now().timestamp()
        for index, resurrection in enumerate(state["resurrections"], 1):
            repo = by_path.get(resurrection["path"])
            display = ("resurrected-project-%d" % index if args.redact
                       else resurrection["name"])
            if repo is None:
                lines.append("- %s: resurrected %s, no longer found on disk. Buried for good, or moved."
                             % (display, resurrection["date"]))
                continue
            if args.redact:
                display = repo["name"]
            marked = resurrection_reference_time(resurrection)
            latest_activity = max(marked, repo["last"])
            silent_seconds = max(0, now - latest_activity)
            silent_days = int(silent_seconds / 86400)
            if silent_seconds > 14 * 86400:
                lines.append("- %s: resurrected %s, no activity for %d days. It's dying again — "
                             "decide: recommit or bury it honestly."
                             % (display, resurrection["date"], silent_days))
            elif repo["last"] < marked:
                lines.append("- %s: resurrected %s, awaiting its first new commit (%dd). Holding."
                             % (display, resurrection["date"], silent_days))
            else:
                lines.append("- %s: resurrected %s, last commit %dd ago. Holding."
                             % (display, resurrection["date"], silent_days))
        print("\nRELAPSE WATCH")
        print("-" * 60)
        for line in lines:
            print(line)

    # ---- pulse ----
    if dead:
        print("\nSTRONGEST PULSE --------/\\_/\\-------- (most resurrectable)")
        print("-" * 60)
        for repo in sorted(dead, key=lambda item: item["pulse"], reverse=True)[:3]:
            print("%-30s pulse %d/100" % (repo["name"][:30], repo["pulse"]))
            print("   evidence: %s" % ("; ".join(repo["pulse_why"]) or "not much"))
            print("   cause:    %s" % repo["causes"][0][1])
            if repo["missing"]:
                print("   to ship:  needs %s" % ", ".join(repo["missing"]))
    print()

    report = build_report(args, alive, finished, dead, unversioned, skipped, empty)
    try:
        if args.json:
            atomic_json_dump(args.json, report)
            print("full report written" if args.redact else "full report: %s" % args.json)
        if args.state:
            # The state file is private resume data, so real names and paths are
            # retained even when the shareable report is redacted.
            state["last_scan"] = scan_snapshot(
                roots, alive, finished, dead, unversioned, empty)
            atomic_json_dump(args.state, state)
    except OSError as exc:
        print("error: could not write requested output: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())