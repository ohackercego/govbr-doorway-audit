# Auditoria independente: doorways de aposta em domínios públicos brasileiros

**Data da coleta:** 30 de outubro de 2026
**Autor:** Juan Matheus Rebello Santos — o hacker cego (pesquisador independente, sem vínculo com governo ou empresa)
**Contato:** abra uma issue neste repositório

---

## O que é isto

Uma varredura de **65.590 hosts públicos brasileiros** (`gov.br`, `edu.br` e domínios de
universidades federais) atrás de páginas de aposta, cassino e "download" injetadas em
servidores do Estado.

**Resultado: 304 hosts confirmados**, em 15 estados mais o Distrito Federal, incluindo:

- 8 universidades federais/estaduais (UFRGS, UFPI, USP, UFPB, UNIFESP, UnB, UFCSPA, IFC)
- 1 instituto federal (INPA)
- 1 secretaria estadual de Saúde (SC)
- dezenas de prefeituras e câmaras municipais

A maior parte dos casos usa **cloaking por User-Agent**: o servidor entrega uma página
normal ao navegador e uma ficha falsa de loja de aplicativos — com links de aposta — ao
robô do Google.

## Por que isso importa

O **CTIR Gov** publicou o ALERTA 10/2023 e, em 8 de setembro de 2026, a **RECOMENDAÇÃO
17/2026**, descrevendo exatamente esta campanha (injeção de rotas, cloaking, persistência
em Linux). Sete semanas depois da recomendação, os servidores continuam no ar.

Parte dos casos não é só SEO: há **distribuição de APK** (`s3.cdnppp889.com/...apk`) a
partir de subdomínios municipais.

## Conteúdo do repositório

| arquivo | o que é |
|---|---|
| `artigo.md` / `artigo.pdf` | matéria completa, em primeira pessoa |
| `relatorio-tecnico.md` / `.pdf` | relatório com os 304 hosts, IPs e evidências |
| `resumo-executivo.md` / `.pdf` | uma página com números e achados |
| `dados/confirmados.csv` | host, IP, evidência e link de exemplo (separador `;`) |
| `dados/resumo-por-estado.csv` | cobertura e infecções por UF |
| `dados/confirmados.json` | mesma lista em JSON |
| `dados/brutos-2026-10-30.tar.gz` | saída bruta de todos os scanners (JSONL) |
| `scripts/` | todo o código usado, sem dependências além da stdlib |
| `METODOLOGIA.md` | como a base foi montada, limites e falsos positivos |

## Como reproduzir

```bash
python scripts/municipios_dns.py            # 5.571 municípios do IBGE × 14 padrões -> DNS
python scripts/dns_sweep.py lista.txt       # agrupa por IP (acha cluster de hospedagem)
python scripts/scan_estados.py              # varre UF por UF (retomável)
python scripts/consolidar.py                # gera relatório + CSV
```

O scanner em si:

```bash
python scripts/govbr_spamhunt.py verify  --urls urls.txt     # duas UAs na mesma URL
python scripts/govbr_spamhunt.py canary  --hosts hosts.txt    # rotas /apps/ /games/ /store/
python scripts/govbr_spamhunt.py linkscan --hosts hosts.txt   # links de spam na home
python scripts/govbr_spamhunt.py harvest --index <url>        # enumera página-índice injetada
```

## Ética e limites

- 1 a 3 requisições GET por host, sem seguir redirect, 0,35–0,9 s entre requisições,
  `User-Agent` identificável e contato no header `From`.
- Nenhum login, nenhum payload, nenhuma força bruta de caminho.
- Nenhum dado de cidadão foi acessado. Só URLs públicas e indexadas.
- O que está documentado é **execução de código no servidor** para manipular busca e
  redirecionar tráfego. Não há evidência pública de exfiltração de dados nesses episódios.
- 74% dos nomes vindos de Certificate Transparency não resolvem mais em DNS: o
  denominador honesto é "infectados / hosts que responderam".
- O total é uma **foto de 30/10/2026**, não um censo. Subestima.

## Notificação

Os órgãos citados não foram contatados antes da publicação.
CTIR Gov: ctir@ctir.gov.br · CERT.br: cert@cert.br

## Licença

MIT para o código. Os textos são de uso livre com atribuição.
