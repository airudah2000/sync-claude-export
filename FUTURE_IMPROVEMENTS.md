# Future Improvements

Deferred work for `sync-claude-export`, written so each item can be pasted almost
directly into a GitHub issue once this becomes its own repo.

---

## 1. Isolated browser automation (Playwright) for downloads

**Problem:** Part A step 4 uses `Start-Process <url>` to open each export download link
in the user's *existing* default browser. This works for triggering the download (it
rides on the user's already-logged-in session), but has two real downsides:
- No handle on the resulting tab/window, so nothing opened this way can be cleanly
  closed afterward without risking closing a tab the user didn't open themselves
  (blindly sending a close-tab keystroke was explicitly ruled out for this reason).
- Windows-only (`Start-Process` doesn't exist on macOS/Linux -- see item 3).

**Proposed fix:** Use Playwright (or Selenium) to drive a separate, isolated,
automation-controlled browser instance instead of the user's regular one. Concretely:
- Launch a persistent browser context once, pointed at the user's real browser profile
  directory (so it inherits the claude.ai login session) but as its own controllable
  process.
- Navigate to each `export_url`, wait for the download event, save it directly to
  `raw_dir` (skipping the Downloads-folder detour entirely).
- Close that automation-controlled window when done -- since it's a process this skill
  launched and owns end-to-end, closing it can never touch a tab/window the user didn't
  open through this skill.

**Cost/tradeoff:** adds a real dependency (`playwright` + a browser binary download,
first-run `playwright install`), so it's a deliberate upgrade, not a one-line change.

**Update:** discovered a simpler alternative that may make this unnecessary when
available -- the `claude-in-chrome` MCP connector's `tabs_create_mcp`/`tabs_close_mcp`
tools manage their own isolated tab group, separate from the user's regular tabs.
Verified working end-to-end (navigate, read page text, close cleanly) in a real session.
If that connector is available, prefer it over adding a Playwright dependency -- it's
zero-setup and solves the exact "don't touch tabs I didn't open" requirement. Playwright
would only still be worth it if `claude-in-chrome` isn't available in a given environment
(e.g. this becomes a fully standalone script with no MCP host at all).

---

## 2. Recurring re-export reminder

**Problem:** claude.ai's export trigger step (Settings -> Privacy -> Export Data) cannot
be automated -- there's no API for it. Left alone, the local archive silently goes stale.

**Proposed fix:** A periodic (e.g. monthly) scheduled nudge (via Claude Code's
`schedule`/`CronCreate` mechanism) reminding the user to re-trigger the export.

**Open question, validate before building on it:** whether a scheduled/cron cloud-agent
run has access to this session's Gmail MCP connector at all. If yes, the scheduled job
could opportunistically check "has a fresh export email arrived?" and only remind the
user if none is found; if no, it can only ever be a static reminder message. Test with
one throwaway scheduled job before relying on either assumption.

---

## 3. Smarter-than-substring related-project matching

**Problem:** `find_related_projects()` (parse-conversations) does a plain case-insensitive
substring match of each known project name against conversation text. Verified against
real data it produces real hits (Sandhurst prep -> RMAS, a JPMC interview-prep
conversation -> My professional profile) but also at least one plausible false positive
(an immigration-strategy conversation matched "RMAS," most likely from an incidental
acronym mention e.g. via SC-clearance/military-service context, not because the
conversation is actually about Sandhurst).

**Proposed fix:** a semantic pass (e.g. embedding similarity between conversation summary
and project description, or an LLM classification call) instead of/in addition to plain
substring matching, to reduce false positives on short or acronym-like project names.
Low priority -- the current heuristic is explicitly labeled as unconfirmed in both the
frontmatter and the index, so a wrong flag is visible and low-cost, not silently trusted.

---

## Not on this list (already resolved)

- Title-derivation picking up raw `<command-name>...>` log lines instead of real text --
  fixed.
- Memory-file output paths ending in a double `.md.md` extension -- fixed.
- Idempotent re-sync (no duplicate files on re-run) -- verified working.
- Project-docs folder collision: two different projects both named "Untitled project"
  shared one output path (`projects\Untitled-project\_project-knowledge.md`), silently
  overwriting each other -- fixed by suffixing the folder with the project's short id
  (`projects\<slug>-<id>\`). Verified against real data: 13 source project files -> 13
  distinct output folders, zero path collisions across the whole manifest.
- Title fallback: conversations/design-chats with no real title (or claude.ai's generic
  "Chat" default) now fall back to the first substantive human message instead of a bare
  "Untitled conversation"/"Untitled design chat" placeholder. Reduced untitled
  conversations from 42/58 to 35/58 and untitled design chats from 5/5 to 2/5 against
  real data -- the remainder are genuinely title-less (empty message lists or
  tool-call-only turns with no human text at all), not a parsing gap.
- Discovered while fixing the above: design-chat messages use a different, more deeply
  nested content schema than regular conversations (`message.content.content` holds the
  actual text, vs. `chat_messages[].text` directly for regular conversations) --
  `content_to_text()` alone didn't handle it; added a design-chat-specific unwrap step.
- Confirmed (not a bug, a real data limitation): the claude.ai bulk export's
  `conversations.json` contains no project-linked conversations at all -- all 58 in this
  account's export were standalone, and no conversation carried a `project` field. Each
  Project's export only includes its knowledge docs, not the chats that happened inside
  it. Conversation-to-project co-location in the archive may simply never populate for
  this reason, not because of a parsing bug.
- Investigated whether other export categories hold a usable conversation<->project link
  the parser was missing: `light_metadata` (users.json/login_history.json) is purely
  account/login data, nothing usable there. `design_chats` DOES carry a `project` field,
  but verified against real data it's a completely different, unrelated uuid namespace
  from real Projects (0/5 matched) -- a Design-canvas-specific concept that happens to
  share the field name "project," not a hard link. Left design-chats in their own
  top-level folder rather than incorrectly merging them into `projects/`.
- Added what actually IS a hard link, once found: claude.ai's per-project memory
  (`memories.json`'s `project_memories`) is keyed by the same project uuid as
  `parse-projects` -- confirmed and now co-located as `_project-memory.md` next to each
  project's `_project-knowledge.md`, instead of sitting in a disconnected top-level folder.
- Added a heuristic (not hard-link) `related_projects` annotation to conversations, since
  no real link exists for them -- see item 3 above for its known limitation.
- Cross-platform support: `SKILL.md` step 4 now prefers the `claude-in-chrome` MCP
  connector (OS-agnostic, cleanly closable tabs) by default, falling back to per-OS
  shellouts (`Start-Process` / `open` / `xdg-open`) only when that connector isn't
  available. `parse_export.py` was already plain Python + pathlib and needed no changes.
- Design-chat folder collision: two same-named Design canvas "projects" would silently
  overwrite each other's output folder (no uuid suffix, unlike the real-project fix
  above) -- fixed by suffixing with the design-chat's own project uuid.
- Design-chat nested-content unwrap only handled a plain string `content.content`; a
  list-of-blocks form silently yielded empty text -- fixed to recurse through
  `content_to_text()` for that case too.
- No per-file error isolation in `parse-projects`/`parse-design-chats`: one malformed
  JSON file crashed the whole run -- fixed with a per-file try/except (skip + warn +
  count in a new `skipped_errors` counter), matching the pattern `load_project_names()`
  already used.
- Added a small `unittest`-based test suite (`tests/test_parse_export.py`, no external
  dependencies) covering the above fixes plus title-fallback and manifest-transition
  behavior.
