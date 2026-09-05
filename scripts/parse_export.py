#!/usr/bin/env python3
"""Sync claude.ai export data + local Claude Code sessions into one unified,
greppable markdown archive.

The claude.ai bulk export (Settings -> Privacy -> Export Data) is NOT a single
zip. The emailed "Download data" link returns a one-time manifest JSON listing
several category-specific one-time-use download URLs:
  - light_metadata : account/login metadata (not conversation content, not parsed)
  - projects       : one JSON file per Project, containing its knowledge docs
  - memories       : claude.ai's own cross-conversation memory (global + per-project)
  - design_chats   : one JSON file per Claude Design canvas chat
  - conversations  : a single JSON array of regular chat conversations

Subcommands:
  fetch                 Download (or accept a local) export category zip and unzip it.
  inspect-export         Print the real shape of a downloaded JSON file (run before parsing).
  parse-conversations    Parse conversations.json -> archive.
  parse-projects         Parse a directory of per-project JSON files -> archive.
  parse-design-chats     Parse a directory of per-design-chat JSON files -> archive.
  parse-memories         Parse the single memories JSON file -> archive.
  inspect-code-session   Print the real shape of one local Claude Code .jsonl session file.
  index-code-sessions    Parse local Claude Code session transcripts -> archive.

All field-name assumptions about each claude.ai export shape are isolated in
their respective extract_*() functions -- if inspect-export shows different
names, only that function needs editing.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ILLEGAL_PATH_CHARS = re.compile(r'[:\\/*?"<>|]')


def slugify(text, maxlen=60):
    text = ILLEGAL_PATH_CHARS.sub("-", text or "untitled").strip()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return (text or "untitled")[:maxlen]


def load_manifest(path: Path):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_manifest(path: Path, manifest: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def write_index(parsed_dir: Path, manifest: dict):
    """Index is always fully rebuilt from the manifest, so the manifest is the
    single source of truth and re-running never leaves stale rows behind."""
    lines = [
        "# Claude Archive Index",
        "",
        "| Title | Project | Related (heuristic) | Source | Updated | File |",
        "|---|---|---|---|---|---|",
    ]
    for key, entry in sorted(manifest.items(), key=lambda kv: kv[1].get("updated") or "", reverse=True):
        title = entry.get("title", "(untitled)")
        project = entry.get("project") or "Standalone"
        related = ", ".join(entry.get("related_projects") or []) or "-"
        source = entry.get("source", "?")
        updated = entry.get("updated", "")
        path = entry.get("path", "")
        lines.append(f"| {title} | {project} | {related} | {source} | {updated} | [{path}]({path}) |")
    (parsed_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")


def content_to_text(content):
    """Flattens either a plain string or a list of Anthropic-style content
    blocks into plain text, keeping only 'text' blocks (never tool_use/
    tool_result/thinking payloads)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def load_project_names(projects_dir):
    """Returns [(uuid, name), ...] for every project JSON file in a directory.
    Used both to co-locate project-memory with its matching project-docs
    folder, and to heuristically flag conversations that mention a project."""
    out = []
    d = Path(projects_dir) if projects_dir else None
    if d and d.exists():
        for f in sorted(d.glob("*.json")):
            try:
                p = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if p.get("uuid") and p.get("name"):
                out.append((p["uuid"], p["name"]))
    return out


def project_folder(name, pid):
    return Path("projects") / f"{slugify(name)}-{str(pid)[:8]}"


def design_chat_project_folder(name, pid):
    """Design canvases use their own unrelated 'project' uuid namespace (verified:
    zero overlap with real Projects), but two Design projects can still share the
    same display name -- suffix with that project's own uuid to avoid collisions,
    same fix already applied to project_folder()."""
    return Path("design-chats") / f"{slugify(name)}-{str(pid)[:8]}"


def compile_project_patterns(project_names):
    """Precompiles a word-boundary regex per known project name once, instead
    of rebuilding/rescanning per conversation."""
    patterns = []
    for _, name in project_names:
        if name and len(name) >= 4:
            patterns.append((name, re.compile(r"\b" + re.escape(name.lower()) + r"\b")))
    return patterns


