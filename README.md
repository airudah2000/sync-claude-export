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

## Quick start

1. Copy this whole folder into `.claude/skills/sync-claude-export/` in whichever project
   root your Claude Code skill discovery is rooted at (or wherever you keep shared skills).
2. Copy `config.example.json` to `config.json` and fill in real `raw_dir` / `parsed_dir`
   paths for where you want the archive to live — a folder *outside* any git repo.
3. Trigger a claude.ai data export (Settings → Privacy → Export Data — web/desktop only,
   not available from the mobile app) and then just ask Claude Code to run the
   `sync-claude-export` skill. It handles finding the export-ready email, downloading each
   category, and parsing everything into the archive.

See `SKILL.md` for the authoritative, exact step-by-step Claude Code follows — this README
stays intentionally high-level so it doesn't go stale as those steps evolve.

## Requirements

- Python 3, no pip installs — `scripts/parse_export.py` is stdlib-only (`argparse`,
  `json`, `urllib`, `zipfile`, `pathlib`).
- A **Gmail MCP connector**, to locate the "your data is ready for download" email.
- Either **PowerShell** (`Start-Process`) / `open` (macOS) / `xdg-open` (Linux), or the
  **claude-in-chrome MCP connector**, to open the export's one-time download links in a
  real logged-in browser session.

## Privacy

The generated archive contains your real personal conversation history. `config.json`
(which points at that archive's real location) is already gitignored — never commit it.
If the archive folder itself ever ends up inside a git repo for any reason, gitignore it
too; it isn't meant to be checked in anywhere.

## Known limitations & roadmap

Tracked as [GitHub Issues](https://github.com/airudah2000/sync-claude-export/issues) —
currently a recurring re-export reminder and, for environments with no MCP host at all, an
isolated Playwright-based download fallback.
