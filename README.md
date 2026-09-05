# sync-claude-export

A [Claude Code](https://claude.com/claude-code) skill that gives Claude Code visibility
into history it otherwise can't see at all: your **claude.ai** conversations, Projects,
and memories (especially useful if you use claude.ai mostly via the mobile app, which has
no export or API access whatsoever), plus your **local Claude Code session history**
across every project on this machine. Both directions get parsed into one unified,
searchable local markdown archive — greppable, browsable, and safe to point Claude Code
at in future sessions.

This is a **one-way sync only**. It builds a local archive *from* claude.ai's official
data export and *from* local Claude Code `.jsonl` session transcripts. Nothing here pushes
data back into claude.ai or the mobile app — there's no supported API for that direction,
and this project doesn't attempt to work around that.

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
  updates entries in place instead of duplicating them.

## Prerequisites

- **You must be logged into Claude Code via a claude.ai subscription (Pro/Max/Team/
  Enterprise), not a bare `ANTHROPIC_API_KEY`.** The Gmail and `claude-in-chrome`
  connectors this skill uses are Anthropic-hosted connectors that only load when
  authenticated through claude.ai's own OAuth (`/login`) — they don't appear at all under
  pure API-key auth, even with a key set alongside a login. If `ANTHROPIC_API_KEY` is set
  in your environment, unset it, run `/login`, then check `/mcp` lists both connectors
  before running this skill.
- Python 3 on your `PATH` as `python` or `python3` — `scripts/parse_export.py` is
  stdlib-only (`argparse`, `json`, `urllib`, `zipfile`, `pathlib`), no pip installs needed.

## Quick start

1. Install the skill so it's available in every project, not just one repo — copy this
   whole folder to `~/.claude/skills/sync-claude-export/` (user-level skills apply across
   all your Claude Code sessions; a user-level skill also takes precedence over a
   project-level one of the same name). Copying it into a single project's
   `.claude/skills/` instead works too, but then it's only usable from that one project.
2. Copy `config.example.json` to `config.json` (same folder) and fill in real `raw_dir` /
   `parsed_dir` paths for where you want the archive to live — a folder *outside* any git
   repo. Forward slashes work fine even on Windows and avoid JSON backslash-escaping
   mistakes (e.g. `"C:/Users/you/ClaudeAI-Sync/raw"`).
3. Trigger a claude.ai data export (Settings → Privacy → Export Data — web/desktop only,
   not available from the mobile app) and then just ask Claude Code to run the
   `sync-claude-export` skill. It handles finding the export-ready email, downloading each
   category, and parsing everything into the archive. **Run the skill the same day** —
   the emailed download link expires 24 hours after delivery.

See `SKILL.md` for the authoritative, exact step-by-step Claude Code follows — this README
stays intentionally high-level so it doesn't go stale as those steps evolve.

## Requirements

- Everything under **Prerequisites** above.
- Either **PowerShell** (`Start-Process`) / `open` (macOS) / `xdg-open` (Linux), or the
  **claude-in-chrome MCP connector**, to open the export's one-time download links in a
  real logged-in browser session. (macOS/Linux paths are implemented but not yet verified
  against a real export on those platforms — see open issues if you hit something.)

## Keeping your archive up to date

There's no automated reminder to re-export — claude.ai's export trigger (Settings →
Privacy → Export Data) has no API, so it can't be scheduled from inside this skill, and a
Claude Code scheduled job can't durably cover a monthly cadence either (jobs are
session-only and recurring ones auto-expire after 7 days). The practical answer is a
manual one: **set your own recurring reminder** (calendar, to-do app, whatever you already
use) to re-trigger the export every so often and re-run this skill — it's safe to run
repeatedly, since re-parsing updates existing entries in place instead of duplicating them.

## FAQ / Troubleshooting

**Gmail search finds zero matching threads.**
Most likely causes, in order: you haven't actually clicked Export Data yet (or the email
hasn't arrived — it can take a few hours), the email landed in Spam/Promotions, or Gmail
MCP is connected to a different account than the one you exported from. Check Spam before
anything else.

**The Gmail or `claude-in-chrome` connector doesn't show up in `/mcp` at all.**
Both require claude.ai subscription login (`/login`), not `ANTHROPIC_API_KEY` auth — see
Prerequisites above. If you have an API key set, unset it and re-authenticate.

**Opening the download link just shows an HTML/login page instead of downloading a zip
(`FALLBACK_NEEDED`).**
Expected on some accounts (e.g. certain SSO setups) — this isn't a bug. Ask Claude to fall
back to the manual path: download the file yourself from the link in the email and hand
Claude the file path.

**The download link says it's expired, or nothing downloads.**
The link expires 24 hours after the "ready for download" email arrives, and each of the 5
per-category links is single-use. Re-trigger a fresh export and start over — there's no way
to recover an expired link.

**`config.json` fails to parse / Claude says it can't read the config.**
Almost always a Windows backslash path typed with single backslashes into JSON (`\U` etc.
isn't a valid escape). Use forward slashes instead, e.g. `"C:/Users/you/ClaudeAI-Sync/raw"`
— `parse_export.py` uses `pathlib`, which accepts these fine on any OS.

**A conversation got tagged with a `related_projects` entry that's clearly wrong.**
That field is explicitly a heuristic guess (a project name mentioned somewhere in the
conversation), not a confirmed link — it's normal for it to occasionally flag an incidental
mention. It's never used to move or merge files, only to annotate. See issue tracker for
the matching logic's known limitations.

**Two projects/design-chats share the same name — did one overwrite the other?**
No — folders are suffixed with each project's own short ID specifically to prevent this
(`projects/<slug>-<id>/`), verified against real exports with zero collisions.

**Where should I actually put this skill folder?**
`~/.claude/skills/sync-claude-export/` (user-level) if you want it usable from any
project, which is almost always what you want for an account-wide sync tool. A specific
project's `.claude/skills/` only if you deliberately want it scoped to that one project.

## Privacy

The generated archive contains your real personal conversation history. `config.json`
(which points at that archive's real location) is already gitignored — never commit it.
If the archive folder itself ever ends up inside a git repo for any reason, gitignore it
too; it isn't meant to be checked in anywhere.

## Known limitations & roadmap

Tracked as [GitHub Issues](https://github.com/airudah2000/sync-claude-export/issues) —
currently just verifying macOS/Linux support on real hardware, since development so far has
been Windows-only.