def find_related_projects(title, summary, turns_text, project_patterns, exclude_name=None):
    """Heuristic only: word-boundary match of each known project name against
    conversation text, weighted by where the match falls. Not a hard link
    (conversations.json carries no project id at all) -- flags a *possible*
    mention for a human to judge, never used to move/group the file itself.

    A match in the title or summary is a strong signal -- one hit is enough.
    A match only inside the turn text is weaker: short, acronym-like names
    (<8 chars, e.g. "RMAS") need 3+ mentions there to count, since a single
    incidental mention (e.g. via an unrelated SC-clearance/military-service
    context) was observed to produce a false positive against real data;
    longer, more distinctive project names need only one."""
    strong_text = f"{title}\n{summary}".lower()
    weak_text = turns_text.lower()
    hits = []
    for name, pattern in project_patterns:
        if name == exclude_name:
            continue
        if pattern.search(strong_text):
            hits.append(name)
            continue
        min_occurrences = 1 if len(name) >= 8 else 3
        if len(pattern.findall(weak_text)) >= min_occurrences:
            hits.append(name)
    return sorted(set(hits))


def write_conversation_md(path: Path, title, project, created, updated, source, turns, related_projects=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_title = (title or "Untitled").replace('"', "'")
    lines = [
        "---",
        f'title: "{safe_title}"',
        f'project: "{project or "Standalone"}"',
        f'created: "{created or ""}"',
        f'updated: "{updated or ""}"',
        f'source: "{source}"',
    ]
    if related_projects:
        lines.append(f'related_projects: "{", ".join(related_projects)}"  # heuristic name match, not a confirmed link')
    lines += ["---", ""]
    for turn in turns:
        speaker = "**Human:**" if turn["role"] in ("human", "user") else "**Assistant:**"
        lines.append(speaker)
        lines.append("")
        lines.append(turn["text"])
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def manifest_upsert(manifest, key, title, project, source, created, updated, rel_path, related_projects=None):
    prev = manifest.get(key)
    if prev is None:
        status = "new"
    elif prev.get("updated") != updated or prev.get("related_projects") != (related_projects or []):
        status = "updated"
    else:
        return "unchanged"
    manifest[key] = {
        "title": title, "project": project, "source": source,
        "created": created, "updated": updated, "path": str(rel_path),
        "related_projects": related_projects or [],
    }
    return status


# --------------------------------------------------------------------------
# fetch
# --------------------------------------------------------------------------

def cmd_fetch(args):
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    if args.zip:
        zip_path = Path(args.zip)
        if not zip_path.exists():
            print(f"ERROR: zip not found at {zip_path}", file=sys.stderr)
            return 1
    elif args.url:
        zip_path = raw_dir / f"export-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.zip"
        req = urllib.request.Request(
            args.url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                content_type = resp.headers.get("Content-Type", "")
                data = resp.read()
        except urllib.error.HTTPError as e:
            print(f"FALLBACK_NEEDED: HTTP {e.code} fetching URL -- likely requires an authenticated browser session.", file=sys.stderr)
            return 2
        except urllib.error.URLError as e:
            print(f"FALLBACK_NEEDED: could not reach URL ({e.reason}).", file=sys.stderr)
            return 2

        if "html" in content_type.lower():
            print(f"FALLBACK_NEEDED: response Content-Type was '{content_type}', looks like an HTML page (login redirect?) rather than a zip.", file=sys.stderr)
            return 2

        zip_path.write_bytes(data)
    else:
        print("ERROR: must pass --url or --zip", file=sys.stderr)
        return 1

    extract_dir = raw_dir / zip_path.stem
    extract_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)
    except zipfile.BadZipFile:
        print("FALLBACK_NEEDED: downloaded file is not a valid zip (likely an HTML error page saved with a .zip name).", file=sys.stderr)
        return 2

    json_candidates = [str(p) for p in extract_dir.rglob("*.json")]
    print(json.dumps({"zip_path": str(zip_path), "extract_dir": str(extract_dir), "json_candidates": json_candidates}, indent=2))
    return 0


# --------------------------------------------------------------------------
# inspect-export (generic, works against any of the 4 real JSON shapes)
# --------------------------------------------------------------------------

def _summarize(v, depth=0):
    if isinstance(v, dict):
        if depth >= 2:
            return f"<dict, {len(v)} keys: {list(v.keys())[:10]}>"
        return {k: _summarize(v[k], depth + 1) for k in list(v.keys())[:20]}
    if isinstance(v, list):
        return {"_type": "list", "_len": len(v), "_sample": _summarize(v[0], depth + 1) if v else None}
    if isinstance(v, str):
        return v[:80]
    return v


def cmd_inspect_export(args):
    data = json.loads(Path(args.json).read_text(encoding="utf-8"))
    if isinstance(data, list):
        print(f"Top-level: list of {len(data)} items\n")
        if data:
            print(json.dumps(_summarize(data[0]), indent=2, default=str))
    elif isinstance(data, dict):
        print(f"Top-level: dict with keys: {list(data.keys())}\n")
        print(json.dumps(_summarize(data), indent=2, default=str))
    else:
        print(f"Top-level type: {type(data).__name__}")
    return 0


# --------------------------------------------------------------------------
# parse-conversations  (conversations.json: list of {uuid,name,summary,
# created_at,updated_at,account,chat_messages:[{uuid,text,content,sender,...}]})
# --------------------------------------------------------------------------

def title_from_turns(turns, fallback):
    """Falls back to the first substantive human message when a conversation
    has no real title -- mirrors the same fix applied to code-session titles."""
    for turn in turns:
        if turn["role"] not in ("human", "user"):
            continue
        first_line = turn["text"].strip().splitlines()[0].strip() if turn["text"].strip() else ""
        if first_line and not first_line.startswith("<"):
            return first_line[:80]
    return fallback


def extract_conversation_fields(convo: dict):
    conv_id = convo.get("uuid") or convo.get("id") or convo.get("conversation_id")
    raw_title = convo.get("name") or convo.get("title")

    project = None
    proj = convo.get("project")
    if isinstance(proj, dict):
        project = proj.get("name")
    elif isinstance(proj, str):
        project = proj

    created = convo.get("created_at") or convo.get("created")
    updated = convo.get("updated_at") or convo.get("updated") or created

    raw_messages = convo.get("chat_messages") or convo.get("messages") or []
    turns = []
    for m in raw_messages:
        role = m.get("sender") or m.get("role") or "unknown"
        text = m.get("text")
        if not text:
            text = content_to_text(m.get("content"))
        turns.append({"role": role, "text": text or ""})

    title = raw_title or title_from_turns(turns, "Untitled conversation")

    return {
        "id": str(conv_id) if conv_id else slugify(title),
        "title": title, "project": project, "created": created, "updated": updated, "turns": turns,
    }


def cmd_parse_conversations(args):
    parsed_dir = Path(args.parsed_dir)
    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)
    project_names = load_project_names(args.projects_dir) if args.projects_dir else []
    project_patterns = compile_project_patterns(project_names)

    conversations = json.loads(Path(args.json).read_text(encoding="utf-8"))
    if isinstance(conversations, dict):
        conversations = conversations.get("conversations", [conversations])

    counts = {"new": 0, "updated": 0, "unchanged": 0}
    for convo in conversations:
        fields = extract_conversation_fields(convo)
        key = f"claude-ai-conversation:{fields['id']}"
        rel_dir = Path("projects") / slugify(fields["project"]) if fields["project"] else Path("standalone")
        rel_path = rel_dir / f"{slugify(fields['title'])}-{fields['id'][:8]}.md"

        turns_text = "\n".join(t["text"] for t in fields["turns"])
        related = find_related_projects(fields["title"], convo.get("summary") or "", turns_text,
                                          project_patterns, exclude_name=fields["project"])

        status = manifest_upsert(manifest, key, fields["title"], fields["project"], "claude.ai",
                                  fields["created"], fields["updated"], rel_path, related)
        counts[status] = counts.get(status, 0) + 1
        if status == "unchanged":
            continue
        write_conversation_md(parsed_dir / rel_path, fields["title"], fields["project"],
                               fields["created"], fields["updated"], "claude.ai", fields["turns"], related)

    save_manifest(manifest_path, manifest)
    write_index(parsed_dir, manifest)
    counts["total"] = len(conversations)
    print(json.dumps(counts, indent=2))
    return 0


