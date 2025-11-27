
from .database import SessionLocal
from .models import Scan
import subprocess, os
from urllib.parse import urlsplit, parse_qsl

def run(cmd): return subprocess.getoutput(cmd)

def lines(path):
    if not os.path.exists(path): return []
    out=[]; seen=set()
    for l in open(path):
        l=l.strip()
        if l and l not in seen:
            seen.add(l); out.append(l)
    return out

def extract_params(path):
    out=set()
    for u in lines(path):
        for k,_ in parse_qsl(urlsplit(u).query):
            out.add(k.lower())
    return sorted(out)

def pipeline_for_domain(domain, scan_id):
    db=SessionLocal()
    s=db.query(Scan).get(scan_id)
    s.status="running"; db.commit()
    base=domain

    run(f"bash ./tools/clean.sh {base}")
    clean=f"{base}.txt"

    run(f"bash ./tools/parameter.sh {base}")
    params=f"{base}_params_dedupe.txt"

    hidden=f"{base}_hidden_output.txt"
    if os.path.exists(clean):
        run(f"python3 ./tools/hidden.py -i {clean} -o {hidden}")

    union=f"{base}_xss_input.txt"
    merged=[]
    for f in (params, hidden):
        merged += lines(f)
    with open(union,"w") as f: f.write("\n".join(merged))

    if os.path.exists("reflected.txt"): os.remove("reflected.txt")
    run(f"cat {union} | python3 ./tools/xsslection.py")

    s.parameters = ", ".join(extract_params(params)) or None
    s.hidden_params = ", ".join(extract_params(hidden)) or None
    s.xss_urls = "\n".join(lines("reflected.txt")) or None
    s.status="done"
    db.commit()
    db.close()
