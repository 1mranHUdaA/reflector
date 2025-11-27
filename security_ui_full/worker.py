import os
import subprocess
from urllib.parse import urlsplit, parse_qsl
from concurrent.futures import ThreadPoolExecutor

from db import SessionLocal
from models import Scan

executor = ThreadPoolExecutor(max_workers=4)


def _run_cmd(cmd: str):
    """Run a shell command, return (stdout, stderr)."""
    proc = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out, err = proc.communicate()
    return out.decode(errors="ignore"), err.decode(errors="ignore"), proc.returncode


def _extract_param_names_from_urls_file(path: str):
    if not os.path.exists(path):
        return []
    names = set()
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            url = line.strip()
            if not url:
                continue
            qs = urlsplit(url).query
            for k, _ in parse_qsl(qs, keep_blank_values=True):
                if k:
                    names.add(k.lower())
    return sorted(names)


def _extract_hidden_param_names_from_urls_file(path: str):
    # same logic as normal param extraction
    return _extract_param_names_from_urls_file(path)


def _read_lines_dedup(path: str):
    if not os.path.exists(path):
        return []
    items = []
    seen = set()
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line in seen:
                continue
            seen.add(line)
            items.append(line)
    return items


def pipeline_for_domain(domain: str, scan_id: int):
    session = SessionLocal()
    try:
        scan = session.query(Scan).get(scan_id)
        if not scan:
            return

        scan.status = "running"
        session.commit()

        domain = domain.strip()
        if not domain:
            scan.status = "error"
            session.commit()
            return

        base = domain  # used as prefix for files created by your scripts

        # 1) Run parameter.sh
        param_cmd = f"bash ./tools/parameter.sh {base}"
        _run_cmd(param_cmd)
        params_file = f"{base}_params_dedupe.txt"

        # 2) Run clean.sh
        clean_cmd = f"bash ./tools/clean.sh {base}"
        _run_cmd(clean_cmd)
        clean_file = f"{base}.txt"  # from clean.sh

        # 3) Run hidden.py with clean.sh output
        hidden_output = f"{base}_hidden_output.txt"
        if os.path.exists(clean_file):
            hidden_cmd = f"python3 ./tools/hidden.py -i {clean_file} -o {hidden_output}"
            _run_cmd(hidden_cmd)

        # 4) Build xss input file: union(params_file, hidden_output)
        union_file = f"{base}_xss_input.txt"
        urls_union = []
        seen = set()
        for path in (params_file, hidden_output):
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line in seen:
                            continue
                        seen.add(line)
                        urls_union.append(line)
        if urls_union:
            with open(union_file, "w", encoding="utf-8") as f:
                for u in urls_union:
                    f.write(u + "\n")

        # 5) Run xsslection.py with union_file as stdin
        reflected_file = "reflected.txt"
        # clear previous reflections to keep per-run clean
        if os.path.exists(reflected_file):
            os.remove(reflected_file)

        if os.path.exists(union_file):
            xss_cmd = f"cat {union_file} | python3 ./tools/xsslection.py"
            _run_cmd(xss_cmd)

        # ---- collect results for DB ----
        param_names = _extract_param_names_from_urls_file(params_file)
        hidden_names = _extract_hidden_param_names_from_urls_file(hidden_output)
        xss_urls = _read_lines_dedup(reflected_file)

        scan.parameters = ", ".join(param_names) if param_names else None
        scan.hidden_params = ", ".join(hidden_names) if hidden_names else None
        scan.xss_urls = "\n".join(xss_urls) if xss_urls else None
        scan.status = "done"
        session.commit()

    except Exception as e:
        scan = session.query(Scan).get(scan_id)
        if scan:
            scan.status = "error"
            scan.hidden_params = (scan.hidden_params or "") + f"\n[worker error] {e}"
            session.commit()
    finally:
        session.close()


def schedule_scan(domain: str) -> int | None:
    domain = (domain or "").strip()
    if not domain:
        return None
    session = SessionLocal()
    try:
        scan = session.query(Scan).filter_by(domain=domain).first()
        if not scan:
            scan = Scan(domain=domain, status="pending")
            session.add(scan)
            session.commit()
            session.refresh(scan)
        else:
            scan.status = "pending"
            scan.parameters = None
            scan.hidden_params = None
            scan.xss_urls = None
            session.commit()

        scan_id = scan.id
    finally:
        session.close()

    executor.submit(pipeline_for_domain, domain, scan_id)
    return scan_id
