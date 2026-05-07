"""Statistiche su un campione di 200 release ANAC del file 2026/03 per capire
la distribuzione dei tag, status, e dove sono effettivamente i suppliers."""
import requests
import ijson
from collections import Counter

URL = ("https://dati.anticorruzione.it/opendata/download/dataset/ocds/"
       "filesystem/bulk/2026/03.json")

# Scarica il file in streaming, ferma a 200 release
r = requests.get(URL, stream=True, timeout=60,
                 headers={"User-Agent": "Mozilla/5.0"})

tags = Counter()
tender_status = Counter()
award_status = Counter()
supplier_in_award = 0
parties_roles = Counter()
parties_with_supplier_role = 0
n_releases = 0
sample_release_with_supplier = None

# ijson lavora su un fileobj, posso wrappare lo stream
class StreamReader:
    def __init__(self, response):
        self._iter = response.iter_content(chunk_size=64 * 1024)
        self._buffer = b""
    def read(self, n=-1):
        while not self._buffer:
            try:
                self._buffer = next(self._iter)
            except StopIteration:
                return b""
        if n == -1:
            data, self._buffer = self._buffer, b""
            return data
        data = self._buffer[:n]
        self._buffer = self._buffer[n:]
        return data

reader = StreamReader(r)
for release in ijson.items(reader, "releases.item"):
    n_releases += 1
    tag = release.get("tag")
    if isinstance(tag, list):
        tags[tuple(sorted(tag))] += 1
    elif tag:
        tags[(tag,)] += 1

    tender = release.get("tender") or {}
    tender_status[str(tender.get("status"))] += 1

    awards = release.get("awards") or []
    for a in awards:
        award_status[str(a.get("status"))] += 1
        if a.get("suppliers"):
            supplier_in_award += 1

    parties = release.get("parties") or []
    has_supplier_role = False
    for p in parties:
        roles = p.get("roles") or []
        if isinstance(roles, list):
            for role in roles:
                parties_roles[role] += 1
                if role in ("supplier", "tenderer", "winner"):
                    has_supplier_role = True
                    if not sample_release_with_supplier:
                        sample_release_with_supplier = {
                            "release_id": release.get("id"),
                            "party_role": role,
                            "party_name": p.get("name"),
                            "party_id": p.get("id"),
                        }
    if has_supplier_role:
        parties_with_supplier_role += 1

    if n_releases >= 200:
        break

print(f"=== STATS su {n_releases} release ===")
print()
print("TAG combinations:")
for k, v in tags.most_common(10):
    print(f"  {k}: {v}")
print()
print("TENDER STATUS:")
for k, v in tender_status.most_common():
    print(f"  {k!r}: {v}")
print()
print("AWARD STATUS:")
for k, v in award_status.most_common():
    print(f"  {k!r}: {v}")
print()
print(f"Awards con suppliers nel campo 'suppliers': {supplier_in_award}")
print(f"Release con almeno 1 party con role supplier/tenderer/winner: "
      f"{parties_with_supplier_role}")
print()
print("PARTIES ROLES (tutti):")
for k, v in parties_roles.most_common(15):
    print(f"  {k}: {v}")
print()
if sample_release_with_supplier:
    print(f"Esempio party-supplier: {sample_release_with_supplier}")
