---
name: sync-claude-export
description: Sync claude.ai conversation/project/memory history (via official data export) and local Claude Code session history into one unified, searchable local markdown archive.
---

# Sync Claude Export

Builds and maintains a local markdown archive covering both directions of Claude history:
- **claude.ai -> local**: the account's official data export (web only, not mobile).
- **Local Claude Code sessions -> local**: this machine's own `~/.claude/projects/*/*.jsonl` transcripts.

Note: nothing in this skill pushes data back into claude.ai or the mobile app -- that
direction has no supported API and isn't possible today. This only builds a local archive.

All logic lives in `scripts/parse_export.py`, run with `python` (already confirmed
available in this environment). This file tells Claude what to do and in what order.

## First run: confirm storage location

Confirm with the user where the archive should live (default suggestion:
`C:\Users\Robert\Documents\ClaudeAI-Sync\`, with `raw\` and `parsed\` subfolders), then
record it in `config.json` next to this file:

```json
{ "raw_dir": "C:\\...\\ClaudeAI-Sync\\raw", "parsed_dir": "C:\\...\\ClaudeAI-Sync\\parsed" }
```

On later runs, read `config.json` instead of asking again. The archive holds personal
conversation history -- if it ever ends up inside a git repo, make sure it's gitignored.

Paths throughout this file are shown in Windows backslash style as illustration only --
`parse_export.py` uses Python's `pathlib` internally, which accepts forward slashes
equally well on any OS. On macOS/Linux, use forward-slash paths (e.g.
`~/ClaudeAI-Sync/raw`) instead.

## Part A: claude.ai export -> archive

1. **Check the export was triggered.** Ask the user to confirm they've recently clicked
   Export Data on claude.ai web (Settings -> Privacy -> Export Data) -- not possible from
   the mobile app. Two emails arrive: "Your data export is in progress" then, once ready,
   "Your data is ready for download" -- the second one's "Download data" button link
   expires 24 hours after delivery.

2. **Find the ready email.** Gmail MCP `search_threads`:
   `from:anthropic.com OR from:claude.ai (export OR "data export" OR "your data") newer_than:2d`
   (fallback: `from:anthropic.com newer_than:1d`). If more than one plausible thread comes
   back, show the candidates to the user.

3. **Extract the "Download data" link.** `get_thread` on the chosen thread, then find the
   `https://claude.ai/export/.../download/...` URL in the body (it's the "Download data"
   button href). Confirm with the user if ambiguous.

4. **Open it in the user's browser -- this is the default first attempt, not a fallback.**
   This must use the user's own logged-in session, so it succeeds where a plain
   script-side HTTP fetch would hit a login redirect. Two ways to do this, in
   preference order:

   - **Preferred, when the `claude-in-chrome` MCP connector is available:** use
     `tabs_create_mcp` to open the link (this rides the user's real logged-in Chrome
     session, same as any other tab), then `tabs_close_mcp` once the download has
     started. This connector manages its own isolated tab group, separate from the
     user's regular tabs, so it can be opened and closed cleanly without any risk of
     touching a tab the user didn't open themselves -- verified working end-to-end in
     a real session (see `FUTURE_IMPROVEMENTS.md` item 1). This approach is also
     OS-agnostic -- no shelling out to an OS-specific open-command at all.

   - **Fallback, when `claude-in-chrome` isn't available:** shell out to the OS's
     default "open URL in default browser" command:
     - Windows: `powershell -Command "Start-Process '<the link>'"` (or the PowerShell
       tool directly)
     - macOS: `open '<the link>'`
     - Linux: `xdg-open '<the link>'`
     This still uses the user's logged-in session, but see the "Known limitation"
     section below -- there's no clean way to close only the tab this opens.

   Confirmed working (either way): the link does NOT return a single zip -- it
   downloads a small **manifest JSON** to the user's Downloads folder, e.g.
   `manifest-<id>-<ts>-<hash>-<date>.json`, shaped like:
   ```json
   {
     "total_files": 5,
     "data_files": [
       {"category": "light_metadata", "export_url": "...", "filename": "light_metadata-000.zip"},
       {"category": "projects",       "export_url": "...", "filename": "projects-000.zip"},
       {"category": "memories",       "export_url": "...", "filename": "memories-000.zip"},
       {"category": "design_chats",   "export_url": "...", "filename": "design_chats-000.zip"},
       {"category": "conversations",  "export_url": "...", "filename": "conversations-000.zip"}
     ]
   }
   ```
   Read that manifest, then **open all 5 `export_url`s the same way** (whichever method
   you used above, one call per URL with a short pause between them) -- each one
   auto-downloads its zip to Downloads. **Each `export_url` is single-use** -- never
   open the same one twice, and never also try a script-side fetch on one you've
   already opened in-browser.

   If neither method is available, or a link still doesn't produce a real zip (check:
   a "FALLBACK_NEEDED" style HTML/login-redirect result), fall back to asking the user
   to download it manually and hand you the file path.

