#!/usr/bin/env python3
"""precheckshim_selftest.py - controls for ensure_precheck_shim (core serial 7, OI-0794)."""
import os, sys, tempfile, pathlib, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hooks"))
import gate as G
bad = 0
def ck(name, cond):
    global bad
    bad += not cond
    print("  %-4s %s" % ("ok" if cond else "FAIL", name))
d = pathlib.Path(tempfile.mkdtemp())
ck("no loader.py: does nothing", G.ensure_precheck_shim(str(d)) == "no loader plug-in" and not (d / "checker").exists())
(d / "loader.py").write_text("# stand-in\n")
ck("loader plug-in: shim written", G.ensure_precheck_shim(str(d)) == "written")
ck("second session start: present, not rewritten", G.ensure_precheck_shim(str(d)) == "present")
(d / "checker" / "precheck.py").write_text("stale\n")
ck("a stale shim is replaced", G.ensure_precheck_shim(str(d)) == "written")
core = pathlib.Path(__file__).resolve().parent.parent
os.symlink(core, d / "core")
r = subprocess.run([sys.executable, str(d / "checker" / "precheck.py"), "--help"], capture_output=True, text=True,
                   env=dict(os.environ, HOME=str(d)))
ck("the shim runs the bundled precheck when no cache exists", "no such draft" in (r.stdout + r.stderr))
print("PRECHECKSHIM SELFTEST %s" % ("FAIL" if bad else "OK"))
sys.exit(1 if bad else 0)
