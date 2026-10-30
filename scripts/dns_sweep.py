"""Resolve A de todos os hosts da base e grava host->IP (retomável).
Serve para achar clusters: um servidor de hospedagem compartilhada respondendo por
vários domínios municipais é o padrão que explica os casos de Acreúna e do Piauí."""
import json, os, socket, sys
import concurrent.futures as cf

SRC = sys.argv[1] if len(sys.argv) > 1 else "hosts_union.txt"
OUT = sys.argv[2] if len(sys.argv) > 2 else "dns_map.jsonl"

hosts = [h.strip() for h in open(SRC, encoding="utf-8") if h.strip()]
done = set()
if os.path.exists(OUT):
    for line in open(OUT, encoding="utf-8"):
        try:
            done.add(json.loads(line)["host"])
        except Exception:
            pass
todo = [h for h in dict.fromkeys(hosts) if h not in done]
print(f"[*] {len(hosts)} hosts, {len(done)} feitos, {len(todo)} na fila", flush=True)


def resolve(h):
    try:
        return {"host": h, "ip": socket.gethostbyname(h)}
    except Exception as e:
        return {"host": h, "ip": None, "error": type(e).__name__}


n = 0
with open(OUT, "a", encoding="utf-8") as f, cf.ThreadPoolExecutor(max_workers=40) as ex:
    for r in ex.map(resolve, todo):
        f.write(json.dumps(r) + "\n")
        n += 1
        if n % 500 == 0:
            f.flush()
            print(f"  {n}/{len(todo)}", flush=True)
print("[+] fim", flush=True)