# --------------------------------------------------------------------------
# parse-projects  (directory of per-project JSON files: {uuid,name,description,
# created_at,updated_at,creator,docs:[{uuid,filename,content,created_at}]})
# --------------------------------------------------------------------------

def cmd_parse_projects(args):
    projects_dir = Path(args.projects_dir)
    parsed_dir = Path(args.parsed_dir)
    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)

    files = sorted(projects_dir.glob("*.json"))
    counts = {"new": 0, "updated": 0, "unchanged": 0, "skipped_errors": 0}
    for f in files:
        try:
            proj = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"WARNING: skipping unreadable project file {f}: {e}", file=sys.stderr)
            counts["skipped_errors"] += 1
            continue
        pid = proj.get("uuid") or f.stem
        name = proj.get("name") or "Untitled project"
        created = proj.get("created_at")
        updated = proj.get("updated_at") or created
        docs = proj.get("docs") or []

        key = f"claude-ai-project-docs:{pid}"
        rel_path = project_folder(name, pid) / "_project-knowledge.md"
        status = manifest_upsert(manifest, key, name, name, "claude.ai-project-docs", created, updated, rel_path)
        counts[status] = counts.get(status, 0) + 1
        if status == "unchanged":
            continue

        lines = [
            "---", f'title: "{name}"', f'project: "{name}"', f'created: "{created or ""}"',
            f'updated: "{updated or ""}"', 'source: "claude.ai-project-docs"', "---", "",
            proj.get("description") or "", "",
        ]
        for doc in docs:
            lines.append(f"## {doc.get('filename', '(untitled doc)')}")
            lines.append("")
            lines.append(doc.get("content") or "")
            lines.append("")
        abs_path = parsed_dir / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text("\n".join(lines), encoding="utf-8")

    save_manifest(manifest_path, manifest)
    write_index(parsed_dir, manifest)
    counts["total"] = len(files)
    print(json.dumps(counts, indent=2))
    return 0


