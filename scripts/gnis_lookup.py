"""Lookup GNIS feature IDs for CTA cities via Wikidata SPARQL."""
import urllib.request
import json
import gzip
import urllib.parse

# Wikidata QIDs for the cities we need GNIS codes for
# Q2100064 = Niceville FL
# Q738261  = Fort Walton Beach FL
# Q2049698 = Crestview FL
# Q2018459 = Destin FL
# Q2134451 = Laurel Hill FL (city in Okaloosa County FL)
# Q2095832 = Valparaiso FL
# Q107690  = Pensacola FL
# Q80874   = Oglala SD
# Q51268   = Greenleaf WI village  (may need to verify)
# Q2115694 = Holt FL (unincorporated, may not have GNIS P590)
# Q2100100 = Eglin AFB CDP FL

items = [
    ("Q2100064", "Niceville FL"),
    ("Q738261", "Fort Walton Beach FL"),
    ("Q2049698", "Crestview FL"),
    ("Q2018459", "Destin FL"),
    ("Q2134451", "Laurel Hill FL"),
    ("Q2095832", "Valparaiso FL"),
    ("Q107690", "Pensacola FL"),
    ("Q80874", "Oglala SD"),
    ("Q51268", "Greenleaf WI"),
    ("Q2115694", "Holt FL"),
    ("Q2100100", "Eglin AFB FL"),
]

ids = " ".join(f"wd:{q}" for q, _ in items)
sparql = (
    "SELECT ?item ?itemLabel ?gnis WHERE {"
    f" VALUES ?item {{ {ids} }}"
    " ?item wdt:P590 ?gnis."
    ' SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }'
    " }"
)
params = urllib.parse.urlencode({"query": sparql, "format": "json"})
url = "https://query.wikidata.org/sparql?" + params
req = urllib.request.Request(
    url,
    headers={"User-Agent": "NEMSISbot/1.0", "Accept": "application/json"},
)
with urllib.request.urlopen(req, timeout=30) as r:
    raw = r.read()
    try:
        data = gzip.decompress(raw).decode("utf-8")
    except Exception:
        data = raw.decode("utf-8", errors="replace")

j = json.loads(data)
label_map = {q: label for q, label in items}
for row in j["results"]["bindings"]:
    qid = row["item"]["value"].split("/")[-1]
    gnis = row["gnis"]["value"]
    label = row.get("itemLabel", {}).get("value", qid)
    print(f"{label} ({qid}): GNIS={gnis}")
