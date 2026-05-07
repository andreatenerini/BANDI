"""Diagnostico: ispeziona la struttura del primo release ANAC OCDS."""
import json
import requests

HDR = {"User-Agent": "Mozilla/5.0"}
URL = ("https://dati.anticorruzione.it/opendata/download/dataset/ocds/"
       "filesystem/bulk/2026/03.json")

r = requests.get(URL, headers={**HDR, "Range": "bytes=0-800000"}, timeout=60)
text = r.content.decode("utf-8", errors="replace")

# Trova "releases":
start = text.find('"releases":')
idx = text.find("{", start + 11)

# Bilancia graffe (rispettando stringhe quoted)
depth = 0
end = idx
in_string = False
escape = False
i = idx
BRACE_OPEN = "{"
BRACE_CLOSE = "}"
QUOTE = '"'
BACKSLASH = "\\"
for ch in text[idx:]:
    if escape:
        escape = False
        i += 1
        continue
    if ch == BACKSLASH:
        escape = True
        i += 1
        continue
    if ch == QUOTE:
        in_string = not in_string
        i += 1
        continue
    if not in_string:
        if ch == BRACE_OPEN:
            depth += 1
        elif ch == BRACE_CLOSE:
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    i += 1

raw = text[idx:end]
print(f"Primo release: {len(raw)} bytes")
try:
    j = json.loads(raw)
    print()
    print(f"=== KEYS top-level ===")
    for k, v in j.items():
        if isinstance(v, list):
            print(f"  {k}: list[{len(v)}]")
        elif isinstance(v, dict):
            print(f"  {k}: dict ({list(v.keys())[:6]})")
        else:
            print(f"  {k}: {str(v)[:80]}")
    print()
    print(f"=== TENDER ===")
    tender = j.get("tender")
    if tender:
        print(f"  status: {tender.get('status')}")
        print(f"  tenderPeriod: {tender.get('tenderPeriod')}")
        print(f"  title (50ch): {(tender.get('title') or '')[:50]}")
    else:
        print("  (assente)")
    print()
    print(f"=== AWARDS ===")
    awards = j.get("awards") or []
    print(f"  count: {len(awards)}")
    if awards:
        a = awards[0]
        print(f"  first.status: {a.get('status')}")
        print(f"  first.suppliers count: {len(a.get('suppliers') or [])}")
        if a.get('suppliers'):
            print(f"  first.supplier: {a['suppliers'][0]}")
        print(f"  first keys: {list(a.keys())}")
        # Stampo l'award completo se vuoto suppliers
    if awards and not awards[0].get("suppliers"):
        print()
        print("=== AWARD COMPLETO ===")
        print(json.dumps(awards[0], indent=2, ensure_ascii=False)[:1500])
    print()
    print(f"=== PARTIES ===")
    parties = j.get("parties") or []
    print(f"  count: {len(parties)}")
    for prt in parties[:3]:
        roles = prt.get("roles") or prt.get("role") or []
        print(f"  - id={prt.get('id')} roles={roles}")
        print(f"    name={prt.get('name')}")
        print(f"    keys={list(prt.keys())}")
    print()
    print(f"=== TAG ===")
    print(f"  {j.get('tag')}")
    print(f"  initiationType: {j.get('initiationType')}")
except Exception as e:
    print(f"Parse error: {e}")
    print(f"Inizio raw: {raw[:500]}")
