#!/usr/bin/env python3
import requests
import re
import argparse
import hashlib
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from itertools import combinations
import threading

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

seen_hashes = set()
output_set = set()
lock = threading.Lock()

MAX_URLS_PER_PAGE = 500

def normalize_html(html):
    clean = re.sub(r'\d+', '', html)
    clean = re.sub(r'[A-Za-z0-9]{20,}', '', clean)
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip()

def html_hash(html):
    normalized = normalize_html(html)
    return hashlib.md5(normalized.encode(errors="ignore")).hexdigest()

def generate_urls(clean_url, params):
    found_params = list(params.keys())
    urls = set()

    for p in found_params:
        urls.add(f"{clean_url}?{p}=test")


    for keep_param in found_params:
        query_parts = []
        for p in found_params:
            value = params[p] if params[p] else "test"
            if p != keep_param:
                value = "test"
            query_parts.append(f"{p}={value}")
        urls.add(f"{clean_url}?{'&'.join(query_parts)}")


    for remove in combinations(found_params, 1):
        remaining = [p for p in found_params if p not in remove]
        for keep_param in remaining:
            query_parts = []
            for p in remaining:
                value = params[p] if params[p] else "test"
                if p != keep_param:
                    value = "test"
                query_parts.append(f"{p}={value}")
            urls.add(f"{clean_url}?{'&'.join(query_parts)}")


    if len(urls) > MAX_URLS_PER_PAGE:
        urls = set(list(urls)[:MAX_URLS_PER_PAGE])

    return urls

def fetch_and_extract(url, timeout=10):
    try:
        response = requests.get(
            url, timeout=timeout, verify=False, allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        if not response.text.strip():
            return

        page_hash = html_hash(response.text)
        with lock:
            if page_hash in seen_hashes:
                print(f"[~] Skipping duplicate content: {url}")
                return
            seen_hashes.add(page_hash)

        soup = BeautifulSoup(response.text, "html.parser")
        inputs = soup.find_all("input")


        params = {}
        for inp in inputs:
            t = inp.get("type", "").lower()
            if t == "hidden" or inp.has_attr("hidden") or "display:none" in str(inp).lower():
                name = inp.get("name")
                value = inp.get("value", "").strip() if inp.get("value") else ""
                if name:
                    params[name] = value if value != "" else "test"

        if params:
            parsed = urlparse(url)
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            print(f"[+] {url} -> hidden params: {', '.join(params.keys())}")

            urls_generated = generate_urls(clean_url, params)
            with lock:
                for u in urls_generated:
                    output_set.add(u)
                    print(u)

    except requests.exceptions.RequestException as e:
        print(f"[!] Network error for {url}: {e}")
    except Exception as e:
        print(f"[!] Unexpected error processing {url}: {e}")

def read_urls(input_file):
    urls = set()
    try:
        with open(input_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.add(line)
    except FileNotFoundError:
        print(f"[!] Input file not found: {input_file}")
    except Exception as e:
        print(f"[!] Error reading input file: {e}")
    return sorted(urls)

def main():
    parser = argparse.ArgumentParser(description="Extract hidden input parameters from URLs (skips duplicate HTML)."})
    parser.add_argument("-i", "--input", required=True, help="Input file with URLs (one per line)")
    parser.add_argument("-o", "--output", default="output.txt", help="Output file to store results")
    parser.add_argument("-t", "--threads", type=int, default=10, help="Number of threads")
    parser.add_argument("--timeout", type=int, default=10, help="Request timeout (seconds)")
    args = parser.parse_args()

    urls = read_urls(args.input)
    if not urls:
        print("[!] No valid URLs found in input file.")
        return

    print(f"[*] Starting: {len(urls)} URLs | threads={args.threads} | timeout={args.timeout}s")


    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        for url in urls:
            executor.submit(fetch_and_extract, url, args.timeout)


    if output_set:
        with open(args.output, "w", encoding="utf-8") as out:
            for u in sorted(output_set):
                out.write(u + "\n")
        print(f"\n[+] Saved {len(output_set)} unique parameterized URLs to {args.output}")
    else:
        print("\n[-] No hidden parameters found.")

if __name__ == "__main__":
    main()
