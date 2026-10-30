"""markdown -> HTML -> PDF via Chrome headless. Sem pandoc, sem LaTeX.
Uso: python make_pdf.py artigo-final.md saida.pdf ["Título"]"""
import os, subprocess, sys, tempfile, time
import markdown

CSS = """
@page { size: A4; margin: 22mm 18mm 20mm 18mm; }
body { font-family: Georgia, 'Times New Roman', serif; font-size: 11.5pt; line-height: 1.55;
       color: #111; max-width: 44em; margin: 0 auto; }
h1 { font-size: 26pt; line-height: 1.15; margin: 0 0 8pt; font-family: 'Segoe UI', Arial, sans-serif; }
h2 { font-size: 15pt; margin: 26pt 0 8pt; padding-top: 6pt; border-top: 1px solid #ccc;
     font-family: 'Segoe UI', Arial, sans-serif; page-break-after: avoid; }
h3 { font-size: 12.5pt; margin: 18pt 0 6pt; font-family: 'Segoe UI', Arial, sans-serif; }
p, li { text-align: left; hyphens: auto; }
strong { font-weight: 700; }
em { font-style: italic; }
blockquote { margin: 12pt 0; padding: 8pt 12pt; border-left: 3px solid #444; background: #f6f6f6; }
code { font-family: Consolas, monospace; font-size: 9.5pt; background: #f2f2f2; padding: 0 2pt; }
pre { background: #f2f2f2; padding: 8pt; overflow-wrap: break-word; white-space: pre-wrap; }
table { border-collapse: collapse; width: 100%; font-size: 9.5pt; margin: 10pt 0; }
th, td { border: 1px solid #bbb; padding: 4pt 6pt; text-align: left; vertical-align: top; }
hr { border: 0; border-top: 1px solid #999; margin: 18pt 0; }
a { color: #0b3d91; text-decoration: none; }
ul, ol { padding-left: 1.3em; }
li { margin: 3pt 0; }
@media print { h2 { break-after: avoid; } table, pre { break-inside: avoid; } }
"""


def md_to_html(md_text, title, css):
    body = markdown.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists", "nl2br"])
    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
<title>{title}</title><style>{css}</style></head><body>{body}</body></html>"""


def pdf(md_path, out_pdf, title=None):
    title = title or os.path.basename(md_path).replace(".md", "")
    md_text = open(md_path, encoding="utf-8").read()
    html = md_to_html(md_text, title, CSS)
    tmp = os.path.join(tempfile.gettempdir(), os.path.basename(out_pdf) + ".html")
    open(tmp, "w", encoding="utf-8").write(html)
    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    url = "file:///" + tmp.replace("\\", "/")
    out_abs = os.path.abspath(out_pdf)
    if os.path.exists(out_abs):
        os.remove(out_abs)
    profile = os.path.join(tempfile.gettempdir(), "chrome-pdf-profile")
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
                    f"--user-data-dir={profile}",
                    "--no-pdf-header-footer", f"--print-to-pdf={out_abs}", url],
                   check=False, capture_output=True, timeout=180)
    # o Chrome anexa a uma sessão existente e grava depois de retornar: esperar o arquivo
    for _ in range(40):
        if os.path.exists(out_abs) and os.path.getsize(out_abs) > 5000:
            break
        time.sleep(0.5)
    ok = os.path.exists(out_abs) and os.path.getsize(out_abs) > 5000
    print(f"{'ok ' if ok else 'FALHOU '}{out_pdf} "
          f"{os.path.getsize(out_abs)//1024 if os.path.exists(out_abs) else 0} KB")
    return ok


if __name__ == "__main__":
    pdf(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
