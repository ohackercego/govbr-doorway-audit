"""Consolida todos os resultados em relatorio_final.md (snapshot; pode rodar a qualquer momento)."""
import glob, json, collections, os

CONF = {}   # host -> evidência
TESTADOS = collections.Counter()
FONTES = collections.Counter()


def carrega(f):
    try:
        return [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
    except FileNotFoundError:
        return []


for f in glob.glob("*_ls.jsonl") + ["az_resultados.jsonl", "az_resultados2.jsonl",
                                    "epicentro_ls.jsonl", "ls3_resultados.jsonl"]:
    if not os.path.exists(f):
        continue
    rows = carrega(f)
    if not rows:
        continue
    FONTES[f] = len(rows)
    for r in rows:
        TESTADOS[r["host"]] = 1
        if not r.get("infected"):
            continue
        if "hard_links" in r:
            if (r.get("hard_links") or 0) >= 10 or (r.get("apk_links") or 0) >= 3:
                CONF[r["host"]] = {"evid": f"{r['kw_links']} links ({r['hard_links']} de aposta)",
                                   "ex": r["spam_links"][:2], "fonte": f}
        else:
            h = r["hits"][0]
            CONF[r["host"]] = {"evid": f"{h['bytes']} B — {h.get('title','')[:70]}",
                               "ex": [h["url"]], "fonte": f}

ip = {}
for l in carrega("dns_map.jsonl"):
    if l.get("ip"):
        ip[l["host"]] = l["ip"]

uf = collections.Counter(h.split(".")[-3] for h in CONF)
L = [f"# Varredura .gov.br — snapshot", "",
     f"Hosts distintos testados: **{len(TESTADOS)}** | confirmados: **{len(CONF)}**", "",
     "## Confirmados por estado", ""]
for k, v in uf.most_common():
    L.append(f"- **{k.upper()}**: {v}")
L += ["", "## Hosts confirmados", "",
      "| host | IP | evidência |", "|---|---|---|"]
for h in sorted(CONF):
    L.append(f"| `{h}` | {ip.get(h,'—')} | {CONF[h]['evid']} |")
L += ["", "## Cobertura por arquivo", ""]
for f, n in sorted(FONTES.items()):
    L.append(f"- {f}: {n} hosts")
open("relatorio_final.md", "w", encoding="utf-8").write("\n".join(L))

# CSV para análise
import csv
with open("relatorio_final.csv", "w", encoding="utf-8", newline="") as fh:
    w = csv.writer(fh, delimiter=";")
    w.writerow(["host", "ip", "dominio", "evidencia", "exemplo_link"])
    for h in sorted(CONF):
        w.writerow([h, ip.get(h, ""), ".".join(h.split(".")[-2:]),
                    CONF[h]["evid"], (CONF[h]["ex"][0] if CONF[h]["ex"] else "")])

print(f"testados={len(TESTADOS)} confirmados={len(CONF)} uf={dict(uf)}")
print("-> relatorio_final.md / relatorio_final.csv")
