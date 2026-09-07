---
name: sync-claude-export
description: Sync claude.ai conversation/project/memory history (via official data export) and local Claude Code session history into one unified, searchable local markdown archive.
---

# Sync Claude Export

Builds and maintains a local markdown archive covering both directions of Claude history:
- **claude.ai -> local**: the account's official data export (web only, not mobile).
- **Local Claude Code sessions -> local**: this machine's own `~/.claude/projects/*/*.jsonl` transcripts.

Note: nothing in this skill pushes data back into claude.ai or the mobile app. That
direction has no supported API and isn't possible today. This only builds a local archive.

All logic lives in `scripts/parse_export.py`. Run it with whichever of `python` / `python3`
actually resolves to a Python 3 interpreter on this machine: check with `python --version`
/ `python3 --version` if unsure, don't assume. This file tells Claude what to do and in
what order.

## First run: confirm storage location

Confirm with the user where the archive should live (a folder *outside* any git repo,
e.g. `~/ClaudeAI-Sync/` or `Documents/ClaudeAI-Sync/`, with `raw/` and `parsed/`
subfolders), then record it in `config.json` next to this file. Copy `config.example.json`
to `config.json` and fill in the real paths (forward slashes work fine even on Windows and
sidestep JSON backslash-escaping mistakes, e.g. `"C:/Users/you/ClaudeAI-Sync/raw"`).

On later runs, read `config.json` instead of asking again. The archive holds personal
conversation history. If it ever ends up inside a git repo, make sure it's gitignored.

## Part A: claude.ai export -> archive

