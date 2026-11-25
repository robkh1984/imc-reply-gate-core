#!/usr/bin/env python3
"""pipeline_selftest.py (0.3.75): the reply-gate pipeline steps pass preaction.py without a stamp; everything else still needs one."""
import importlib.util, os, sys, tempfile
os.environ["IMC_PREACTION_DIR"] = tempfile.mkdtemp()
HERE = os.path.dirname(os.path.abspath(__file__))
sp = importlib.util.spec_from_file_location("pa", os.path.join(os.path.dirname(HERE), "hooks", "preaction.py"))
pa = importlib.util.module_from_spec(sp); sp.loader.exec_module(pa)
P = "/root/.claude/plugins/synced/4d1d_1a9c/imc-reply-gate~g2"; M = "/Users/robk/.claude/plugins/synced/4d1d/imc-reply-gate"
CASES = [("Bash", {"command": 'python3 "%s/checker/precheck.py" /tmp/x/scratchpad/reply.md' % P}, 0),
         ("Bash", {"command": "timeout 170 python3 %s/hooks/reviewpanel.py review /tmp/seeded.md" % P}, 0),
         ("Bash", {"command": 'python3 "%s/checker/precheck.py" /tmp/ab.md' % M}, 0),
         ("Write", {"file_path": "/tmp/claude-0/abc/scratchpad/reply-1.md.review"}, 0),
         ("Agent", {"prompt": "review"}, 0), ("SubagentHandback", {}, 0), ("SendUserMessage", {"message": "x"}, 0),
         ("Bash", {"command": "python3 /tmp/evil/imc-reply-gate/checker/precheck.py d.md"}, 2),
         ("Bash", {"command": "python3 %s/checker/precheck.py d.md; rm -rf ~" % P}, 2),
         ("Bash", {"command": "python3 %s/checker/precheck.py d.md > ~/.claude/x" % P}, 2),
         ("Bash", {"command": "python3 /root/.claude/plugins/synced/x/../../../tmp/imc-reply-gate/checker/precheck.py d.md"}, 2),
         ("Bash", {"command": "python3 other.py"}, 2),
         ("Write", {"file_path": "/Users/robk/Claude/Improving-my-Claude/INTAKE.md"}, 2),
         ("Write", {"file_path": "/tmp/x/../../root/.claude/settings.json"}, 2),
         ("Write", {"file_path": "/tmp/x/scratchpad/run.py"}, 2),
         ("Edit", {"file_path": P + "/hooks/gate.py"}, 2),
         ("mcp__claude-code-remote__update_trigger", {}, 2)]
bad = [(t, i) for t, i, want in CASES if pa.decide(t, i, "s1")[0] != want]
for t, i in bad: print("FAIL", t, i)
print("PIPELINE SELFTEST OK (%d cases)" % len(CASES) if not bad else "PIPELINE SELFTEST FAIL (%d)" % len(bad))
sys.exit(1 if bad else 0)
