#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
govbr_spamhunt.py — caçador de páginas de spam/bet injetadas em domínios *.gov.br
Autor: Café com Cyber  |  Licença: MIT  |  Requisitos: Python 3.9+ (só stdlib)

O que ele faz (somente leitura, sem exploração):
  1) canary  — baixa um arquivo estático público (/css/apps-<hash>.css) que a família
               de malware usada nessa campanha deixa no servidor. 200 = host comprometido.
  2) verify  — acessa uma URL duas vezes (UA de navegador e UA de Googlebot) e compara
               status, tamanho, título e conteúdo para detectar cloaking / redirect 302.
  3) host    — canary + enumeração passiva (Wayback/CDX) + verificação das URLs suspeitas.
  4) dorks   — imprime consultas prontas para rodar no Google/Bing e um importador de URLs.

Uso:
  python govbr_spamhunt.py dorks
  python govbr_spamhunt.py canary --hosts hosts.txt --out canary.json
  python govbr_spamhunt.py verify --urls urls.txt  --out findings.jsonl
  python govbr_spamhunt.py host   --host www.exemplo.mg.gov.br --out-dir dados/
  python govbr_spamhunt.py report --in findings.jsonl --out relatorio.md

Ética: 1 requisição por URL, 1,2 s entre requisições, User-Agent identificável.
Não faz força bruta de caminhos, não envia payload, não tenta login. Se o alvo não é seu,
avise o CTIR Gov (ctir@ctir.gov.br) e o CERT.br (cert@cert.br) antes de publicar.
"""

import argparse
import concurrent.futures as cf
import json
import os
import random
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

CONTACT = "pesquisa-cafecomcyber (contato: cafecomcyber@proton.me)"
UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
UA_GOOGLEBOT = ("Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36 "
                "(compatible; Googlebot/2.1; +http://www.google.com/bot.html)")

# --- impressões digitais observadas na campanha (atualize conforme a família evoluir)
CSS_CANARIES = ["/css/apps-21c06ba0.css"]
CANARY_PATHS = ["/apps/", "/games/", "/store/"]
ICON_HOSTS = ("app-static-file.com",)
SPAM_TITLE = re.compile(r"(apps?\s+(no|on)\s+google\s+play|google\s+play)", re.I)
BET_TOKENS = ("aposta", "apostas", "bet", "betano", "blaze", "cassino", "tigrinho",
              "fortune", "giros grátis", "saque", "bônus", "depósito", "1xbet", "superbet",
              "plataforma 79h", "pgbet", "esportivas")
SPAM_PATH = re.compile(r"(/(apps?|games|store|wp-form|app\.php)/|torrent|tigrinho|aposta|"
                       r"cassino|\bbet\b|79h|\.apk$)", re.I)
BET_LINK = re.compile(r"(bet|casino|slot|aposta|tigrinho|blaze|giros|fortune|aviator|pgsoft)", re.I)
# A mesma família também serve spam internacional (tailandês, indonésio, inglês, espanhol).
def _intl_terms():
    base = [r"สล็อต", r"เว็บตรง", r"คาสิโน", r"pg\s*slot", r"jackpot", r"scommesse", r"apuestas",
            r"casino", r"free\s*spin", r"big\s*win", r"judi", r"togel", r"gacor"]
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "termos_intl.txt")
        extra = [l.strip() for l in open(p, encoding="utf-8") if l.strip() and not l.startswith("#")]
        return base + [re.escape(t) for t in extra]
    except FileNotFoundError:
        return base


INTL_SPAM = re.compile("|".join(_intl_terms()), re.I)

# --- camada HTTP mínima, sem seguir redirect, guardando Location
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE  # muitos .gov.br municipais têm cadeia quebrada


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib segue 301/302 por padrão — e isso esconde justamente o redirect que
    queremos ver (além de transformar um 301 legítimo para a Play Store em falso
    positivo de 1 MB). Aqui o 3xx volta como resposta."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(urllib.request.HTTPSHandler(context=CTX), _NoRedirect())
LOCK = threading.Lock()
LAST_REQ = [0.0]
DELAY = 1.2


def _throttle():
    with LOCK:
        wait = DELAY - (time.time() - LAST_REQ[0])
        if wait > 0:
            time.sleep(wait)
        LAST_REQ[0] = time.time()


class Resp:
    __slots__ = ("status", "headers", "body", "url", "error")

    def __init__(self, status=None, headers=None, body=b"", url="", error=None):
        self.status, self.headers, self.body, self.url, self.error = status, headers or {}, body, url, error

    @property
    def text(self):
        enc = "utf-8"
        ct = self.headers.get("content-type", "")
        m = re.search(r"charset=([\w-]+)", ct)
        if m:
            enc = m.group(1)
        try:
            return self.body.decode(enc, "replace")
        except LookupError:
            return self.body.decode("utf-8", "replace")


def fetch(url, ua=UA_BROWSER, timeout=25, retries=2):
    for attempt in range(retries + 1):
        _throttle()
        req = urllib.request.Request(url, headers={
            "User-Agent": ua, "Accept": "*/*", "Accept-Language": "pt-BR,pt;q=0.9",
            "From": CONTACT, "Connection": "close"})
        try:
            with OPENER.open(req, timeout=timeout) as r:
                return Resp(r.status, dict(r.headers), r.read(3_000_000), r.geturl())
        except urllib.error.HTTPError as e:
            try:
                body = e.read(500_000)
            except Exception:
                body = b""
            return Resp(e.code, dict(e.headers or {}), body, url)
        except Exception as e:
            if attempt == retries:
                return Resp(error=f"{type(e).__name__}: {e}", url=url)
            time.sleep(1.5 * (attempt + 1))
    return Resp(error="falha desconhecida", url=url)


def host_of(url):
    try:
        return urllib.parse.urlsplit(url if "//" in url else "//" + url).hostname or ""
    except Exception:
        return ""


def is_gov(host):
    return host.endswith(".gov.br") or host == "gov.br"


# ------------------------------------------------------------------ 1) CANARY
def canary(host, extra_paths=()):
    """Duas impressões digitais da família:
       a) /apps/ ou /games/ respondendo 200 + título falso de Google Play SÓ para o Googlebot;
       b) CSS estático /css/apps-<hash>.css servido sem cloaking (variante que reusa o hash).
       Um GET por caminho, sem seguir redirect e sem força bruta."""
    hits = []
    for path in CANARY_PATHS:
        url = f"https://{host}{path}"
        r = fetch(url, UA_GOOGLEBOT, timeout=15, retries=1)
        if r.status in (403, 429):
            return {"host": host, "canary": False, "hits": hits,
                    "note": f"bloqueado ({r.status})"}
        if r.status == 200 and len(r.body) > 20_000:
            title = (re.findall(r"<title[^>]*>(.*?)</title>", r.text, re.S) or [""])[0].strip()
            links = re.findall(r'href="(/[^"]{2,90})"', r.text)
            betting = [l for l in links if BET_LINK.search(l)]
            if (SPAM_TITLE.search(title) or "app-static-file.com" in r.text or len(betting) >= 10
                    or ".apk" in r.text or INTL_SPAM.search(title)):
                hits.append({"url": url, "status": r.status, "bytes": len(r.body), "title": title,
                             "bet_links": len(betting)})
    for path in list(CSS_CANARIES) + list(extra_paths):
        url = f"https://{host}{path}"
        r = fetch(url, timeout=15, retries=1)
        if r.status == 200 and len(r.body) > 5000 and b"font-face" in r.body[:2000]:
            hits.append({"url": url, "status": r.status, "bytes": len(r.body), "title": "css apps"})
    return {"host": host, "canary": bool(hits), "hits": hits, "note": ""}


# ------------------------------------------------------------------ 2) VERIFY
def analyse_pair(browser, bot, url):
    """Compara as duas respostas e devolve achados + IOCs."""
    out = {"url": url, "host": host_of(url), "browser": {}, "googlebot": {}, "signals": [], "iocs": {}}
    for lab, r in (("browser", browser), ("googlebot", bot)):
        d = {"status": r.status, "bytes": len(r.body),
             "location": r.headers.get("location"), "server": r.headers.get("server"),
             "error": r.error}
        if r.body:
            t = r.text
            d["title"] = (re.findall(r"<title[^>]*>(.*?)</title>", t, re.S) or [""])[0].strip()[:160]
            low = t.lower()
            d["bet_tokens"] = sorted({k for k in BET_TOKENS if k in low})
            d["icon_cdn"] = sorted(set(re.findall(r"https?://([a-z0-9.\-]*app-static-file\.com)", t)))
            d["css_apps"] = sorted(set(re.findall(r'href="(/css/apps-[0-9a-f]+\.css)"', t)))
            d["ext_hosts"] = sorted(set(re.findall(r'https?://([^/"\'?\s]+)', t)))[:25]
            d["apk"] = sorted(set(re.findall(r'https?://[^"\'\s<>]+\.apk', t)))[:5]
        out[lab] = d

    b, g = out["browser"], out["googlebot"]
    # cloaking por status / tamanho / título
    if b.get("status") and g.get("status") and b["status"] != g["status"]:
        out["signals"].append(f"cloaking_status ({b['status']} vs {g['status']})")
    if b.get("bytes") and g.get("bytes"):
        ratio = max(b["bytes"], g["bytes"]) / max(1, min(b["bytes"], g["bytes"]))
        if ratio >= 2.0 and abs(g["bytes"] - b["bytes"]) > 2000:
            out["signals"].append(f"cloaking_tamanho (x{ratio:.1f})")
    if b.get("title") and g.get("title") and b["title"] != g["title"]:
        out["signals"].append("cloaking_titulo")
    # conteúdo de spam no que o Google vê
    if g.get("title") and SPAM_TITLE.search(g["title"]):
        out["signals"].append("titulo_fake_google_play")
    if g.get("icon_cdn") or g.get("css_apps"):
        out["signals"].append("asset_da_familia")
    if len(g.get("bet_tokens") or []) >= 2:
        out["signals"].append("copy_de_apostas")
    if g.get("apk"):
        out["signals"].append("apk_distribuido")
    if g.get("title") and INTL_SPAM.search(g["title"]):
        out["signals"].append("titulo_spam_internacional")
    if INTL_SPAM.search(" ".join(g.get("ext_hosts") or []) or " "):
        out["signals"].append("links_cassino_internacional")
    # open redirect 302 para fora do gov.br
    for lab, d in (("browser", b), ("googlebot", g)):
        loc = d.get("location")
        if loc and d.get("status") in (301, 302, 303, 307, 308):
            lh = host_of(loc)
            if lh and not is_gov(lh):
                out["signals"].append(f"open_redirect_{lab}")
                out["iocs"].setdefault("redirects", set()).add(loc)
    for key in ("icon_cdn", "ext_hosts", "apk"):
        vals = set(g.get(key) or []) | set(b.get(key) or [])
        vals = {v for v in vals if v and "." in v and not is_gov(v) and "schema.org" not in v
                and "w3.org" not in v
                and not v.startswith(("www.", "play.google", "policies.google", "support.google",
                                      "myaccount.google", "myactivity.google", "store.google",
                                      "developer.android", "accounts.google", "google.com",
                                      "fonts.gstatic", "challenges.cloudflare", "tse-mm.bing"))}
        if vals:
            out["iocs"][key] = sorted(vals)[:15]

    score = len([s for s in out["signals"] if not s.startswith("cloaking_titulo")])
    out["score"] = score
    if "open_redirect_browser" in out["signals"] or "open_redirect_googlebot" in out["signals"]:
        out["verdict"] = "OPEN_REDIRECT"
    elif ("apk_distribuido" in out["signals"] and score >= 2) or "titulo_fake_google_play" in out["signals"] \
            or "asset_da_familia" in out["signals"] or score >= 3:
        out["verdict"] = "SPAM_CLOAKING"
    elif score >= 1:
        out["verdict"] = "SUSPEITO"
    else:
        out["verdict"] = "LIMPO"
    out["iocs"] = {k: sorted(v) for k, v in out["iocs"].items()}
    return out


def verify(url, tries=3):
    """Repete quando o servidor devolve 5xx para o Googlebot: essa família derruba a
    resposta sob carga e um único 503 gera falso 'suspeito'."""
    last = None
    for i in range(tries):
        b = fetch(url, UA_BROWSER)
        g = fetch(url, UA_GOOGLEBOT)
        last = analyse_pair(b, g, url)
        if not (g.status and g.status >= 500):
            break
        time.sleep(2 + 2 * i)
    return last


# ------------------------------------------------------------------ 3) HOST
def wayback_urls(host, limit=5000):
    q = ("http://web.archive.org/cdx/search/cdx?url=" + urllib.parse.quote(host) +
         "&matchType=host&output=json&collapse=urlkey&fl=original,statuscode,timestamp&limit=" + str(limit))
    r = fetch(q, timeout=90, retries=1)
    if r.status != 200:
        return []
    try:
        rows = json.loads(r.text)[1:]
    except Exception:
        return []
    return [row[0] for row in rows if len(row) > 1 and row[1] in ("200", "-")]


def hunt_host(host, max_verify=25):
    res = canary(host)
    urls = [u for u in wayback_urls(host) if SPAM_PATH.search(urllib.parse.unquote(u))]
    # também testa os caminhos clássicos da família, só os do próprio host
    urls = list(dict.fromkeys(urls))[:max_verify]
    findings = [verify(u) for u in urls]
    return {"host": host, "canary": res, "enumerated": len(urls), "findings": findings}


def harvest(index_url, limit=40, out="findings.jsonl"):
    """Abre uma página-índice injetada (ex.: /games/) como Googlebot, extrai os links
    de spam do próprio host e verifica cada um. É assim que se enumera o diretório inteiro."""
    r = fetch(index_url, UA_GOOGLEBOT, timeout=30)
    host = host_of(index_url)
    links = re.findall(r'href="([^"]+)"', r.text)
    cand, seen = [], set()
    for l in links:
        u = urllib.parse.urljoin(index_url, l)
        if host_of(u) != host or u in seen:
            continue
        path = urllib.parse.unquote(urllib.parse.urlsplit(u).path)
        if SPAM_PATH.search(path) or BET_LINK.search(path) and len(path) > 8:
            seen.add(u)
            cand.append(u)
    cand = cand[:limit]
    print(f"[*] {len(links)} links na índice, {len(cand)} candidatos a verificar")
    rows = []
    with open(out, "a", encoding="utf-8") as f:
        for u in cand:
            out_row = verify(u)
            rows.append(out_row)
            f.write(json.dumps(out_row, ensure_ascii=False) + "\n")
            print(f"  [{out_row['verdict']:14}] {u}")
    bad = sum(1 for x in rows if x["verdict"] in ("SPAM_CLOAKING", "OPEN_REDIRECT"))
    print(f"[+] {bad}/{len(rows)} confirmados como spam/redirect -> {out}")
    return rows



def az_scan(host):
    """Varredura A-Z: 1–2 GETs por host, só os caminhos canário da família.
    Retorna o resultado já com a letra inicial para agregação."""
    letter = host[0].lower()
    res = {"host": host, "letter": letter, "hits": [], "status": [], "error": None}
    for path in ("/apps/", "/games/", "/store/"):
        r = fetch(f"https://{host}{path}", UA_GOOGLEBOT, timeout=8, retries=0)
        if r.error:
            res["error"] = r.error.split(":")[0]
            break
        res["status"].append(f"{path}{r.status}")
        if r.status in (403, 429):
            res["error"] = f"bloqueado {r.status}"
            break
        if r.status == 200 and len(r.body) > 20_000:
            title = (re.findall(r"<title[^>]*>(.*?)</title>", r.text, re.S) or [""])[0].strip()[:90]
            betting = [l for l in re.findall(r'href="(/[^"]{2,90})"', r.text) if BET_LINK.search(l)]
            if SPAM_TITLE.search(title) or "app-static-file.com" in r.text or len(betting) >= 10:
                res["hits"].append({"url": f"https://{host}{path}", "status": r.status,
                                    "bytes": len(r.body), "title": title, "bet_links": len(betting)})
            break  # 200 que não casou é página real do órgão: não vale pedir mais caminhos
        if 300 <= r.status < 400:
            break  # redirect no caminho canário = comportamento legítimo (ex.: app na Play Store)
    res["infected"] = bool(res["hits"])
    return res


def az_run(hosts_path, out_path, delay=0.6, workers=4, resume=True):
    """Roda a varredura em blocos por letra, gravando incrementalmente (retomável)."""
    global DELAY
    DELAY = delay
    hosts = [h.strip().lower() for h in open(hosts_path, encoding="utf-8")
             if h.strip() and not h.startswith("#") and re.match(r"^[a-z]", h.strip().lower())]
    done = set()
    if resume and os.path.exists(out_path):
        for line in open(out_path, encoding="utf-8"):
            try:
                done.add(json.loads(line)["host"])
            except Exception:
                pass
    todo = [h for h in dict.fromkeys(hosts) if h not in done]
    print(f"[*] {len(hosts)} hosts, {len(done)} já feitos, {len(todo)} na fila", flush=True)
    by_letter = {}
    with open(out_path, "a", encoding="utf-8") as f, cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for letter in sorted({h[0] for h in todo}):
            chunk = [h for h in todo if h[0] == letter]
            found = []
            for res in ex.map(az_scan, chunk):
                f.write(json.dumps(res, ensure_ascii=False) + "\n")
                f.flush()
                if res["infected"]:
                    found.append(res)
                    print(f"  [{letter.upper()}] INFECTADO {res['host']} -> "
                          f"{res['hits'][0]['title']} ({res['hits'][0]['bytes']} B)", flush=True)
            by_letter[letter] = {"testados": len(chunk), "infectados": len(found)}
            print(f"[{letter.upper()}] {len(chunk)} testados, {len(found)} infectados — "
                  f"acumulado {sum(v['infectados'] for v in by_letter.values())}", flush=True)
    return by_letter


def az_report(path_in, out_md):
    """Consolida a varredura A-Z: cobertura por letra, infectados e falhas."""
    rows = [json.loads(l) for l in open(path_in, encoding="utf-8") if l.strip()]
    seen, uniq = set(), []
    for r in rows:
        if r["host"] not in seen:
            seen.add(r["host"])
            uniq.append(r)
    inf = [r for r in uniq if r.get("infected")]
    err = [r for r in uniq if r.get("error") and not r.get("infected")]
    letters = sorted({r["letter"] for r in uniq})
    L = [f"# Varredura A–Z em subdomínios .gov.br — {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}", "",
         f"Hosts analisados: **{len(uniq)}** | infectados: **{len(inf)}** | "
         f"sem resposta/erro: **{len(err)}**", ""]
    L += ["## Cobertura por letra", ""]
    for let in letters:
        tot = [r for r in uniq if r["letter"] == let]
        bad = [r for r in tot if r.get("infected")]
        flag = " ⚠️" if bad else ""
        L.append(f"- **{let.upper()}**: {len(tot)} testados, {len(bad)} infectados{flag}")
    L += ["", "## Infectados", ""]
    for r in sorted(inf, key=lambda x: x["host"]):
        h = r["hits"][0]
        L.append(f"- `{r['host']}` — {h['bytes']} B — `{h['title']}` — "
                 f"({', '.join(r.get('status') or [])})")
    if err:
        L += ["", "## Sem resposta (DNS/TLS/timeout) — amostra", ""]
        for r in err[:25]:
            L.append(f"- `{r['host']}` — {r['error']}")
    open(out_md, "w", encoding="utf-8").write("\n".join(L))
    print(f"[+] {len(uniq)} hosts, {len(inf)} infectados -> {out_md}")
    for r in inf:
        print("  *", r["host"], "|", r["hits"][0]["title"][:70])


def safe_join(base, link):
    """urljoin explode com href malformado tipo 'https://[facebook_entidade]'."""
    try:
        return urllib.parse.urljoin(base, link)
    except Exception:
        return ""


# Termos que o usuário busca: download, torrent, baixar jogos, cassino, bet etc.
# Carregados de termos.txt / termos_hard.txt (editáveis sem mexer no código).
def _load_terms(name, default):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    try:
        terms = [l.strip() for l in open(path, encoding="utf-8")
                 if l.strip() and not l.startswith("#")]
        return terms or default
    except FileNotFoundError:
        return default


KW_TERMS = _load_terms("termos.txt", [
    "torrent", "baixar", "download", "jogos", "apk", "bet", "aposta", "cassino",
    "slot", "79h", "tigrinho", "blaze", "fortune", "filme", "serie", "aplicativo"])
HARD_TERMS = _load_terms("termos_hard.txt", [
    "bet", "aposta", "cassino", "slot", "tigrinho", "79h", "blaze", "fortune", "giros"])

def _terms_regex(terms):
    """Termos curtos (bet, kto, pix, iso, rom) precisam de fronteira: sem isso
    'alfabetização' casa com 'bet' e a prefeitura vira falso positivo."""
    parts = []
    for t in sorted({x.strip() for x in terms if x.strip()}, key=len, reverse=True):
        esc = re.escape(t)
        if t.isascii() and len(t) <= 3:
            parts.append(r"(?<![a-z0-9])" + esc + r"(?![a-z0-9])")
        else:
            parts.append(esc)
    return re.compile("|".join(parts), re.I)


KW_PATH = _terms_regex(KW_TERMS)
HARD_BET = _terms_regex(HARD_TERMS)


def linkscan(host):
    """1 GET na home como Googlebot. Extrai âncoras, iframes, scripts e form actions —
    a família usa os quatro. Se achar spam, repete com UA de navegador para separar
    cloaking (só o robô vê) de tomada aberta (todo mundo vê)."""
    res = {"host": host, "letter": host[0], "status": None, "bytes": 0, "title": "",
           "spam_links": [], "kw_links": 0, "infected": False, "error": None,
           "modo": None, "iframe_js": [], "externos": []}
    r = fetch(f"https://{host}/", UA_GOOGLEBOT, timeout=10, retries=0)
    if r.error:
        res["error"] = r.error.split(":")[0]
        return res
    res["status"], res["bytes"] = r.status, len(r.body)
    if not r.body:
        return res
    if r.status not in (200, 404, 410):
        return res
    res["title"] = (re.findall(r"<title[^>]*>(.*?)</title>", r.text, re.S) or [""])[0].strip()[:90]

    # âncoras + iframes + scripts + form actions + meta refresh
    alvos = re.findall(r'href="([^"]+)"', r.text)
    alvos += re.findall(r'(?:src|action)="([^"]+)"', r.text)
    alvos += re.findall(r'content="\d+;\s*url=([^"]+)"', r.text, re.I)

    spam, hard, iframe_js, externos = [], 0, [], set()
    for a in alvos:
        u = safe_join(f"https://{host}/", a)
        h = host_of(u)
        if not h:
            continue
        if h != host:
            if BET_LINK.search(h) or INTL_SPAM.search(h) or KW_PATH.search(h):
                externos.add(u)
            if re.search(r"\.(js|php|asp)", u, re.I) and h not in ("www.w3.org",):
                iframe_js.append(u)
            continue
        path = urllib.parse.unquote(urllib.parse.urlsplit(u).path)
        if len(path) < 3 or not KW_PATH.search(path):
            continue
        spam.append(u)
        if HARD_BET.search(path):
            hard += 1
    spam = list(dict.fromkeys(spam))
    apk_links = [u for u in spam if re.search(r"apk", urllib.parse.urlsplit(u).path, re.I)]
    res["spam_links"] = spam[:60]
    res["kw_links"] = len(spam)
    res["hard_links"] = hard
    res["apk_links"] = len(apk_links)
    res["iframe_js"] = iframe_js[:10]
    res["externos"] = sorted(externos)[:10]
    # regra: 5+ links de palavra-chave com 2+ de aposta; 10+ de aposta; 3+ de APK
    res["infected"] = (hard >= 2 and len(spam) >= 5) or hard >= 10 or len(apk_links) >= 3
    # espelho de software ("Index of /" com crack-attack, pypoker, qbittorrent) não é spam
    if res["infected"] and res["title"].lower().startswith("index of /"):
        marcas = re.compile(r"(betano|blaze|sportingbet|pixbet|1xbet|bet365|betnacional|"
                            r"tigrinho|fortune|79h|gacor|สล็อต)", re.I)
        if not any(marcas.search(urllib.parse.unquote(u)) for u in spam):
            res["infected"] = False
            res["nota"] = "espelho de software (Index of /)"

    if res["infected"]:
        # navegador vê a mesma coisa? então não é cloaking, é tomada aberta do host
        rb = fetch(f"https://{host}/", UA_BROWSER, timeout=10, retries=0)
        if rb.status in (200, 404, 410) and rb.body:
            kw_b = 0
            for a in re.findall(r'href="([^"]+)"', rb.text) + re.findall(r'(?:src|action)="([^"]+)"', rb.text):
                u = safe_join(f"https://{host}/", a)
                if host_of(u) == host and KW_PATH.search(urllib.parse.unquote(urllib.parse.urlsplit(u).path)):
                    kw_b += 1
            res["browser_kw"] = kw_b
            res["modo"] = "aberto" if kw_b >= 3 else "cloaking"
        else:
            res["browser_kw"] = None
            res["modo"] = "cloaking"  # sem resposta ao navegador: só o robô vê
        if r.status in (404, 410) and res["modo"] == "aberto":
            res["modo"] = "tomada_404"  # página de erro abandonada virou hospedagem de spam
    return res


def linkscan_run(hosts_path, out_path, delay=0.35, workers=14, resume=True):
    global DELAY
    DELAY = delay
    hosts = [h.strip().lower() for h in open(hosts_path, encoding="utf-8")
             if h.strip() and not h.startswith("#") and re.match(r"^[a-z]", h.strip().lower())]
    done = set()
    if resume and os.path.exists(out_path):
        for line in open(out_path, encoding="utf-8"):
            try:
                done.add(json.loads(line)["host"])
            except Exception:
                pass
    todo = [h for h in dict.fromkeys(hosts) if h not in done]
    print(f"[*] {len(hosts)} hosts, {len(done)} já feitos, {len(todo)} na fila", flush=True)
    with open(out_path, "a", encoding="utf-8") as f, cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for letter in sorted({h[0] for h in todo}):
            chunk = [h for h in todo if h[0] == letter]
            found = 0
            for res in ex.map(linkscan, chunk):
                f.write(json.dumps(res, ensure_ascii=False) + "\n")
                f.flush()
                if res["infected"]:
                    found += 1
                    print(f"  [{letter.upper()}] INFECTADO {res['host']} — {res['kw_links']} links "
                          f"({res['hard_links']} de aposta) — ex: {res['spam_links'][:2]}", flush=True)
            print(f"[{letter.upper()}] {len(chunk)} testados, {found} infectados", flush=True)


DORKS = [
 'site:gov.br "Apps no Google Play"',
 'site:gov.br "Apps on Google Play"',
 'site:gov.br torrent',
 'site:gov.br "download torrent"',
 'site:gov.br "plataforma 79h"',
 'site:gov.br "tigrinho"',
 'site:gov.br "bet" "aposta"',
 'site:gov.br inurl:app.php',
 'site:gov.br inurl:/store/apps/details',
 'site:gov.br inurl:/wp-form/',
 'site:gov.br inurl:/games/',
 'site:gov.br "giros grátis"',
 'site:gov.br "cassino online"',
]


def dorks():
    print("# Rode cada linha no Google (resultados por página: 100) e salve as URLs em urls.txt\n")
    for d in DORKS:
        print("https://www.google.com/search?q=" + urllib.parse.quote(d) + "&num=100")
    print("\n# Alternativa sem Google: Bing -> https://www.bing.com/search?q=<dork>&count=50")
    print("# Importe o que encontrar:  python govbr_spamhunt.py verify --urls urls.txt")


# ------------------------------------------------------------------ 5) REPORT
def report(path_in, out_md):
    rows = [json.loads(l) for l in open(path_in, encoding="utf-8") if l.strip()]
    by = {}
    for f in rows:
        by.setdefault(f["verdict"], []).append(f)
    hosts = sorted({f["host"] for f in rows})
    lines = [f"# Achados — {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}", "",
             f"URLs analisadas: **{len(rows)}** em **{len(hosts)}** hosts.", ""]
    for v in ("SPAM_CLOAKING", "OPEN_REDIRECT", "SUSPEITO", "LIMPO"):
        items = by.get(v, [])
        if not items:
            continue
        lines += [f"## {v} ({len(items)})", ""]
        for f in items:
            g = f.get("googlebot", {})
            lines.append(f"- `{f['url']}` — {g.get('status')} / {g.get('bytes')} B — "
                         f"título: {g.get('title') or '-'} — sinais: {', '.join(f['signals']) or '-'}")
        lines.append("")
    iocs = {}
    for f in rows:
        if f["verdict"] not in ("SPAM_CLOAKING", "OPEN_REDIRECT"):
            continue
        for k, vals in (f.get("iocs") or {}).items():
            iocs.setdefault(k, set()).update(vals)
    if iocs:
        lines += ["## IOCs", ""]
        for k, vals in iocs.items():
            for v in sorted(vals)[:40]:
                lines.append(f"- {k}: `{v}`")
    open(out_md, "w", encoding="utf-8").write("\n".join(lines))
    print(f"[+] relatório: {out_md} ({len(rows)} URLs)")


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description="Caçador de spam cloaked em *.gov.br")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("canary", help="checa impressão digital do malware em uma lista de hosts")
    c.add_argument("--hosts", required=True)
    c.add_argument("--out", default="canary.json")
    c.add_argument("--workers", type=int, default=4)

    v = sub.add_parser("verify", help="verifica URLs com UA de navegador e de Googlebot")
    v.add_argument("--urls", required=True)
    v.add_argument("--out", default="findings.jsonl")

    h = sub.add_parser("host", help="canary + enumeração passiva + verificação por host")
    h.add_argument("--host", required=True)
    h.add_argument("--out-dir", default="dados")

    hv = sub.add_parser("harvest", help="enumera e verifica todos os links de spam de uma página-índice injetada")
    hv.add_argument("--index", required=True)
    hv.add_argument("--limit", type=int, default=40)
    hv.add_argument("--out", default="findings.jsonl")

    az = sub.add_parser("az", help="varredura de A a Z em lista de subdomínios (retomável)")
    az.add_argument("--hosts", required=True)
    az.add_argument("--out", default="az_resultados.jsonl")
    az.add_argument("--delay", type=float, default=0.6)
    az.add_argument("--workers", type=int, default=4)

    ar = sub.add_parser("azreport", help="consolida o resultado da varredura A-Z em markdown")
    ar.add_argument("--in", dest="inp", required=True)
    ar.add_argument("--out", default="az_relatorio.md")

    ls = sub.add_parser("linkscan", help="busca por termos (download, torrent, jogos, bet) na home via Googlebot")
    ls.add_argument("--hosts", required=True)
    ls.add_argument("--out", default="ls_resultados.jsonl")
    ls.add_argument("--delay", type=float, default=0.35)
    ls.add_argument("--workers", type=int, default=14)

    sub.add_parser("dorks", help="imprime dorks prontos")
    r = sub.add_parser("report", help="gera markdown a partir do JSONL")
    r.add_argument("--in", dest="inp", required=True)
    r.add_argument("--out", default="relatorio.md")

    a = ap.parse_args()
    if a.cmd == "dorks":
        return dorks()

    if a.cmd == "canary":
        hosts = [x.strip() for x in open(a.hosts, encoding="utf-8") if x.strip() and not x.startswith("#")]
        res = []
        with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
            for out in ex.map(canary, hosts):
                res.append(out)
                flag = "COMPROMETIDO" if out["canary"] else ("?" if out["note"] else "ok")
                print(f"[{flag:12}] {out['host']} {out['note']}")
        json.dump(res, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"[+] {sum(1 for x in res if x['canary'])}/{len(res)} com a impressão digital -> {a.out}")
        return

    if a.cmd == "verify":
        urls = [x.strip() for x in open(a.urls, encoding="utf-8") if x.strip() and not x.startswith("#")]
        with open(a.out, "w", encoding="utf-8") as f:
            for u in urls:
                out = verify(u)
                f.write(json.dumps(out, ensure_ascii=False) + "\n")
                print(f"[{out['verdict']:14}] {u} -> {out['googlebot'].get('status')} "
                      f"({out['googlebot'].get('bytes')} B) {','.join(out['signals'])}")
        return

    if a.cmd == "host":
        out = hunt_host(a.host)
        os.makedirs(a.out_dir, exist_ok=True)
        p = os.path.join(a.out_dir, f"host-{a.host.replace('.', '_')}.json")
        json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(json.dumps({"host": out["host"], "canary": out["canary"], "enumerated": out["enumerated"]},
                         ensure_ascii=False))
        for f in out["findings"]:
            print(f"  [{f['verdict']:14}] {f['url']} {','.join(f['signals'])}")
        print(f"[+] salvo em {p}")
        return

    if a.cmd == "report":
        return report(a.inp, a.out)

    if a.cmd == "harvest":
        return harvest(a.index, a.limit, a.out)

    if a.cmd == "az":
        res = az_run(a.hosts, a.out, a.delay, a.workers)
        print(json.dumps(res, ensure_ascii=False, indent=1))

    if a.cmd == "azreport":
        return az_report(a.inp, a.out)

    if a.cmd == "linkscan":
        return linkscan_run(a.hosts, a.out, a.delay, a.workers)


if __name__ == "__main__":
    main()
