import os,sys,tempfile,time,importlib.util,json,subprocess
core=sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def load(n,p):
    sp=importlib.util.spec_from_file_location(n,p); m=importlib.util.module_from_spec(sp); sp.loader.exec_module(m); return m
pa=load("pa",os.path.join(core,"hooks/preaction.py"))
tmp=tempfile.mkdtemp(); os.environ["TMPDIR"]=tmp
pa.DIR="/dev/null/imc-preaction"   # unwritable, like ~/.claude inside the Mac sandbox
S="sbxtest-%d"%int(time.time())
ok=0;tot=0
def t(name,got,want):
    global ok,tot; tot+=1; r=got==want; ok+=r; print(("ok  " if r else "FAIL"),name,"got",repr(got)[:120])
t("stamp falls back when home store is unwritable",pa.write_stamp(S,"write the test file now","prove the sandbox fallback works","no defect: selftest of fallback",multi=False),"ok")
t("fallback file is under TMPDIR",pa.LAST_WRITTEN.startswith(tmp),True)
c=pa.check_stamp(S); t("hook-side check finds the fallback stamp",c[0],True)
t("decide allows a write with the fallback stamp",pa.decide("Write",{"file_path":"/x"},S)[0],0)
t("CONTROL: the one-shot stamp is consumed in the fallback file",pa.decide("Write",{"file_path":"/x"},S)[0],2)
pa2=load("pa2",os.path.join(core,"hooks/preaction.py")); pa2.DIR="/dev/null/x"
t("CONTROL: no stamp for another session",pa2.check_stamp(S+"-other")[0],False)
os.environ["IMC_PREACTION_DIR"]="/dev/null/y"
t("CONTROL: explicit IMC_PREACTION_DIR disables fallback",pa2._fallback_dirs(),[])
del os.environ["IMC_PREACTION_DIR"]
# precheck fallback through gate.sandbox_fallbacks
g=load("g",os.path.join(core,"hooks/gate.py"))
fb=g.sandbox_fallbacks("imc-reply-gate-prechecked.tsv")
t("gate fallback list starts with TMPDIR",fb[0],os.path.join(tmp,"imc-reply-gate-prechecked.tsv"))
open(fb[0],"a").write("deadbeef\t2026\t/x\n")
g.PRECHECKED="/dev/null/z.tsv"
t("prechecked() reads the fallback file",g.prechecked("deadbeef"),True)
t("CONTROL: prechecked() false for unknown sha",g.prechecked("cafebabe"),False)
print("%d of %d ok"%(ok,tot)); sys.exit(0 if ok==tot else 1)
