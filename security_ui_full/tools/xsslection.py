#!/usr/bin/env python3
"""
xsslection.py - improved reflected XSS scanner.
"""

import sys
import concurrent.futures
import urllib3
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, unquote
import requests
import threading
import time

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

IGNORE_EXTENSIONS = (
    ".js", ".css", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
    ".ico", ".woff", ".woff2", ".ttf", ".eot", ".pdf", ".zip", ".rar",
    ".exe", ".bmp", ".mp4", ".mp3", ".avi", ".mov"
)

COMMON_SKIP_PARAMS = [
    "utm_", "fbclid", "gclid", "ref", "referrer", "session", "sid",
    "phpsessid", "jsessionid", "source", "trk", "clickid"
]

PAYLOAD = '"><xsslection>'
MARKER_RAW = "<xsslection>"
OUTPUT_FILE = "reflected.txt"

REQUEST_TIMEOUT = 12
MAX_WORKERS = 15
_reflected_lock = threading.Lock()


def should_skip_url_by_path(url: str) -> bool:
    path = urlparse(url).path or ""
    return any(path.lower().endswith(ext) for ext in IGNORE_EXTENSIONS)


def decode_query_params(raw_query: str):
    if not raw_query:
        return {}
    decoded = unquote(raw_query)
    return parse_qs(decoded, keep_blank_values=True)


def looks_like_file_value(value: str) -> bool:
    if not value:
        return False
    val = value.split("/")[-1].lower()
    return any(val.endswith(ext) for ext in IGNORE_EXTENSIONS)


def filter_parameters(params):
    filtered = []
    for name, values in params.items():
        lname = name.lower()
        if any(lname.startswith(skip) for skip in COMMON_SKIP_PARAMS):
            continue
        if any(looks_like_file_value(v) for v in values):
            continue
        filtered.append(name)
    return filtered


def replace_parameter(url, param, value):
    parsed = urlparse(url)
    qs = decode_query_params(parsed.query)
    if param in qs:
        qs[param] = [value]
    new_qs = urlencode(qs, doseq=True)
    return urlunparse(parsed._replace(query=new_qs))


def check_exact_marker_in_text(content: str):
    if content and MARKER_RAW in content:
        return True
    return False


def test_reflection(url, parameter, verbose=False, reflected_urls=None):
    try:
        if should_skip_url_by_path(url):
            if verbose:
                print(f"[skip] by path: {url}")
            return

        headers = {
            "User-Agent": "Mozilla/5.0 (XSS-Scanner)",
            "Accept": "*/*",
            "Connection": "close",
        }

        response = requests.get(url, headers=headers, verify=False, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        ctype = (response.headers.get("content-type") or "").lower()

        skip_types = ["image/", "video/", "audio/", "font/"]
        skip_types.extend([
            "text/plain",
            "text/xml",
            "application/json",
            "application/xml",
            "text/css",
            "text/javascript",
        ])

        if any(x in ctype for x in skip_types):
            if verbose:
                print(f"[-] [skip] content-type: {ctype}")
            return

        try:
            text = response.text
        except Exception:
            text = response.content.decode("utf-8", errors="ignore")


        is_reflected = check_exact_marker_in_text(text)

        if is_reflected and ctype.startswith("text/html"):
            print(f"[+] Reflection found in parameter '{parameter}': {url}")
            if verbose:
                print(f"    matched exact marker: {MARKER_RAW}")

            with _reflected_lock:
                if reflected_urls is not None:
                    reflected_urls.append(url)

    except requests.exceptions.RequestException as e:
        if verbose:
            print(f"[error] {url}: {e}")


def process_url(url, verbose=False, reflected_urls=None):
    parsed = urlparse(url)
    params = decode_query_params(parsed.query)
    if not params:
        if verbose:
            print(f"[info] no params in: {url}")
        return

    filtered = filter_parameters(params)
    if verbose:
        print(f"[*] Testing {url} with params: {filtered}")

    for p in filtered:
        test_url = replace_parameter(url, p, PAYLOAD)
        test_reflection(test_url, p, verbose, reflected_urls)


def process_urls(urls, verbose=False):
    reflected = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_url, u, verbose, reflected) for u in urls]
        for f in concurrent.futures.as_completed(futures):
            try:
                f.result()
            except Exception as e:
                if verbose:
                    print(f"[worker error] {e}")

    seen, unique = set(), []
    for u in reflected:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


def main(verbose=False):
    urls = [line.strip() for line in sys.stdin if line.strip()]
    if not urls:
        print("No URLs provided. Example:\n  cat urls.txt | python3 xsslection.py")
        return

    start = time.time()
    reflected = process_urls(urls, verbose)
    elapsed = time.time() - start

    if reflected:
        with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
            f.write("\n".join(reflected) + "\n")
        print(f"\nSaved {len(reflected)} reflected URL(s) to {OUTPUT_FILE}")
    else:
        print("\nNo reflections found.")

    if verbose:
        print(f"[done] {len(urls)} URLs processed in {elapsed:.2f}s")


if __name__ == "__main__":
    verbose_flag = "-v" in sys.argv[1:]
    main(verbose_flag)
