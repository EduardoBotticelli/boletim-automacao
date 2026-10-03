# Diário Oficial da União (Seções 1 e 3)

O INLABS está fora do ar e o in.gov.br derruba a conexão vinda do runner do
GitHub. O Firecrawl, que já lê o in.gov.br nos "Destaques do D.O.U.", passou a
trazer o DOU pela leitura do jornal.

## Investigação (edição de 02/10/2026)

`https://www.in.gov.br/leiturajornal?secao=dou1&data=02-10-2026`, baixada pelo
Firecrawl com `formats=["rawHtml"]`, traz embutido um
`<script id="params" type="application/json">` com a lista de atos da edição
(`jsonArray`). Cada ato vem com título (`title`), tipo (`artType`), órgão
(`hierarchyStr` e `hierarchyList`), página, edição, data e endereço
(`urlTitle`, que forma `https://www.in.gov.br/web/dou/-/<urlTitle>`). Nenhum
ato veio sem algum desses campos. O `content` é só o começo do texto (até
~400 caracteres).

| Seção | Atos no JSON | Total da busca do in.gov.br (mesma data e seção) |
|---|---|---|
| 1 (`dou1`) | 415 | 415 |
| 3 (`dou3`) | 2.334 | 2.334 |

A página de cada ato traz o texto em `<div class="texto-dou">`, com
identificação, ementa, parágrafos e assinatura separados por classe. Os oito
atos abertos no ensaio (CADE, MEC, MDIC, Receita, CVM e CADE na Seção 3) foram
lidos sem falha. A investigação custou 14 créditos (`scripts/investigar_dou.py`,
etapa `investigar_dou`).

## Como funciona (`scripts/coleta_dou.py`)

1. Uma leitura por seção, com `max_age=0` para não receber do cache uma
   edição incompleta: **1 crédito cada**.
2. O filtro por órgão do `dou.json` dá os Radares de cada ato. Quem não casa
   com nenhuma regra fica só na contagem do log.
3. Só os atos que passaram no filtro abrem (**1 crédito cada**), para tirar a
   ementa (vira o resumo) e o trecho do texto (vai para o e-mail). Para
   controlar o gasto:
   - atos da mesma série (mesmo órgão, mesmo tipo e o mesmo começo de texto)
     abrem um só. Em 02/10, 46 portarias conjuntas iguais do MEC viraram 1
     ato aberto;
   - há um teto por execução (`limite_atos_abertos`, hoje 20), e as normas
     abrem antes do expediente;
   - o ato que não abre entra do mesmo jeito, com o começo do texto que a
     leitura já traz e o motivo no log. Nenhum ato que passou no filtro some.

Os atos do DOU não vão ao Gemini: entram no boletim com os Radares do filtro,
passam pelo Filtro 1 (as duas seções estão na matriz, derivada do
`dou.json`) e chegam ao portal como as outras fontes. A fonte é
"Diário Oficial da União | Seção 1" ou "| Seção 3". Cada uma cai na seção do
DOU do template do Radar, sem alias: no Regulatório, as duas vão para
"Diário Oficial da União (Seções 1 e 3)".

**E-mail (modelo D).** Abaixo do resumo, em texto:
*"Trecho do ato (DOU, Seção 1, p. 34): …"*, com até 900 caracteres, cortado
no fim de uma frase. Não há PDF nem anexo. O resumo é a ementa; quando o ato
não tem ementa, é o começo do texto.

**Edição.** A coleta diária lê a edição do dia. No sábado e no domingo não há
edição regular, e nada é pedido ao Firecrawl. Para ensaio, `DOU_EDICAO=DD-MM-AAAA`
troca a edição. As edições extras (`dou1e` etc.) não são lidas.

**Reprocessar.** Os atos ficam no dossier guardado (`indice.json` e um `.md`
legível por seção); reprocessar não gasta crédito com o DOU.

## Regras por Radar (`dou.json`)

| Radar | Seção 1 | Seção 3 |
|---|---|---|
| Regulatório e Óleo e Gás | CADE; MEC (sem os atos internos de universidades, institutos e hospitais federais); MDIC | CADE; MEC só com "Mais Médicos" |
| Tributário | Fazenda / Gabinete do Ministro (portarias, INs, resoluções); CONFAZ; CARF; PGFN; Comitê Gestor do IBS | — |
| Societário | CADE; CVM; DREI; CRSFN | — |
| Mercado de Capitais | CVM; CRSFN; SUSEP e PREVIC (só normas) | — |
| Imobiliário e Infraestrutura | SPU; INCRA; Cidades, Transportes e Portos e Aeroportos (Gabinete do Ministro); ANA (resoluções); PPI | — |
| Ambiental e ESG | Ministério do Meio Ambiente e Mudança do Clima (inclui IBAMA, ICMBio, CONAMA, SFB) | — |
| Propriedade Intelectual | INPI; ANPD; Secretaria Nacional de Direitos Digitais (sem classificação indicativa) | — |
| Solução de Conflitos | STF; STJ (sem o CJF); CNJ (normas); SENACON | — |

O Regulatório segue o documento "Distribuição de Clusters e Fontes". Para os
outros sete Radares, o documento indica a Seção 1, mas não traz os órgãos de
cada um. As listas acima são **uma proposta** a partir da descrição de cada
Radar no `prompt.md`, para validação. Receita Federal e Banco Central ficam de
fora porque já chegam completos pelas fontes próprias. Atos de unidades
regionais e administrativas ficam de fora de todas as regras, menos das que
têm `termos` (Mais Médicos).

## Ensaio com o Firecrawl (edição de 02/10/2026)

Etapa `ensaio_dou` do workflow, sem o pipeline:

| | Seção 1 | Seção 3 |
|---|---|---|
| Atos na edição | 415 | 2.334 |
| No filtro por órgão | 65 | 1 |
| Abertos | 19 | 1 |
| Créditos | 20 | 2 |

Total: 22 créditos. 45 atos não abriram por serem da mesma série; 1 não
abriu pelo teto. Com o ajuste posterior das regras (atos internos de
universidades fora do MEC, outorgas da ANA e portarias administrativas do
INCRA fora), a mesma edição fica com 61 atos no filtro e 16 abertos:
**18 créditos**.

## Custo

Cerca de 18 a 22 créditos por dia útil, ou 400 a 480 por mês, somados ao que
a coleta já gasta. O plano gratuito do Firecrawl tem 1.000 por mês. O teto
(`limite_atos_abertos`) é o controle direto; o log de cada execução traz o
gasto em `dou.creditos_firecrawl` e em `creditos_firecrawl_estimados.dou`.

## Log (`output/log_execucao.json`, chave `dou`)

`edicao`, `creditos_firecrawl` (no reprocessamento, 0, e o gasto original em
`creditos_firecrawl_na_coleta`), `limite_atos_abertos`, `atos_abertos`,
`atos_nao_abertos`, `nao_abertos_por_motivo`, `por_radar` e, por seção,
`atos_na_edicao`, `no_filtro_por_orgao`, `abertos`, `creditos_firecrawl`,
`status` e `erro`. Seção que falha vira erro técnico da fonte; ato que não
abre traz o motivo em `dou.nao_aberto` no item.