# --------------------------------------------------------------------------
# parse-design-chats  (directory of per-chat JSON files: {uuid,title,project,
# created_at,updated_at,messages:[{uuid,role,content,created_at}]})
# --------------------------------------------------------------------------

def cmd_parse_design_chats(args):
    chats_dir = Path(args.chats_dir)
    parsed_dir = Path(args.parsed_dir)
    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)

    files = sorted(chats_dir.glob("*.json"))
    counts = {"new": 0, "updated": 0, "unchanged": 0, "skipped_errors": 0}
    for f in files:
        try:
            chat = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"WARNING: skipping unreadable design-chat file {f}: {e}", file=sys.stderr)
            counts["skipped_errors"] += 1
            continue
        cid = chat.get("uuid") or f.stem
        raw_title = chat.get("title")
        proj = chat.get("project") or {}
        project_name = proj.get("name") if isinstance(proj, dict) else (proj if isinstance(proj, str) else None)
        project_uuid = proj.get("uuid") if isinstance(proj, dict) else None
        created = chat.get("created_at")
        updated = chat.get("updated_at") or created

        turns = []
        for m in (chat.get("messages") or []):
            role = m.get("role") or m.get("sender") or "unknown"
            raw_content = m.get("content")
            text = m.get("text")
            if not text and isinstance(raw_content, dict):
                # design-chat schema nests the real text one level deeper
                # (content.content), unlike conversations.json's flat text field.
                # It can be either a plain string or another list of content blocks.
                nested = raw_content.get("content")
                if isinstance(nested, str):
                    text = nested
                elif isinstance(nested, list):
                    text = content_to_text(nested)
            if not text:
                text = content_to_text(raw_content)
            turns.append({"role": role, "text": text or ""})

        # "Chat" is claude.ai's generic default title for design canvas chats --
        # treat it the same as missing and fall back to the first real message.
        generic = not raw_title or raw_title.strip().lower() in ("chat", "untitled", "new chat")
        title = title_from_turns(turns, "Untitled design chat") if generic else raw_title

        key = f"claude-ai-design-chat:{cid}"
        if project_name and project_uuid:
            rel_dir = design_chat_project_folder(project_name, project_uuid)
        elif project_name:
            rel_dir = Path("design-chats") / slugify(project_name)
        else:
            rel_dir = Path("design-chats") / "standalone"
        rel_path = rel_dir / f"{slugify(title)}-{str(cid)[:8]}.md"
        status = manifest_upsert(manifest, key, title, project_name, "claude.ai-design", created, updated, rel_path)
        counts[status] = counts.get(status, 0) + 1
        if status == "unchanged":
            continue
        write_conversation_md(parsed_dir / rel_path, title, project_name, created, updated, "claude.ai-design", turns)

    save_manifest(manifest_path, manifest)
    write_index(parsed_dir, manifest)
    counts["total"] = len(files)
    print(json.dumps(counts, indent=2))
    return 0


