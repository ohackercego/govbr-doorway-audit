# Metodologia

**Autor:** Juan Matheus Rebello Santos — o hacker cego

Esta auditoria foi feita de fora, sem acesso a nenhum sistema interno, com requisições
HTTP públicas. O objetivo era responder uma pergunta simples: quantos endereços públicos
brasileiros ainda servem página de aposta ao robô do Google?

## 1. Como a base de hosts foi montada

Não existe lista pública completa de subdomínios `.gov.br`: o Registro `.br` não publica
o zone file e os logs de Certificate Transparency são um retrato histórico.

Três fontes:

1. **Certificate Transparency (`crt.sh`)** — consulta `%.gov.br`, extração de todos os
   nomes de certificado. Resultado: 30.766 hosts, dos quais ~70% já não resolvem em DNS.
2. **Enumeração municipal (IBGE)** — 5.571 municípios × 14 padrões de host (`apex`, `www`,
   `portal`, `prefeitura`, `cpanel`, `autodiscover`, `mail`, `webmail`, `transparencia`,
   `saude`, `educacao`, `camara`, `cm`, `semed`), com e sem hífen no nome da cidade.
   Resolução DNS: 25.823 vivos.
3. **Universidades e institutos federais** — 44 domínios de universidades + todo o
   `.edu.br`. Resultado: 16.663 hosts.

Total testado: **65.590 hosts distintos**.

## 2. Como cada host foi testado

Um GET na home com **User-Agent de Googlebot**, extraindo âncoras (`a href`), `iframe src`,
`script src`, `form action` e `meta refresh`.

Cada URL encontrada foi classificada por 130+ termos em `scripts/termos.txt` (aposta,
cassino, bet, tigrinho, fortune, slot, 79h, torrent, baixar, download, apk, marcas
conhecidas) e por termos internacionais em `scripts/termos_intl.txt` (tailandês, indonésio,
inglês, espanhol).

**Critério de confirmação:** 10+ links de aposta, ou 3+ links com `apk` no caminho
(variante de distribuição de aplicativo), ou ficha falsa de loja de aplicativos.

Quando um host passou no critério, ele foi reprocessado para separar os modos:

- `cloaking` — navegador vê outra coisa (ou 404);
- `aberto` — navegador e robô veem o mesmo spam (subdomínio tomado);
- `tomada_404` — página de erro com corpo de spam.

## 3. Como os clusters foram descobertos

Depois da varredura, resolvi o DNS de toda a base e agrupei por IP. Foi o passo que mudou
a leitura: o comprometimento não é por site, é por **servidor de hospedagem compartilhada**.

Clusters confirmados:

| IP | hosts | onde | observação |
|---|---|---|---|
| `107.190.141.98` | 216 | Piauí | 203 infectados; todos os vhosts de cPanel |
| `31.220.75.95` | 18 | Goiás | 10 de 10 vhosts de 5 prefeituras |
| `45.178.224.153` | 10 | MS | 6 municípios |
| `45.7.171.191` | 12 | SP | portais da transparência |
| `168.0.52.120` | 18 | PE/AL | 6 infectados |
| `177.70.23.182` | 8 | BA | 4 prefeituras (abaixo do limiar) |
| `200.17.53.5` | 3 | INPA | 3 de 3 |
| `200.19.215.60` | 1 | SC | Secretaria de Saúde |

## 4. Falsos positivos encontrados e corrigidos

Publicar número sem mostrar onde errei seria fazer metade do trabalho.

1. **`internetbanking.caixa.gov.br`** — `/apps/` faz 301 legítimo para a ficha real do app
   Caixa na Play Store. O cliente HTTP seguiu o redirect e baixou 1,1 MB da Google Play.
   Corrigido com handler que não segue 3xx.
2. **Cinco prefeituras** (`altolonga.pi`, `cachoeirinha.pe`, `calcado.pe`, `guarabira.pb`,
   `picui.pb`) — "alfa**bet**ização" casando com o termo `bet`. Corrigido com fronteira de
   palavra para termos curtos.
3. **`savannah.c3sl.ufpr.br`** — espelho de software com projetos `crack-attack`, `pypoker`,
   `qbittorrent`; o regex lia "crack" e "poker" como cassino. Corrigido com exclusão para
   `Index of /` sem marca de aposta.

## 5. Limites

- A base do CT é um retrato histórico: 74% dos nomes não resolvem mais.
- A enumeração municipal cobre 14 padrões de host — subdomínios com nomes não previstos
  ficam de fora.
- O Google bloqueia IP de datacenter; a descoberta por dork não foi possível.
- Quatro casos da Bahia ficaram com 4–7 links (abaixo do corte de 10) e estão listados
  como prováveis, não confirmados.
- O número é uma foto de 30/10/2026. O real é maior.

## 6. Reprodutibilidade

Tudo que foi usado está em `scripts/`. Os arquivos brutos de saída estão em
`dados/brutos-2026-10-30.tar.gz` (JSONL, um registro por host, com status, links
encontrados, evidência e erro quando houve).

Para refazer: `python scripts/consolidar.py` sobre os JSONL gera o relatório e o CSV.
