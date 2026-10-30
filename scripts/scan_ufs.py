"""Varre uma lista de UFs em sequência, gravando <uf>_ls.jsonl (retomável).
Uso: python scan_ufs.py se al pe pb rn ce ma"""
import os, subprocess, sys

for uf in sys.argv[1:]:
    src = os.path.join("municipios", f"{uf}.txt")
    out = f"{uf}_ls.jsonl"
    if not (os.path.exists(src) and os.path.getsize(src) > 0):
        print(f"[{uf.upper()}] sem lista", flush=True)
        continue
    n = sum(1 for _ in open(src, encoding="utf-8"))
    print(f"[{uf.upper()}] {n} hosts", flush=True)
    subprocess.run([sys.executable, "govbr_spamhunt.py", "linkscan",
                    "--hosts", src, "--out", out, "--delay", "0.5", "--workers", "8"])
    print(f"[{uf.upper()}] concluído", flush=True)