# --------------------------------------------------------------------------
# parse-memories  (single JSON: {conversations_memory, project_memories:{id:text},
# memory_files:[{path,content,updated_at}], account_uuid})
# --------------------------------------------------------------------------

def cmd_parse_memories(args):
    data = json.loads(Path(args.json).read_text(encoding="utf-8"))
    parsed_dir = Path(args.parsed_dir)
    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)

    written = 0

    global_mem = data.get("conversations_memory")
    if global_mem:
        rel_path = Path("claude-ai-memory") / "global-memory.md"
        abs_path = parsed_dir / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(f"# Claude.ai Cross-Conversation Memory\n\n{global_mem}\n", encoding="utf-8")
        manifest["claude-ai-memory:global"] = {
            "title": "Global memory", "project": None, "source": "claude.ai-memory",
            "created": None, "updated": None, "path": str(rel_path),
        }
        written += 1

    project_names = dict(load_project_names(args.projects_dir)) if args.projects_dir else {}

    for proj_id, text in (data.get("project_memories") or {}).items():
        name = project_names.get(proj_id)
        if name:
            # Hard link: this memory's key IS the project's own uuid, so it can
            # be co-located with that project's _project-knowledge.md safely --
            # unlike design_chats, which turned out to be a different, unrelated
            # "project" namespace entirely (verified: zero uuid overlap).
            rel_path = project_folder(name, proj_id) / "_project-memory.md"
            title = f"Project memory: {name}"
            project_field = name
        else:
            rel_path = Path("claude-ai-memory") / "project-memories" / f"{proj_id}.md"
            title = f"Project memory ({proj_id})"
            project_field = proj_id
        abs_path = parsed_dir / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(f"# {title}\n\n{text}\n", encoding="utf-8")
        manifest[f"claude-ai-memory:project:{proj_id}"] = {
            "title": title, "project": project_field, "source": "claude.ai-memory",
            "created": None, "updated": None, "path": str(rel_path), "related_projects": [],
        }
        written += 1

    for mf in (data.get("memory_files") or []):
        path_field = mf.get("path", "untitled")
        stem = path_field[:-3] if path_field.endswith(".md") else path_field
        rel_path = Path("claude-ai-memory") / "memory-files" / f"{slugify(stem)}.md"
        abs_path = parsed_dir / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(f"# Memory File: {path_field}\n\n{mf.get('content', '')}\n", encoding="utf-8")
        manifest[f"claude-ai-memory:file:{path_field}"] = {
            "title": path_field, "project": None, "source": "claude.ai-memory",
            "created": None, "updated": mf.get("updated_at"), "path": str(rel_path),
        }
        written += 1

    save_manifest(manifest_path, manifest)
    write_index(parsed_dir, manifest)
    print(json.dumps({"items_written": written}, indent=2))
    return 0


# --------------------------------------------------------------------------
# inspect-code-session / index-code-sessions  (local Claude Code ~/.claude/projects)
# --------------------------------------------------------------------------

