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
/ `python3 --version` if unsure, don't assume. **macOS ships no `python` command, only
`python3`** (and most Linux distros are the same), so the commands below, which are written
as `python`, must be run as `python3` there. Installing Python won't add a `python` alias.
Paths in every example use forward slashes, which work on all platforms including Windows.
This file tells Claude what to do and in what order.

## First run: confirm storage location

Confirm with the user where the archive should live (a folder *outside* any git repo,
e.g. `~/ClaudeAI-Sync/`, with `raw/` and `parsed/` subfolders), then record it in
`config.json` next to this file. Copy `config.example.json` to `config.json` and fill in the
real paths (forward slashes work fine even on Windows and sidestep JSON backslash-escaping
mistakes, e.g. `"C:/Users/you/ClaudeAI-Sync/raw"`; on macOS,
`"/Users/you/ClaudeAI-Sync/raw"`).

**macOS: don't suggest `~/Documents` or `~/Desktop`.** If iCloud "Desktop & Documents" is on
(`defaults read com.apple.finder FXICloudDriveDocuments` prints `1`), a folder there is
uploaded to iCloud, and this archive is the user's full conversation history. Check that
setting before proposing a location, and prefer a folder directly under the home directory.
The same caution applies to any Dropbox/OneDrive/Google Drive folder.

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
   - **Only the "in progress" email found:** the export is running. Small exports can finish
     within seconds (in a real macOS run the "ready" email arrived 14 seconds after the "in
     progress" one), so re-run the search once after a minute or so before settling into a
     long poll. Don't ask the user to
     ping you back — poll for it yourself (e.g. `ScheduleWakeup` at ~20-30 min intervals, or
     whatever this session's equivalent of "check back later" is) and re-run the same Gmail
     search each time until the ready email appears. Tell the user once, up front, that
     you'll check back automatically rather than asking them to remind you.
   - **Neither email found:** only now trigger an export (Settings -> Privacy -> Export Data
     on claude.ai web; not available on mobile). Confirm with the user first, since it starts
     an export of their whole account and emails them. **If the `claude-in-chrome` connector
     is available you can do this yourself** (verified on macOS; the browser must already be
     logged in to claude.ai):
     1. Open `https://claude.ai/settings/data-privacy-controls` in a tab. It opens the
        Settings modal (the URL becomes `claude.ai/new#settings/data-privacy-controls`).
        If the panel is still a loading skeleton, wait a couple of seconds.
     2. `find` the "Export data" button in the "Your data" section and click it.
     3. The export panel has a **"Conversations from" range selector (All / 30 days / 90
        days / Custom), defaulting to All.** Use All for a first sync. The panel lists only
        "Conversations, Users, Projects", but the resulting manifest still contained all 5
        category files (memories and design chats included).
     4. Click "Export". An "Export started" toast confirms it. Close the tab, then go back
        to the Gmail search (the "in progress" email arrives within seconds).
     Otherwise, ask the user to do these steps themselves.

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
   button href). Confirm with the user if ambiguous. Pass `messageFormat: PLAIN_TEXT` if
   the connector offers it: this email's default `FULL_CONTENT` result is one very large
   HTML-only body, so match the `https://claude.ai/export/<uuid>/download/<hash>` href
   with a regex rather than reading the whole thing.

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
     - macOS: `open '<the link>'` (not yet verified on real hardware)
     - Linux: `xdg-open '<the link>'` (not yet verified on real hardware)
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
   Read that manifest, then **open each `export_url` in its own fresh tab, never two links
   in the same tab.** The sequence that is reliable in practice (verified on macOS, 5 of 5
   downloads, ~4-6 seconds each), run as separate steps, not batched into one parallel
   call (a batched close can run before the navigate):
   1. `tabs_context_mcp` with `createIfEmpty: true` (returns a fresh tab; the group was
      auto-removed when its last tab closed)
   2. `navigate` that tab to the `export_url`
   3. poll the Downloads folder for the exact expected filename, modified in the last
      couple of minutes and with no `<name>.crdownload` next to it, e.g. on macOS/Linux:
      `find ~/Downloads -maxdepth 1 -name "projects-000.zip" -mmin -2`
   4. `tabs_close_mcp` that tab, then repeat from step 1 for the next link

   **Don't** do `tabs_create_mcp` and then close the group's *original* tab, and then
   navigate in the new tab: on macOS that navigate failed with "Tab ... is not in Claude's
   tab group" (before the page loaded, so the link was not consumed) and left a blank
   "New tab" in the user's Chrome that the connector can't close. If it happens, recover
   with `tabs_context_mcp` `createIfEmpty: true` and retry the same link.
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
   Re-verified on macOS (Intel, macOS 15.6.1, Chrome via `claude-in-chrome`) on 2026-09-22
   with zero dropped downloads.

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
   python scripts/parse_export.py parse-projects       --projects-dir "<extracted>/projects" --parsed-dir "<parsed_dir>" --manifest "<parsed_dir>/manifest.json"
   python scripts/parse_export.py parse-memories        --json "<extracted>/memories/<account-uuid>.json" --parsed-dir "<parsed_dir>" --manifest "<parsed_dir>/manifest.json" --projects-dir "<extracted>/projects"
   python scripts/parse_export.py parse-conversations --json "<conversations.json>" --parsed-dir "<parsed_dir>" --manifest "<parsed_dir>/manifest.json" --projects-dir "<extracted>/projects"
   python scripts/parse_export.py parse-design-chats    --chats-dir "<extracted>/design_chats" --parsed-dir "<parsed_dir>" --manifest "<parsed_dir>/manifest.json"
   ```
   `fetch` extracts each zip into `<raw_dir>/<category>-000/` and prints the paths, so
   `<extracted>` above is a different folder per category, e.g.
   `<raw_dir>/projects-000/projects`, `<raw_dir>/memories-000/memories/<uuid>.json`,
   `<raw_dir>/conversations-000/conversations.json`,
   `<raw_dir>/design_chats-000/design_chats`.
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
python scripts/parse_export.py index-code-sessions --parsed-dir "<parsed_dir>" --manifest "<parsed_dir>/manifest.json"
```

Walks every `~/.claude/projects/*/*.jsonl`, extracts only human-readable user/assistant
text (never raw tool output or file contents), writes/updates
`parsed_dir/code-sessions/<project>/*.md`, sharing the same manifest/index as Part A.

## After either part

Every `parse-*` and `index-code-sessions` command's JSON output includes a `changes` array
alongside the counts — one entry per new/updated item (`{status, title, project, path}`),
skipping unchanged ones. **Use it**: report the counts, but also actually name what's new
(conversation/project/memory titles), not just a number — the user should be able to see
what showed up without having to go dig through `index.md` themselves. Group by category if
there's more than a couple of items; skip categories with an empty `changes` list rather
than reporting "0 new" noise for each one. Then point the user at `<parsed_dir>/index.md`
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
