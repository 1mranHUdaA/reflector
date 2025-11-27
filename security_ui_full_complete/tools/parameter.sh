#!/usr/bin/env bash
# filter_wayback_params_dedupe.sh
# Usage:
#   ./filter_wayback_params_dedupe.sh domain.com
#   ./filter_wayback_params_dedupe.sh domains.txt
#
# Behavior:
#  - Runs waybackurls for each domain.
#  - Decodes URLs for inspection.
#  - Keeps only URLs that contain parameters (query string with at least one key=value).
#  - Excludes API endpoints (api subdomain or /api path) and common static file extensions.
#  - Deduplicates by (host + path + set-of-parameter-names) — keeps only the first seen URL per signature.
#  - Writes the ORIGINAL (possibly %-encoded) URL to the output file.
#
set -o errexit
set -o nounset
set -o pipefail

if [ -z "${1:-}" ]; then
    echo "Usage: $0 domain.com OR $0 domains.txt"
    exit 1
fi

input="$1"

# create a small python filter script in /tmp; ensure it is removed on exit
py_filter="/tmp/wayback_params_dedupe_filter_$$.py"
trap 'rm -f "$py_filter"' EXIT

cat > "$py_filter" <<'PY'
#!/usr/bin/env python3
import sys, urllib.parse, re

# static file extensions to ignore (checked on decoded URL)
ext_re = re.compile(
    r'\.(js|css|png|jpg|jpeg|gif|svg|woff|ico|pdf|zip|bmp|ttf|eot|otf|webp|txt)(?:[/?\s]|$)',
    re.I
)

# exclude api as subdomain (://api.) OR path /api or /api? or /api/
api_re = re.compile(r'(?:(?<=://)api\.|/api(?:/|\?|$))', re.I)

def extract_query_from_decoded(decoded):
    """
    Return tuple (netloc, path, list_of_param_names) from a decoded URL-like string.
    Handles the normal query (urlparse) and cases where ? and = are URL-encoded into the path.
    """
    try:
        p = urllib.parse.urlparse(decoded)
    except Exception:
        # if urlparse fails, operate on the raw string heuristically
        p = urllib.parse.urlparse("http://" + decoded)  # best-effort
    netloc = p.netloc or ""
    path = p.path or "/"

    query = p.query or ""
    # If query is empty but path contains encoded or literal '?', attempt to split
    if not query and '?' in p.path:
        # split at first '?'
        path_part, _, qpart = p.path.partition('?')
        path = path_part or "/"
        query = qpart

    # If query still empty but decoded string contains '?', try splitting raw decoded
    if not query and '?' in decoded:
        _, _, qpart = decoded.partition('?')
        query = qpart

    # parse query into keys
    params = []
    if query:
        # parse_qsl returns list of (k,v). Keep keys only.
        try:
            pairs = urllib.parse.parse_qsl(query, keep_blank_values=True)
            params = [k for k, _ in pairs if k != ""]
        except Exception:
            # fallback: simple heuristic to extract 'k=' patterns
            params = re.findall(r'([^&=]+)=', query)

    # Also handle cases where the query string is encoded into the path (e.g. /path%3Fid%3D1)
    # but was not split above: check path for '?' or '='
    if not params and ('?' in path and '=' in path):
        # split after '?' in path
        _, _, qpart = path.partition('?')
        try:
            pairs = urllib.parse.parse_qsl(qpart, keep_blank_values=True)
            params = [k for k, _ in pairs if k != ""]
        except Exception:
            params = re.findall(r'([^&=]+)=', qpart)

    # Normalize param names: strip and lower
    params = [p.strip().lower() for p in params if p and p.strip() != ""]
    return netloc, path, sorted(set(params))

def is_static_or_api(decoded):
    # static file extension check
    if ext_re.search(decoded):
        return True
    if api_re.search(decoded):
        return True
    return False

def main():
    seen = set()
    for raw in sys.stdin:
        url = raw.rstrip("\n")
        if not url:
            continue

        # decode for inspection only
        try:
            decoded = urllib.parse.unquote(url)
        except Exception:
            decoded = url

        # skip obvious api or static files
        if is_static_or_api(decoded):
            continue

        # extract netloc, path, param names
        netloc, path, param_names = extract_query_from_decoded(decoded)

        # require at least one parameter name (key=value)
        if not param_names:
            continue

        # signature: host + path + comma-separated sorted param names
        sig = f"{netloc}{path}?" + ",".join(param_names)

        if sig in seen:
            # already encountered same host+path+params (regardless of values) -> skip
            continue

        # first time: record and print original (encoded) URL
        seen.add(sig)
        print(url)

if __name__ == '__main__':
    main()
PY

chmod +x "$py_filter" || true

process_domain() {
    local domain="$1"
    echo "[*] Running waybackurls for $domain..."
    # Pipe waybackurls output into the python filter; warn if it returns non-zero
    if ! waybackurls "$domain" 2>/dev/null | python3 "$py_filter" >> "$temp_file"; then
        echo "[!] Warning: waybackurls|python filter returned non-zero for $domain (continuing)."
    fi
}

prepare_files_for_base() {
    local base="$1"
    temp_file="${base}_params_dedupe_temp.txt"
    output_file="${base}_params_dedupe.txt"
    rm -f "$temp_file" "$output_file" 2>/dev/null
}

if [[ -f "$input" ]]; then
    first_domain=$(head -n 1 "$input" | xargs)
    if [[ -z "$first_domain" ]]; then
        echo "[!] First domain in file is empty. Please check the file."
        exit 1
    fi
    prepare_files_for_base "$first_domain"

    while IFS= read -r domain || [ -n "$domain" ]; do
        domain=$(echo "$domain" | xargs)
        if [[ -z "$domain" || "$domain" == \#* ]]; then
            continue
        fi
        echo "[*] Processing domain: $domain"
        process_domain "$domain"
    done < "$input"
else
    domain="$input"
    prepare_files_for_base "$domain"
    process_domain "$domain"
fi

# if temp file doesn't exist or is empty, warn and exit
if [[ ! -s "$temp_file" ]]; then
    echo "[!] No parameter-based URLs found — temp file is empty or missing: $temp_file"
    rm -f "$temp_file"
    exit 0
fi

echo "[*] Sorting and scanning with httpx..."
# We already deduped by signature in python, this sort -u is extra-safety
sort -u "$temp_file" | httpx -silent -o "$output_file"

rm -f "$temp_file"
echo "[+] Temp file deleted: $temp_file"
echo "[+] Done. Parameter-based, deduplicated live URLs saved to: $output_file"

exit 0