def _read_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def cmd_inspect_code_session(args):
    path = Path(args.jsonl)
    entries = list(_read_jsonl(path))
    print(f"{len(entries)} lines total\n")
    type_counts = {}
    for e in entries:
        type_counts[e.get("type", "?")] = type_counts.get(e.get("type", "?"), 0) + 1
    print("Entry types:", json.dumps(type_counts, indent=2))
    sample = next((e for e in entries if e.get("type") in ("user", "assistant") and not e.get("isMeta")), None)
    if sample:
        print("\nFirst real conversational entry:")
        print(json.dumps(_summarize(sample), indent=2, default=str))
    return 0


def cmd_index_code_sessions(args):
    claude_home = Path(args.claude_home)
    parsed_dir = Path(args.parsed_dir)
    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)

    projects_dir = claude_home / "projects"
    session_files = sorted(projects_dir.glob("*/*.jsonl")) if projects_dir.exists() else []

    counts = {"new": 0, "updated": 0, "unchanged": 0, "skipped_empty": 0}
    for session_path in session_files:
        project_key = session_path.parent.name
        session_id = session_path.stem

        turns = []
        first_ts = last_ts = None
        for entry in _read_jsonl(session_path):
            if entry.get("type") not in ("user", "assistant") or entry.get("isMeta"):
                continue
            text = content_to_text((entry.get("message") or {}).get("content"))
            if not text.strip():
                continue
            role = (entry.get("message") or {}).get("role", entry.get("type"))
            turns.append({"role": role, "text": text})
            ts = entry.get("timestamp")
            if ts:
                first_ts = first_ts or ts
                last_ts = ts

        if not turns:
            counts["skipped_empty"] += 1
            continue

        title = session_id
        for turn in turns:
            first_line = turn["text"].strip().splitlines()[0].strip() if turn["text"].strip() else ""
            if first_line and not first_line.startswith("<"):
                title = first_line[:80]
                break

        key = f"code-session:{session_id}"
        rel_path = Path("code-sessions") / project_key / f"{slugify(title)}-{session_id[:8]}.md"
        status = manifest_upsert(manifest, key, title, project_key, "Claude Code", first_ts, last_ts, rel_path)
        counts[status] = counts.get(status, 0) + 1
        if status == "unchanged":
            continue
        write_conversation_md(parsed_dir / rel_path, title, project_key, first_ts, last_ts, "Claude Code", turns)

    save_manifest(manifest_path, manifest)
    write_index(parsed_dir, manifest)
    counts["total_sessions_seen"] = len(session_files)
    print(json.dumps(counts, indent=2))
    return 0


# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("fetch")
    p.add_argument("--url")
    p.add_argument("--zip")
    p.add_argument("--raw-dir", required=True)
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("inspect-export")
    p.add_argument("--json", required=True)
    p.set_defaults(func=cmd_inspect_export)

    p = sub.add_parser("parse-conversations")
    p.add_argument("--json", required=True)
    p.add_argument("--parsed-dir", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--projects-dir", help="Enables heuristic related_projects name-matching against known project names")
    p.set_defaults(func=cmd_parse_conversations)

    p = sub.add_parser("parse-projects")
    p.add_argument("--projects-dir", required=True)
    p.add_argument("--parsed-dir", required=True)
    p.add_argument("--manifest", required=True)
    p.set_defaults(func=cmd_parse_projects)

    p = sub.add_parser("parse-design-chats")
    p.add_argument("--chats-dir", required=True)
    p.add_argument("--parsed-dir", required=True)
    p.add_argument("--manifest", required=True)
    p.set_defaults(func=cmd_parse_design_chats)

    p = sub.add_parser("parse-memories")
    p.add_argument("--json", required=True)
    p.add_argument("--parsed-dir", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--projects-dir", help="Enables co-locating each project's memory into its own project folder (uuid-matched)")
    p.set_defaults(func=cmd_parse_memories)

    p = sub.add_parser("inspect-code-session")
    p.add_argument("--jsonl", required=True)
    p.set_defaults(func=cmd_inspect_code_session)

    p = sub.add_parser("index-code-sessions")
    p.add_argument("--claude-home", default=str(Path.home() / ".claude"))
    p.add_argument("--parsed-dir", required=True)
    p.add_argument("--manifest", required=True)
    p.set_defaults(func=cmd_index_code_sessions)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
