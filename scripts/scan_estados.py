"""Varre estado por estado, na ordem das regiões, conforme os arquivos de DNS aparecem.
Cada UF vira <uf>_ls.jsonl (retomável). Espera o arquivo existir antes de começar."""
import os, subprocess, sys, time

ORDEM = ["sp", "rj", "mg", "es",           # Sudeste
         "pr", "sc", "rs",                  # Sul
         "go", "mt", "ms", "df",            # Centro-Oeste
         "ba", "se", "al", "pe", "pb", "rn", "ce", "pi", "ma",  # Nordeste
         "am", "pa", "ac", "ro", "rr", "ap", "to"]             # Norte

MAX_ESPERA = int(sys.argv[1]) if len(sys.argv) > 1 else 90 * 60

for uf in ORDEM:
    src = os.path.join("municipios", f"{uf}.txt")
    out = f"{uf}_ls.jsonl"
    t0 = time.time()
    while not (os.path.exists(src) and os.path.getsize(src) > 0):
        if time.time() - t0 > MAX_ESPERA:
            print(f"[{uf.upper()}] sem lista de DNS, pulando", flush=True)
            break
        time.sleep(20)
    else:
        n = sum(1 for _ in open(src, encoding="utf-8"))
        print(f"[{uf.upper()}] {n} hosts — iniciando", flush=True)
        subprocess.run([sys.executable, "govbr_spamhunt.py", "linkscan",
                        "--hosts", src, "--out", out, "--delay", "0.45", "--workers", "10"])
        print(f"[{uf.upper()}] concluído", flush=True)
print("[+] todos os estados da fila processados", flush=True)
