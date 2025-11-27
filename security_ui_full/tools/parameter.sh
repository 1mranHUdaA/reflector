#!/usr/bin/env bash
# filter_wayback_params_dedupe.sh
# (user-provided script)
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
    try:
        p = urllib.parse.urlparse(decoded)
    except Exception:
        p = urllib.parse.urlparse("http://" + decoded)
    netloc = p.netloc or ""
    path = p.path or "/"

    query = p.query or ""
    if not query and '?' in p.path:
        path_part, _, qpart = p.path.partition('?')
        path = path_part or "/"
        query = qpart

    if not query and '?' in decoded:
        _, _, qpart = decoded.partition('?')
        query = qpart

    params = []
    if query:
        try:
            pairs = urllib.parse.parse_qsl(query, keep_blank_values=True)
            params = [k for k, _ in pairs if k != ""]
        except Exception:
            params = re.findall(r'([^&=]+)=', query)

    if not params and ('?' in path and '=' in path):
        _, _, qpart = path.partition('?')
        try:
            pairs = urllib.parse.parse_qsl(qpart, keep_blank_values=True)
            params = [k for k, _ in pairs if k != ""]
        except Exception:
            params = re.findall(r'([^&=]+)=', qpart)

    params = [p.strip().lower() for p in params if p and p.strip() != ""]
    return netloc, path, sorted(set(params))

def is_static_or_api(decoded):
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

        try:
            decoded = urllib.parse.unquote(url)
        except Exception:
            decoded = url

        if is_static_or_api(decoded):
            continue

        netloc, path, param_names = extract_query_from_decoded(decoded)

        if not param_names:
            continue

        sig = f"{netloc}{path}?" + ",".join(param_names)

        if sig in seen:
            continue

        seen.add(sig)
        print(url)

if __name__ == '__main__':
    main()
PY

chmod +x "$py_filter" || true

process_domain() {
    local domain="$1"
    echo "[*] Running waybackurls for $domain..."
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

if [[ ! -s "$temp_file" ]]; then
    echo "[!] No parameter-based URLs found — temp file is empty or missing: $temp_file"
    rm -f "$temp_file"
    exit 0
fi

echo "[*] Sorting and scanning with httpx..."
sort -u "$temp_file" | httpx -silent -o "$output_file"

rm -f "$temp_file"
echo "[+] Temp file deleted: $temp_file"
echo "[+] Done. Parameter-based, deduplicated live URLs saved to: $output_file"

exit 0
