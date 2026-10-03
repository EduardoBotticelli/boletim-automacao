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
2. O filtro do `dou.json` dá os Radares de cada ato (ver "Regra", abaixo).
   Quem não entra em nenhum Radar fica só na contagem do log.
3. Atos repetidos viram uma notícia só (ver "Agrupamento").
4. Abre-se um ato por notícia (**1 crédito cada**), para tirar a ementa (vira
   o resumo) e o trecho do texto (vai para o e-mail). Há um teto por execução
   (`limite_atos_abertos`, hoje 20), e as normas abrem antes do expediente.
   A notícia cujo ato não abre entra do mesmo jeito, com o começo do texto
   que a leitura já traz, e o motivo fica no log. Nenhum ato que passou no
   filtro some.

Os atos do DOU não vão ao Gemini: entram no boletim com os Radares do filtro,
passam pelo Filtro 1 (as duas seções estão na matriz, derivada do
`dou.json`) e chegam ao portal como as outras fontes. A fonte é
"Diário Oficial da União | Seção 1" ou "| Seção 3". Cada uma cai na seção do
DOU do template do Radar, sem alias: no Regulatório, as duas vão para
"Diário Oficial da União (Seções 1 e 3)".

## Regra (documento "Distribuição de Clusters e Fontes")

- **Seção 1**: fonte dos nove Radares, inclusive o Trabalhista, inteira,
  sem recorte por órgão. É tratada como fonte genérica: o ato entra no Radar
  se o **título ou a ementa** tiver palavras-chave daquele Radar no
  `prompt.md`, com a regra das fontes genéricas: **dois termos ou um termo
  composto**. Um ato pode entrar em mais de um Radar. O preâmbulo de
  competência ("O DIRETOR-GERAL DA ANTT, no uso das atribuições…") não conta:
  nele, toda resolução citada e toda sigla de agência viravam "dois termos".
  A ementa é, no DOU, o que a descrição é nas outras fontes genéricas.
- **Reforço**: a lista de órgãos de cada Radar (`reforco` no `dou.json`)
  só baixa o mínimo para **um termo**; sem palavra-chave, o órgão não basta.
- **Regulatório e Óleo e Gás**: além das palavras-chave, entram sempre
  CADE (Seções 1 e 3), MEC (Seção 1, sem universidades, institutos e
  hospitais federais; com FNDE, INEP e CNE) e MDIC (Seção 1).
- **Seção 3**: só o Regulatório: CADE, e Mais Médicos do MEC ou do
  Ministério da Saúde. Nos 8 dias medidos, os atos de Mais Médicos vieram
  todos do Ministério da Saúde (SGTES).

## Agrupamento

1. **Lote**: a partir de 4 atos do mesmo órgão, do mesmo tipo e para os
   mesmos Radares na mesma edição e seção, uma notícia só (pautas do CARF,
   despachos sancionadores da SENACON, portarias do INCRA).
2. **Série**: a partir de 2 atos com o mesmo texto-base (mesmo órgão, tipo e
   começo de texto), também uma notícia só (as portarias conjuntas iguais
   do MEC).
3. **Nunca agrupar** CADE e STF: cada ato deles é um caso próprio.

A notícia do grupo tem o título "Secretaria Nacional do Consumidor: 32
despachos na mesma edição, nº 377/2026 a 443/2026"; o resumo e o trecho são
os do ato aberto ("Exemplo (nº 398/2026): …"); e, abaixo, a lista "Atos do
grupo (32): nº 398/2026 (POSTO PLANETA SATURNO…); …", com o link de cada
ato e o que o distingue dos outros. No portal, um cartão por grupo; o log e
o dossier guardam todos os atos.

**E-mail (modelo D).** Abaixo do resumo, em texto:
*"Trecho do ato (DOU, Seção 1, p. 34): …"*, com até 900 caracteres, cortado
no fim de uma frase. Não há PDF nem anexo. O resumo é a ementa; quando o ato
não tem ementa, é o começo do texto.

**Edição.** A coleta diária lê a edição do dia. No sábado e no domingo não há
edição regular, e nada é pedido ao Firecrawl. Para ensaio, `DOU_EDICAO=DD-MM-AAAA`
troca a edição. As edições extras (`dou1e` etc.) não são lidas.