1. **Check first, ask second.** Before asking the user anything, run the Gmail search from
   step 2 yourself. Don't require the user to confirm they clicked Export Data before you've
   even looked. Two emails arrive per export: "Your data export is in progress," then once
   ready, "Your data is ready for download." The second one's "Download data" button link
   expires 24 hours after delivery, and export processing itself can take a few hours (rarely
   up to 12).

   - **Ready email found:** proceed straight to step 3, no need to ask anything.
   - **Only the "in progress" email found:** the export is running. Don't ask the user to
     ping you back — poll for it yourself (e.g. `ScheduleWakeup` at ~20-30 min intervals, or
     whatever this session's equivalent of "check back later" is) and re-run the same Gmail
     search each time until the ready email appears. Tell the user once, up front, that
     you'll check back automatically rather than asking them to remind you.
   - **Neither email found:** only now ask the user to trigger an export (Settings -> Privacy
     -> Export Data on claude.ai web; not available on mobile).

   **Export size/speed varies a lot between runs, this is normal, not a bug:** the first-ever
   export for an account tends to return all ~5 category files (`light_metadata`, `projects`,
   `memories`, `design_chats`, `conversations`) and can take longer to process. Later exports
   (re-triggered after the archive already has a baseline) often come back with fewer files
   in the manifest — categories with nothing new/changed are simply omitted — arrive faster,
   and are cheaper to parse. Don't treat a manifest with fewer than 5 files as an error; check
   `total_files` and `data_files` in the manifest itself rather than assuming a fixed shape.

2. **Find the ready email.** Gmail MCP `search_threads`:
   `from:anthropic.com OR from:claude.ai (export OR "data export" OR "your data") newer_than:2d`
   (fallback: `from:anthropic.com newer_than:1d`). If more than one plausible thread comes
   back, show the candidates to the user. **If zero threads come back**, don't assume
   something's broken. The most common causes are the export not actually being triggered
   yet, the email landing in Spam/Promotions, or Gmail MCP not being connected to the
   expected account. Ask the user to double check Settings -> Privacy -> Export Data was
   clicked and to check Spam, before troubleshooting anything else. If the Gmail MCP tool
   itself isn't available at all (connector not connected), skip straight to asking the user
   to paste the "Download data" link directly from the email themselves.

3. **Extract the "Download data" link.** `get_thread` on the chosen thread, then find the
   `https://claude.ai/export/.../download/...` URL in the body (it's the "Download data"
   button href). Confirm with the user if ambiguous.

4. **Open it in the user's browser. This is the default first attempt, not a fallback.**
   This must use the user's own logged-in session, so it succeeds where a plain
   script-side HTTP fetch would hit a login redirect. Two ways to do this, in
   preference order:

   - **Preferred, when the `claude-in-chrome` MCP connector is available:** use
     `tabs_create_mcp` to open the link (this rides the user's real logged-in Chrome
     session, same as any other tab), then `tabs_close_mcp` once the download has
     started. This connector manages its own isolated tab group, separate from the
     user's regular tabs, so it can be opened and closed cleanly with no risk of
     touching a tab the user didn't open themselves. Verified working end-to-end in a
     real session. This approach is also OS-agnostic: no shelling out to an
     OS-specific open-command at all.

   - **Fallback, when `claude-in-chrome` isn't available:** shell out to the OS's
     default "open URL in default browser" command:
     - Windows: `powershell -Command "Start-Process '<the link>'"` (or the PowerShell
       tool directly)
     - macOS: `open '<the link>'`
     - Linux: `xdg-open '<the link>'`
     This still uses the user's logged-in session, but see the "Known limitation"
     section below: there's no clean way to close only the tab this opens.

   Confirmed working (either way): the link does NOT return a single zip. It downloads
   a small **manifest JSON** to the user's Downloads folder, e.g.
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
   Read that manifest, then **open each `export_url` in its own fresh tab (`tabs_create_mcp`
   -> `navigate` -> verify -> `tabs_close_mcp`, repeat), never two links in the same tab.**
   Each `export_url` is single-use and marked consumed server-side the moment it's
   requested, whether or not the file actually reaches disk — so never open the same one
   twice, and never treat a fixed short wait, or the generic "Downloading..." page
   content, as proof the file arrived. After opening a link, poll the Downloads folder for
   the exact expected filename (freshly modified, not a stale file of the same name from
   a previous run) before closing that tab and moving to the next link.

   **Known failure mode, root cause, and the fix (all confirmed in real runs on
   2026-09-07):** reusing the *same* tab for a second (or later) automatic download
   silently drops it — Chrome's own "this site is trying to download multiple files"
   guard blocks every automatic download in a tab after the first, via a browser-chrome
   infobar near the address bar that the `claude-in-chrome` screenshot/computer tools
   cannot see or click (they only capture the page viewport, not browser chrome). The
   server still marks that `export_url` consumed even though nothing reached disk, so
   there's no recovering it — re-opening it immediately confirms "Expired link." This is
   **not** a timing/pacing issue: spacing out same-tab navigations doesn't help.
   **The fix that works, verified**: give every download its own fresh tab. A brand-new
   tab's automatic-download counter starts at zero, so its first (and only) download in
   that tab always succeeds — confirmed getting 3 different category files this way back
   to back with zero drops. No Chrome setting changes needed and none should be
   requested; this is a pure sequencing fix within the existing browser-automation flow.

   If neither browser method is available, or a link still doesn't produce a real zip
   (check: a "FALLBACK_NEEDED" style HTML/login-redirect result, or an "Expired link"
   page — the latter means the link was already burned, see above), fall back to asking
   the user to download it manually and hand you the file path.

5. **Move + unzip each downloaded zip:**
   ```
   python scripts/parse_export.py fetch --zip "<path-in-Downloads>" --raw-dir "<raw_dir>"
   ```
   Prints the extracted JSON file path(s). Note there's no single schema: `conversations`
   is one JSON array, `projects` and `design_chats` are one file *per item* in a
   subfolder, `memories` is a single JSON object, `light_metadata` is account/login
   metadata (not parsed into the archive; not conversation content).

6. **Inspect once per category, first time only.** `inspect-export --json <file>` prints
   the real shape. The known real shapes (confirmed against an actual export) are already
   encoded in `extract_conversation_fields()` (conversations) and the parse-projects /
   parse-design-chats / parse-memories functions. If a future export looks different,
   edit the relevant function, not the whole script.

7. **Parse each category. `parse-projects` MUST run first**, since the other two now
   read its output directory to cross-reference projects (`--projects-dir`):
   ```
   python scripts/parse_export.py parse-projects       --projects-dir "<extracted>\projects" --parsed-dir "<parsed_dir>" --manifest "<parsed_dir>\manifest.json"
   python scripts/parse_export.py parse-memories        --json "<extracted>\memories\<account-uuid>.json" --parsed-dir "<parsed_dir>" --manifest "<parsed_dir>\manifest.json" --projects-dir "<extracted>\projects"
   python scripts/parse_export.py parse-conversations --json "<conversations.json>" --parsed-dir "<parsed_dir>" --manifest "<parsed_dir>\manifest.json" --projects-dir "<extracted>\projects"
   python scripts/parse_export.py parse-design-chats    --chats-dir "<extracted>\design_chats" --parsed-dir "<parsed_dir>" --manifest "<parsed_dir>\manifest.json"
   ```
   Each prints new/updated/unchanged counts and is safe to re-run after a later export:
   updates in place rather than duplicating (verified: re-running with no new data reports
   all-unchanged with no file-count growth).

   **What the `--projects-dir` cross-referencing actually buys you (verified against real
   data, don't assume more than this):**
   - `parse-memories`: claude.ai's per-project memory is keyed by the *same* project uuid
     as `parse-projects`. This is a genuine hard link. When a match is found, the memory
     file is written into that project's own folder as `_project-memory.md`, sitting right
     next to `_project-knowledge.md`, instead of a disconnected top-level folder.
   - `parse-conversations`: `conversations.json` carries **zero** project associations for
     any conversation (confirmed: 0/58 in a real export). There is no hard link available
     here. What this adds instead is a heuristic: each conversation's text is scanned for
     case-insensitive mentions of a known project's name, and matches are recorded as
     `related_projects` in that conversation's frontmatter and the index, clearly labeled
     as an inferred *possible* mention, never used to move the file or treated as confirmed.
     Expect some false positives (e.g. a short project name incidentally appearing in
     unrelated text). That's inherent to substring matching, not a bug to chase to zero.
   - **`design_chats` deliberately does NOT get this treatment.** Verified against real
     data: none of a design-chat's `project.uuid` values match any real Project uuid.
     Design canvases use a completely separate "project" concept that happens to share the
     same JSON field name. Do not attempt to co-locate design-chats into `projects/` by
     name or uuid; they stay in their own top-level `design-chats/` category.

## Part B: local Claude Code sessions -> archive

No download needed. Reads what's already on this machine.

```
python scripts/parse_export.py index-code-sessions --parsed-dir "<parsed_dir>" --manifest "<parsed_dir>\manifest.json"
```

Walks every `~/.claude/projects/*/*.jsonl`, extracts only human-readable user/assistant
text (never raw tool output or file contents), writes/updates
`parsed_dir\code-sessions\<project>\*.md`, sharing the same manifest/index as Part A.

## After either part

Every `parse-*` and `index-code-sessions` command's JSON output includes a `changes` array
alongside the counts — one entry per new/updated item (`{status, title, project, path}`),
skipping unchanged ones. **Use it**: report the counts, but also actually name what's new
(conversation/project/memory titles), not just a number — the user should be able to see
what showed up without having to go dig through `index.md` themselves. Group by category if
there's more than a couple of items; skip categories with an empty `changes` list rather
than reporting "0 new" noise for each one. Then point the user at `<parsed_dir>\index.md`
for the full archive.

After Part A finishes parsing, offer to clean up the now-redundant downloaded zips/manifest
still sitting in Downloads (everything under step 4/5 has already been extracted into
`raw_dir` and parsed into `parsed_dir` by this point, so the Downloads copies are pure
clutter):
```
python scripts/parse_export.py cleanup-downloads --downloads-dir "<user's Downloads folder>"
```
Add `--dry-run` first if you want to show the user what would be deleted before actually
deleting. This only ever matches this tool's own exact filename patterns (the 5 category
zip names like `projects-000.zip` / `projects-000 (1).zip`, and `manifest-<id>-...json`) —
it will never touch an unrelated file in Downloads, even another `.zip`.

## Known limitation: browser tabs opened during Part A step 4 (fallback path only)

This only applies when the OS-shellout fallback (`Start-Process`/`open`/`xdg-open`) was
used because `claude-in-chrome` wasn't available. That shellout opens each link in the
user's *existing* default browser. There is no reliable way from here to close only the
specific tab that was opened (as opposed to the window, or another tab the user already
had open) without additional tooling. Don't attempt to blindly send close-tab keystrokes.
That risks closing a tab the user didn't want closed. Mention this limitation to the user
rather than silently leaving tabs open with no explanation.

When `claude-in-chrome` was available and used instead, this limitation doesn't apply.
`tabs_create_mcp`/`tabs_close_mcp` manage their own isolated tab group and can be closed
cleanly with no risk to the user's other tabs.
