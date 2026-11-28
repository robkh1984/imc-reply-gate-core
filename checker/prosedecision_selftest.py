"""OI-0826 control (Rob 2026-11-27 "Approved"): check_prose_decision must fire on a reply that asks Rob in prose even when
the reply has no table, and must stay quiet on a reply with no ask. Pipes drafts through checker/precheck.py."""
import os, subprocess, sys, tempfile
here = os.path.dirname(os.path.abspath(__file__))
def run(text):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "draft.md")
    open(p, "w").write(text)
    env = dict(os.environ, HOME=d)
    r = subprocess.run([sys.executable, os.path.join(here, "precheck.py"), p], capture_output=True, text=True, env=env)
    return r.stdout + r.stderr
bad = 0
def chk(name, ok):
    global bad
    print(("ok    " if ok else "FAIL  ") + name)
    bad += 0 if ok else 1
ask = 'Waiting on your call for the classifier prompt (or an "unstamped is fine") before I send the corrected report.\n'
chk("POSITIVE table-less prose ask -> PROSE-DECISION named", "PROSE-DECISION" in run(ask))
chk("CONTROL table-less reply with no ask -> PROSE-DECISION absent", "PROSE-DECISION" not in run("The register row is filed; nothing is waiting on you.\n"))
print("PROSEDECISION SELFTEST " + ("OK" if not bad else "FAILED"))
sys.exit(1 if bad else 0)
