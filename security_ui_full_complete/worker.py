import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit, parse_qsl

from db import SessionLocal
from models import Scan

executor = ThreadPoolExecutor(max_workers=4)

def _run_cmd(cmd: str):
    try:
        subprocess.run(cmd, shell=True, check=False)
    except:
        pass

def _read_lines_dedup(path: str):
    if not os.path.exists(path):
        return []
    seen=set()
    out=[]
    for l in open(path, "r", encoding="utf-8", errors="ignore"):
        l=l.strip()
        if l and l not in seen:
            seen.add(l)
            out.append(l)
    return out

def _extract_param_names(path: str):
    if not os.path.exists(path):
        return []
    names=set()
    for url in _read_lines_dedup(path):
        qs=urlsplit(url).query
        for k,_ in parse_qsl(qs, keep_blank_values=True):
            if k:
                names.add(k.lower())
    return sorted(names)

def _pipeline_for_domain(domain: str, scan_id: int):
    session=SessionLocal()
    try:
        scan=session.query(Scan).get(scan_id)
        scan.status="running"
        session.commit()

        base=domain

        # Run tools
        _run_cmd(f"bash ./tools/clean.sh {base}")
        clean=f"{base}.txt"

        _run_cmd(f"bash ./tools/parameter.sh {base}")
        params=f"{base}_params_dedupe.txt"

        hidden=f"{base}_hidden_output.txt"
        if os.path.exists(clean):
            _run_cmd(f"python3 ./tools/hidden.py -i {clean} -o {hidden}")

        union=f"{base}_xss_input.txt"
        merged=[]
        seen=set()
        for f in (params,hidden):
            for line in _read_lines_dedup(f):
                if line not in seen:
                    seen.add(line)
                    merged.append(line)

        with open(union,"w") as f:
            f.write("\n".join(merged))

        if os.path.exists("reflected.txt"):
            os.remove("reflected.txt")

        _run_cmd(f"cat {union} | python3 ./tools/xsslection.py")

        scan.parameters = ", ".join(_extract_param_names(params)) or None
        scan.hidden_params = ", ".join(_extract_param_names(hidden)) or None
        scan.xss_urls = "\n".join(_read_lines_dedup("reflected.txt")) or None
        scan.status="done"
        session.commit()

    except Exception as e:
        scan=session.query(Scan).get(scan_id)
        scan.status="error"
        scan.hidden_params=f"PIPELINE ERROR: {e}"
        session.commit()
    finally:
        session.close()

def schedule_scan(domain: str):
    session=SessionLocal()
    scan=Scan(domain=domain,status="pending")
    session.add(scan)
    session.commit()
    session.refresh(scan)
    scan_id=scan.id
    session.close()
    executor.submit(_pipeline_for_domain, domain, scan_id)