**Reprocessar.** Os atos ficam no dossier guardado (`indice.json` e um `.md`
legível por seção); reprocessar não gasta crédito com o DOU.

## Estimativa por Radar (8 dias úteis: 22 a 25/09 e 29/09 a 02/10)

Na Seção 1 saíram, em média, 346 atos por dia (de 293 a 435), e na Seção 3,
2.321. Com a regra acima e o agrupamento, medidos sem gastar crédito sobre a
leitura guardada desses dias:

| Radar | Atos/dia: média (mín.–máx.) | Notícias/dia | De onde vêm, principalmente |
|---|---|---|---|
| Regulatório e Óleo e Gás | 40,0 (25–68) | 18,5 (13–24) | 18,5 atos/dia de CADE, MEC e MDIC; o resto por palavras-chave (ANM, ANTT, ANTAQ, SENACON) |
| Tributário | 8,9 (3–15) | 5,6 (3–8) | Receita Federal (2,9 notícias/dia, inclusive unidades locais), CONFAZ (1,2) |
| Imobiliário e Infraestrutura | 9,4 (6–19) | 5,5 (3–7) | INCRA (1,5), ANEEL (1,0), ANM (0,6) |
| Mercado de Capitais | 6,1 (1–13) | 3,1 (1–5) | CVM (1,4), SUSEP (0,9), Banco Central (0,5) |
| Solução de Conflitos | 6,4 (1–32) | 2,5 (1–4) | STF (0,6), ANM (0,5), SENACON (lote) |
| Societário | 2,0 (1–5) | 2,0 (1–5) | CADE (1,8) |
| Trabalhista | 1,5 (0–3) | 1,4 (0–2) | Secretaria de Inspeção do Trabalho (1,1) |
| Ambiental e ESG | 1,0 (0–2) | 1,0 (0–2) | dispersas |
| Propriedade Intelectual | 0,5 (0–2) | 0,5 (0–2) | dispersas |
| **Atos distintos no dia** | **67 (39–100)** | **35 notícias (27–41)** | |

Com as palavras-chave procuradas também no preâmbulo, seriam 137 atos e 53
notícias por dia (Regulatório com 94 atos e 31 notícias). Com 35 notícias por
dia e o teto de 20 atos abertos, cerca de 15 notícias por dia saem sem o
trecho do texto, só com o começo que a leitura do jornal traz.

## Ensaio com o Firecrawl (edição de 02/10/2026)

Etapa `ensaio_dou` do workflow, sem o pipeline:

| | Seção 1 | Seção 3 |
|---|---|---|
| Atos na edição | 415 | 2.334 |
| No filtro (regra por órgão de então) | 65 | 1 |
| Abertos | 19 | 1 |
| Créditos | 20 | 2 |

Total: 22 créditos, com a primeira regra (só por órgão). 45 atos não
abriram por serem da mesma série; 1 não abriu pelo teto.

## Custo

Com o teto de 20 atos abertos, 22 créditos por dia útil (2 leituras e 20
atos), ou cerca de 480 por mês, somados ao que a coleta já gasta. Abrir todas
as 35 notícias do dia custaria cerca de 37 créditos (perto de 800 por mês). O plano gratuito do Firecrawl tem 1.000 por mês. O teto
(`limite_atos_abertos`) é o controle direto; o log de cada execução traz o
gasto em `dou.creditos_firecrawl` e em `creditos_firecrawl_estimados.dou`.

## Log (`output/log_execucao.json`, chave `dou`)

`edicao`, `creditos_firecrawl` (no reprocessamento, 0, e o gasto original em
`creditos_firecrawl_na_coleta`), `limite_atos_abertos`, `atos_abertos`,
`atos_nao_abertos`, `nao_abertos_por_motivo`, `por_radar` (atos),
`noticias_por_radar`, `grupos` e, por seção, `atos_na_edicao`, `no_filtro`,
`abertos`, `creditos_firecrawl`,
`status` e `erro`. Seção que falha vira erro técnico da fonte; ato que não
abre traz o motivo em `dou.nao_aberto` no item.
