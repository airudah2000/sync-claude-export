# sync-claude-export

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A [Claude Code](https://claude.com/claude-code) skill that gives Claude Code visibility
into history it otherwise can't see at all: your **claude.ai** conversations, Projects,
and memories, plus your **local Claude Code session history** across every project on
this machine. Both are parsed into one unified, searchable local markdown archive.

## Table of Contents

- [Why this exists](#why-this-exists)
- [What it does](#what-it-does)
- [Prerequisites & Requirements](#prerequisites--requirements)
- [Quick start](#quick-start)
- [Keeping your archive up to date](#keeping-your-archive-up-to-date)
- [FAQ / Troubleshooting](#faq--troubleshooting)
- [Known limitations & roadmap](#known-limitations--roadmap)
- [Privacy](#privacy)
- [License](#license)

## Why this exists

If you use claude.ai mostly through the mobile app, Claude Code has zero visibility into
any of it: no conversations, no Projects, no memories, and no way to get them, since the
mobile app has no export or API access at all. Claude Code's own history isn't much better
off either. Session transcripts are scattered across every project directory on your
machine with no unified, searchable view.

This project closes both gaps at once. It builds a **one-way sync only**: a local archive
*from* claude.ai's official data export and *from* local Claude Code `.jsonl` session
transcripts. Nothing pushes data back into claude.ai or the mobile app. There's no
supported API for that direction, and this project doesn't attempt to work around that.

## What it does

- **claude.ai → archive:** walks the account's official data export (conversations,
  per-project knowledge docs, claude.ai's own cross-conversation memory, and Design canvas
  chats) and writes each into readable markdown with YAML frontmatter, cross-referencing
  what can genuinely be linked (e.g. a project's memory sits next to that project's docs)
  and clearly labeling what's only a heuristic guess (e.g. a conversation that mentions a
  project by name, since the export itself carries no conversation→project link).
- **Local Claude Code sessions → archive:** walks every `~/.claude/projects/*/*.jsonl` on
  this machine and extracts human-readable user/assistant text only (never raw tool output
  or file contents) into the same archive.
- Both feed the same `manifest.json` + `index.md`, so re-running after a later export
  updates entries in place instead of duplicating them. Your first-ever export tends to
  return all 5 category files; later exports typically return fewer (categories with
  nothing new are simply omitted), so they arrive faster and parse quicker.
- Every run reports what's actually new by title, not just counts, and offers to delete
  the now-redundant zips/manifest it downloaded to your Downloads folder afterward.

```mermaid
flowchart LR
    A[claude.ai Data Export] --> B[raw/]
    subgraph "Local Claude Code Machine"
        B --> D[parsed/]
        C["~/.claude/projects/*.jsonl"] --> D
        D --> E[index.md + manifest.json]
    end
```

## Prerequisites & Requirements

| Requirement | Why |
|---|---|
| Claude Code logged in via a claude.ai subscription (Pro/Max/Team/Enterprise), **not** a bare `ANTHROPIC_API_KEY` | The Gmail and `claude-in-chrome` connectors this skill uses only load under claude.ai's own OAuth (`/login`). They don't appear at all under pure API-key auth. If you have an API key set, unset it, run `/login`, then check `/mcp` lists both connectors. |
| Python 3 on your `PATH` as `python` or `python3` | Runs `scripts/parse_export.py`, which is stdlib-only (`argparse`, `json`, `urllib`, `zipfile`, `pathlib`). No pip installs needed. **macOS ships no `python` command, only `python3`**, and installing Python won't add one. The commands in `SKILL.md` are written as `python`; substitute `python3` on macOS/Linux. |
| **Gmail MCP connector** | Locates the "your data is ready for download" email. Make sure it's connected to the same account you export from. |
| **claude-in-chrome MCP connector**, or PowerShell (`Start-Process`) / `open` (macOS) / `xdg-open` (Linux) | Opens the export's one-time download links in a real logged-in browser session, and can also trigger the export itself. The Chrome extension being installed isn't enough: run `/chrome` in Claude Code, then **fully quit and relaunch Claude Code** before the `mcp__claude-in-chrome__*` tools appear. Verified end to end on macOS (see [Platform support](#platform-support)). The `open` / `xdg-open` fallbacks and Linux are still unverified. See [open issues](https://github.com/airudah2000/sync-claude-export/issues) if you hit something. |

## Quick start

1. Install the skill so it's available in every project, not just one repo. Copy this
   folder to `~/.claude/skills/sync-claude-export/` (user-level skills apply across
   all your Claude Code sessions; a user-level skill also takes precedence over a
   project-level one of the same name). Copy the files, not the `.git` folder:
   ```
   # macOS / Linux
   mkdir -p ~/.claude/skills
   rsync -a --exclude .git --exclude __pycache__ ./ ~/.claude/skills/sync-claude-export/
   ```
   If `~/.claude/skills/` didn't exist before, **restart Claude Code** so it picks up the
   new skills folder. Copying it into a single project's `.claude/skills/` instead works
   too, but then it's only usable from that one project.
2. Copy `config.example.json` to `config.json` (same folder) and fill in real `raw_dir` /
   `parsed_dir` paths for where you want the archive to live: a folder *outside* any git
   repo. Forward slashes work fine even on Windows and avoid JSON backslash-escaping
   mistakes (e.g. `"C:/Users/you/ClaudeAI-Sync/raw"`). On macOS use something like
   `"/Users/you/ClaudeAI-Sync/raw"` and `"/Users/you/ClaudeAI-Sync/parsed"`.
   **macOS: avoid `~/Documents` and `~/Desktop`.** If iCloud "Desktop & Documents" sync is
   on (check with `defaults read com.apple.finder FXICloudDriveDocuments`; `1` means on),
   anything you put there is uploaded to iCloud, including your full conversation history.
   A folder directly under your home directory, like `~/ClaudeAI-Sync`, is not synced.
3. Trigger a claude.ai data export (Settings → Privacy → Export Data; web/desktop only,
   not available from the mobile app) and then just ask Claude Code to run the
   `sync-claude-export` skill. With the `claude-in-chrome` connector, Claude can click
   through that export for you too. It handles finding the export-ready email, downloading
   each category, and parsing everything into the archive. **Run the skill the same day**:
   the emailed download link expires 24 hours after delivery.

See `SKILL.md` for the authoritative, exact step-by-step Claude Code follows. This README
stays intentionally high-level so it doesn't go stale as those steps evolve.

## Keeping your archive up to date

There's no automated reminder to re-export, since claude.ai's export trigger has no API and
can't be scheduled from inside this skill. A Claude Code scheduled job can't durably cover
a monthly cadence either, because jobs are session-only and recurring ones auto-expire
after 7 days. The practical answer is manual: **set your own recurring reminder** to
re-trigger the export and re-run this skill. It's safe to run repeatedly. Re-parsing
updates existing entries in place instead of duplicating them.

## FAQ / Troubleshooting

**Gmail search finds zero matching threads.**
Check, in order: the export hasn't actually been triggered yet (or the email hasn't arrived
yet; it can take a few hours), the email landed in Spam/Promotions, or Gmail MCP is
connected to a different account than the one you exported from.

**The Gmail or `claude-in-chrome` connector doesn't show up in `/mcp` at all.**
Both require claude.ai subscription login (`/login`), not API-key auth. See
[Prerequisites](#prerequisites--requirements). Unset `ANTHROPIC_API_KEY` and re-authenticate.

**`claude-in-chrome` is installed, but Claude says browser tools aren't available.**
Enabling it is a two-step process: run `/chrome` in Claude Code (a slash command; typing
`! /chrome` sends it to the shell and fails), then fully quit and relaunch Claude Code.
Running `/chrome` alone prints nothing and doesn't add the tools to the running session.
Confirm it worked by asking Claude to list its Chrome tabs.

**`python: command not found` (macOS / Linux).**
There's no bare `python` on stock macOS. Use `python3`, which is what `SKILL.md`'s commands
need on those platforms. No separate install is required if `python3 --version` works.

**The skill doesn't appear after installing it.**
Claude Code only watches skills folders that existed when it started. If you just created
`~/.claude/skills/`, restart Claude Code.

**A tab-group error, or a blank "New tab" left behind, during the download step.**
With `claude-in-chrome`, closing the original tab of the automation group and then
navigating in a tab created earlier can fail with "not in Claude's tab group". The failed
navigation happens before the page loads, so the one-time link isn't consumed. Retry with
a fresh tab (see `SKILL.md` Part A step 4). A stray blank tab can be closed by hand.

**Opening the download link just shows an HTML/login page (`FALLBACK_NEEDED`).**
This isn't a bug. It's expected on some accounts (e.g. certain SSO setups). Ask Claude to
fall back to the manual path: download the file yourself from the email link and hand
Claude the path.

**The download link says it's expired, or nothing downloads.**
Links expire 24 hours after the "ready for download" email, and every per-category link
(the manifest lists between 1 and 5 depending on what's changed since your last export —
see below) is single-use. Re-trigger a fresh export and start over.

**`config.json` fails to parse.**
Almost always a Windows path typed with single backslashes into JSON. Use forward slashes
instead, e.g. `"C:/Users/you/ClaudeAI-Sync/raw"`. `pathlib` accepts these fine on any OS.

**A conversation got tagged with a wrong `related_projects` entry.**
That field is an explicit heuristic guess, not a confirmed link. Occasional incidental
matches are expected, and the field is never used to move or merge files, only to annotate.

**A conversation I know is inside a claude.ai Project shows up under `standalone/`.**
Expected. The export has no conversation-to-project link at all, so *every* conversation
lands in `standalone/`, whether or not it lives in a Project in claude.ai. "Standalone" here
means "no known link", not "not in a project". Use the `related_projects` field (a name-match
guess) or check claude.ai itself to see where a chat actually lives.

**Two projects/design-chats share a name. Did one overwrite the other?**
No. Folders are suffixed with each project's own short ID specifically to prevent this,
verified against real exports with zero collisions.

**Where should I put this skill folder?**
`~/.claude/skills/sync-claude-export/` (user-level) for use from any project. That's almost
always what you want for an account-wide sync tool. A project's own `.claude/skills/` only
makes sense if you deliberately want it scoped to that one project.

## Known limitations & roadmap

Tracked as [GitHub Issues](https://github.com/airudah2000/sync-claude-export/issues).
Linux, and the `open` / `xdg-open` fallback for machines without `claude-in-chrome`, are
still unverified on real hardware.

### Doc conventions (keep the docs cross-platform)

- **Forward slashes only in paths**, in prose, commands and JSON (`"C:/Users/you/..."`,
  `"/Users/you/..."`). They work on Windows and macOS/Linux alike; backslashes break on
  macOS/Linux and need escaping in JSON. Use `pathlib` in code, never a hard-coded separator.
- **Label anything OS-specific** (`python` vs `python3`, `open` / `xdg-open` / `Start-Process`)
  instead of assuming one platform.
- Before committing a docs change, searching `README.md` and `SKILL.md` for the backslash
  character should find nothing.

### Platform support

| Platform | Status |
|---|---|
| Windows + Chrome via `claude-in-chrome` | Verified (original development platform). |
| macOS + Chrome via `claude-in-chrome` | Verified end to end on 2026-09-22: macOS 15.6.1 (Intel), Python 3.14.4, Chrome. Export trigger, email lookup, all 5 category downloads, `fetch`, all `parse-*` commands, `index-code-sessions`, and `cleanup-downloads`. Re-runs were idempotent. Filenames containing emoji and curly quotes wrote fine on APFS. |
| macOS/Linux with only `open` / `xdg-open` | Not yet verified. Leaves download tabs open. |
| Linux | Not yet verified. |

## Privacy

The generated archive contains your real personal conversation history. `config.json`
(which points at that archive's real location) is already gitignored. Never commit it.
If the archive folder itself ever ends up inside a git repo for any reason, gitignore it
too; it isn't meant to be checked in anywhere.

On macOS, also keep the archive out of iCloud-synced folders (`~/Documents`, `~/Desktop`
when "Desktop & Documents" sync is on), or it will be uploaded to iCloud. Similarly, don't
place it in a Dropbox, OneDrive or Google Drive folder unless you intend it to sync.

## License

[MIT](LICENSE)
