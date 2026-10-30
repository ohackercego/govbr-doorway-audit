"""Enumeração cidade por cidade: para cada município do IBGE gera os hostnames
prováveis em <slug>.<uf>.gov.br e resolve DNS. Só resolução — nenhum HTTP aqui.
Saída: municipios/<UF>.txt com os hosts que existem."""
import json, os, re, socket, sys, unicodedata
import concurrent.futures as cf
import requests

UF_ORDEM = sys.argv[1:] or None
OUT = "municipios"
os.makedirs(OUT, exist_ok=True)
PREFIXOS = ["", "www.", "portal.", "prefeitura.", "cpanel.", "autodiscover.",
            "mail.", "webmail.", "transparencia.", "saude.", "educacao.",
            "camara.", "cm.", "semed."]


def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def slug_h(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


CACHE = "municipios_ibge.json"
if os.path.exists(CACHE):
    muns_raw = json.load(open(CACHE, encoding="utf-8"))
    print("[*] lista do IBGE em cache", flush=True)
else:
    muns_raw = None
    for tent in range(4):
        try:
            rr = requests.get("https://servicodados.ibge.gov.br/api/v1/localidades/municipios", timeout=120)
            muns_raw = rr.json()
            json.dump(muns_raw, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
            break
        except Exception as e:
            print("  IBGE falhou", type(e).__name__, "tentativa", tent + 1, flush=True)
            time.sleep(10 + 10 * tent)
    if not muns_raw:
        raise SystemExit("sem lista de municípios: rode de novo quando o IBGE responder")

muns = []
for m in muns_raw:
    uf = None
    try:
        uf = m["microrregiao"]["mesorregiao"]["UF"]["sigla"]
    except Exception:
        try:
            uf = m["regiao-imediata"]["regiao-intermediaria"]["UF"]["sigla"]
        except Exception:
            uf = None
    if not uf:
        continue
    muns.append((uf.lower(), m["nome"]))
print(f"[*] {len(muns)} municípios", flush=True)

por_uf = {}
for uf, nome in muns:
    por_uf.setdefault(uf, []).append(nome)

ufs = UF_ORDEM or sorted(por_uf)
cand = {}
for uf in ufs:
    lst = []
    for nome in por_uf.get(uf, []):
        for s in {slug(nome), slug_h(nome)}:
            if not s:
                continue
            base = f"{s}.{uf}.gov.br"
            lst += [p + base for p in PREFIXOS]
    cand[uf] = sorted(set(lst))
    print(f"  {uf.upper()}: {len(por_uf.get(uf,[]))} municípios, {len(cand[uf])} candidatos", flush=True)


def resolve(h):
    try:
        socket.gethostbyname(h)
        return h
    except Exception:
        return None


for uf in ufs:
    path = os.path.join(OUT, f"{uf}.txt")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        print(uf, "já existe, pulando", flush=True)
        continue
    vivos = []
    with cf.ThreadPoolExecutor(max_workers=60) as ex:
        for res in ex.map(resolve, cand[uf]):
            if res:
                vivos.append(res)
    open(path, "w", encoding="utf-8").write("\n".join(sorted(vivos)))
    print(f"{uf.upper()}: {len(vivos)} hosts vivos de {len(cand[uf])} candidatos", flush=True)

todos = set()
for f in os.listdir(OUT):
    todos |= {l.strip() for l in open(os.path.join(OUT, f), encoding="utf-8") if l.strip()}
open("hosts_municipios.txt", "w", encoding="utf-8").write("\n".join(sorted(todos)))
print("TOTAL municípios vivos:", len(todos), flush=True)
