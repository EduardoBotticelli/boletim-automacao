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
   (`limite_atos_abertos`, hoje 20). Quando o teto aperta, abrem primeiro
   CADE, MEC e MDIC, depois os grupos, depois o restante; em cada faixa, as
   normas antes do expediente.
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
- **Receita Federal**: só as unidades centrais, como na fonte "Receita
  Federal | Normas". Superintendências regionais, delegacias (inclusive as de
  julgamento), alfândegas e inspetorias ficam de fora antes de qualquer regra
  (`somente_unidades_centrais`).
- **Exclusões por órgão e tipo de ato** (`exclusoes`): lista configurável,
  no formato das regras de órgão (`orgao`, `unidade`, `tipos`, `termos`), com
  um `motivo` que vai para o log. **Começa vazia.** Depois de uma semana de
  uso, os atos do DOU que a curadoria retirou indicam o que entra nela
  (candidatos já vistos: portarias de rotina da SUSEP, despachos de
  distribuição da ANEEL, portarias da Força Nacional no Ambiental).

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
| Regulatório e Óleo e Gás | 39,6 (24–68) | 18,1 (12–23) | 18,5 atos/dia de CADE, MEC e MDIC; o resto por palavras-chave (ANM, ANTT, ANTAQ, SENACON) |
| Imobiliário e Infraestrutura | 9,0 (5–19) | 5,1 (3–7) | INCRA, ANEEL, ANM |
| Tributário | 4,1 (1–7) | 4,1 (1–7) | CONFAZ e unidades centrais da Receita |
| Mercado de Capitais | 6,1 (1–13) | 3,1 (1–5) | CVM, SUSEP, Banco Central |
| Solução de Conflitos | 6,4 (1–32) | 2,5 (1–4) | STF, ANM, SENACON (lote) |
| Societário | 2,0 (1–5) | 2,0 (1–5) | CADE |
| Trabalhista | 1,5 (0–3) | 1,4 (0–2) | Secretaria de Inspeção do Trabalho |
| Ambiental e ESG | 1,0 (0–2) | 1,0 (0–2) | dispersas |
| Propriedade Intelectual | 0,5 (0–2) | 0,5 (0–2) | dispersas |
| **Atos distintos no dia** | **62 (38–94)** | **33 notícias (25–39)** | |

Com o teto de 20 atos abertos e a ordem de abertura acima, abrem todos os dias
as notícias de CADE, MEC e MDIC (10,5 por dia) e as dos grupos (3,8); do
restante (19,1 notícias por dia), abrem cerca de 6, e as outras saem com o
começo do texto que a leitura do jornal traz.

Com as palavras-chave procuradas também no preâmbulo, seriam 137 atos e 53
notícias por dia (Regulatório com 94 atos e 31 notícias); sem o filtro de
unidades centrais da Receita, 67 atos e 35 notícias.

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
as 33 notícias do dia custaria cerca de 35 créditos (perto de 770 por mês). O plano gratuito do Firecrawl tem 1.000 por mês. O teto
(`limite_atos_abertos`) é o controle direto; o log de cada execução traz o
gasto em `dou.creditos_firecrawl` e em `creditos_firecrawl_estimados.dou`.

## Log (`output/log_execucao.json`)

**Créditos da execução** (`creditos_firecrawl`): `coleta` (páginas e buscas
das outras fontes), `dou` (leituras e atos abertos), `total` e, se a API do
Firecrawl informar (`get_credit_usage`, sem custo), `saldo_restante`,
`creditos_do_plano` e `periodo`; se não informar, `saldo_nao_informado` diz
por quê. No reprocessamento, tudo zero e o saldo não é consultado.

**DOU** (chave `dou`):

`edicao`, `creditos_firecrawl` (no reprocessamento, 0, e o gasto original em
`creditos_firecrawl_na_coleta`), `limite_atos_abertos`, `atos_abertos`,
`atos_nao_abertos`, `nao_abertos_por_motivo`, `por_radar` (atos),
`noticias_por_radar`, `grupos` e, por seção, `atos_na_edicao`,
`excluidos_antes_do_filtro` (por motivo), `no_filtro`,
`abertos`, `creditos_firecrawl`,
`status` e `erro`. Seção que falha vira erro técnico da fonte; ato que não
abre traz o motivo em `dou.nao_aberto` no item.