5. **Move + unzip each downloaded zip:**
   ```
   python scripts/parse_export.py fetch --zip "<path-in-Downloads>" --raw-dir "<raw_dir>"
   ```
   Prints the extracted JSON file path(s) -- note there's no single schema: `conversations`
   is one JSON array, `projects` and `design_chats` are one file *per item* in a
   subfolder, `memories` is a single JSON object, `light_metadata` is account/login
   metadata (not parsed into the archive -- not conversation content).

6. **Inspect once per category, first time only.** `inspect-export --json <file>` prints
   the real shape. The known real shapes (confirmed against an actual export) are already
   encoded in `extract_conversation_fields()` (conversations) and the parse-projects /
   parse-design-chats / parse-memories functions -- if a future export looks different,
   edit the relevant function, not the whole script.

7. **Parse each category -- `parse-projects` MUST run first**, since the other two now
   read its output directory to cross-reference projects (`--projects-dir`):
   ```
   python scripts/parse_export.py parse-projects       --projects-dir "<extracted>\projects" --parsed-dir "<parsed_dir>" --manifest "<parsed_dir>\manifest.json"
   python scripts/parse_export.py parse-memories        --json "<extracted>\memories\<account-uuid>.json" --parsed-dir "<parsed_dir>" --manifest "<parsed_dir>\manifest.json" --projects-dir "<extracted>\projects"
   python scripts/parse_export.py parse-conversations --json "<conversations.json>" --parsed-dir "<parsed_dir>" --manifest "<parsed_dir>\manifest.json" --projects-dir "<extracted>\projects"
   python scripts/parse_export.py parse-design-chats    --chats-dir "<extracted>\design_chats" --parsed-dir "<parsed_dir>" --manifest "<parsed_dir>\manifest.json"
   ```
   Each prints new/updated/unchanged counts and is safe to re-run after a later export --
   updates in place rather than duplicating (verified: re-running with no new data reports
   all-unchanged with no file-count growth).

   **What the `--projects-dir` cross-referencing actually buys you (verified against real
   data, don't assume more than this):**
   - `parse-memories`: claude.ai's per-project memory is keyed by the *same* project uuid
     as `parse-projects` -- a genuine hard link. When a match is found, the memory file is
     written into that project's own folder as `_project-memory.md`, sitting right next to
     `_project-knowledge.md`, instead of a disconnected top-level folder.
   - `parse-conversations`: `conversations.json` carries **zero** project associations for
     any conversation (confirmed: 0/58 in a real export) -- there is no hard link available
     here. What this adds instead is a heuristic: each conversation's text is scanned for
     case-insensitive mentions of a known project's name, and matches are recorded as
     `related_projects` in that conversation's frontmatter and the index -- clearly labeled
     as an inferred *possible* mention, never used to move the file or treated as confirmed.
     Expect some false positives (e.g. a short project name incidentally appearing in
     unrelated text) -- that's inherent to substring matching, not a bug to chase to zero.
   - **`design_chats` deliberately does NOT get this treatment.** Verified against real
     data: none of a design-chat's `project.uuid` values match any real Project uuid --
     Design canvases use a completely separate "project" concept that happens to share the
     same JSON field name. Do not attempt to co-locate design-chats into `projects/` by
     name or uuid; they stay in their own top-level `design-chats/` category.

## Part B: local Claude Code sessions -> archive

No download needed -- reads what's already on this machine.

```
python scripts/parse_export.py index-code-sessions --parsed-dir "<parsed_dir>" --manifest "<parsed_dir>\manifest.json"
```

Walks every `~/.claude/projects/*/*.jsonl`, extracts only human-readable user/assistant
text (never raw tool output or file contents), writes/updates
`parsed_dir\code-sessions\<project>\*.md`, sharing the same manifest/index as Part A.

## After either part

Report a short summary (new/updated/unchanged counts per category, total items indexed)
and point the user at `<parsed_dir>\index.md`.

## Known limitation: browser tabs opened during Part A step 4 (fallback path only)

This only applies when the OS-shellout fallback (`Start-Process`/`open`/`xdg-open`) was
used because `claude-in-chrome` wasn't available. That shellout opens each link in the
user's *existing* default browser -- there is no reliable way from here to close only the
specific tab that was opened (as opposed to the window, or another tab the user already
had open) without additional tooling. Don't attempt to blindly send close-tab keystrokes --
that risks closing a tab the user didn't want closed. Mention this limitation to the user
rather than silently leaving tabs open with no explanation.

When `claude-in-chrome` was available and used instead, this limitation doesn't apply --
`tabs_create_mcp`/`tabs_close_mcp` manage their own isolated tab group and can be closed
cleanly with no risk to the user's other tabs.
