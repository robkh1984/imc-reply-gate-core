"""transcript_util.py (imc-reply-gate 0.2.17): read the session transcript the harness writes, not text Claude wrote."""
import glob, json, os, re

SYSTEM_PREFIXES = ("<system-reminder", "[SYSTEM", "Another Claude session", "<task-notification", "<routine-fire", "Called the", "Note:", "<command-", "Caveat:", "This session is being continued", "<artifact-content-authored-by-others", "Stop hook feedback:", "Base directory for this skill:")  # 0.3.77: a loaded skill body is not Rob's message (measured 2026-11-19 2:30 PM PST: handoff:save text raised 10 SCOPE-UNREAD fails)


def find_transcript():
    p = os.environ.get("REPLY_GATE_TRANSCRIPT")
    if p and os.path.isfile(p):
        return p
    c = glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))
    # 0.3.84 (OI-0491 LIVE-READ-MISSING): reviewpanel.py runs `claude -p` probes whose cwd is a temp
    # directory, so the harness writes their transcripts under ~/.claude/projects/-tmp/ and
    # ~/.claude/projects/-private-tmp/. Those are the NEWEST jsonl right after a panel run, so the
    # unfiltered max() below returned the gate's own probe instead of the session, and every check
    # reading the transcript then saw a session that had made no tool calls. Measured 2026-11-20
    # 09:40 PST: the only jsonl in a cloud container was ~/.claude/projects/-tmp/bc2eddb8-....jsonl
    # with 0 occurrences of memory_read, in a session that had just read two memory files.
    real = [x for x in c if not re.match(r"^-(?:private-)?tmp$|^-var-folders", os.path.basename(os.path.dirname(x)))]
    if real:
        return max(real, key=os.path.getmtime)
    # Only probe transcripts exist: returning one of them produces a FALSE failure, so report no
    # transcript. Callers already treat None as "could not run", which is an instrument result.
    return None


def entries(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            try:
                yield json.loads(ln)
            except ValueError:
                continue


def _blocks(e):
    m = e.get("message") or {}
    c = m.get("content")
    if isinstance(c, str):
        return [{"type": "text", "text": c}]
    return c if isinstance(c, list) else []


def user_texts(path):
    """Genuine user messages in order (no tool results, no system notices)."""
    out = []
    for e in entries(path):
        if e.get("type") != "user":
            continue
        for b in _blocks(e):
            if b.get("type") == "text":
                t = b.get("text", "").strip()
                if t and not t.startswith(SYSTEM_PREFIXES):
                    out.append(t)
    return out


def agent_prompts(path):
    """Prompts of every Agent/Task subagent call, in order (harness-written tool_use records)."""
    out = []
    for e in entries(path):
        if e.get("type") != "assistant":
            continue
        for b in _blocks(e):
            if b.get("type") == "tool_use" and b.get("name") in ("Agent", "Task"):
                out.append((b.get("input") or {}).get("prompt", ""))
    return out


def tool_inputs_and_results(path):
    """All tool_use inputs and tool_result texts as one list of strings each."""
    uses, results = [], []
    for e in entries(path):
        for b in _blocks(e):
            if b.get("type") == "tool_use":
                uses.append(json.dumps(b.get("input") or {}, ensure_ascii=False))
            elif b.get("type") == "tool_result":
                c = b.get("content")
                results.append(c if isinstance(c, str) else json.dumps(c, ensure_ascii=False))
    return uses, results
