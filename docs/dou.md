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

## Órgãos por Radar: o que é oficial e o que é reconstruído

O documento "Distribuição de Clusters e Fontes" não está nos repositórios. O
que dele se recupera:

- **Lista de fontes aprovadas e pendentes de integração** (versão revisada de
  24/08, commit `57041b5`, `FONTES_PENDENTES_INTEGRACAO`): no Regulatório,
  "CADE – DOU (Seções 1 e 3)", "MEC – DOU (Seções 1 e 3)" e "MDIC – DOU
  (Seção 1)". É a única lista de órgãos do DOU que existe por escrito.
- **Templates oficiais do Marketing**: os nove têm seção do DOU. Regulatório:
  "Diário Oficial da União (Seções 1 e 3)". Tributário e Societário:
  "Diário Oficial da União". Os outros seis, inclusive o **Trabalhista**:
  "Diário Oficial da União (Seção 1)".
- **Matriz do Filtro 1** (`MAPA`), que veio do documento: diz que órgãos cada
  Radar acompanha pelas fontes próprias. Ela liga, por exemplo, a SENACON à
  Solução de Conflitos, o MMA ao Ambiental e o INPI e a ANPD à Propriedade
  Intelectual.

Para os outros sete Radares não há lista de órgãos por escrito. A tabela
abaixo reconstrói essas listas e diz de onde vem cada linha: **documento**
(lista de 24/08), **descrição** (o órgão é citado na descrição oficial ou nas
palavras-chave do Radar no `prompt.md`), **matriz** (o Filtro 1 já liga a
fonte do órgão ao Radar) ou **proposta** (escolha minha, sem outra base). A
medição usa as regras atuais em 8 dias úteis (22 a 25/09 e 29/09 a 02/10).

| Radar | Seção | Órgão (regra) | Origem | Atos/dia |
|---|---|---|---|---|
| Regulatório | 1 | CADE | documento | 2,6 |
| Regulatório | 3 | CADE | documento | 1,1 |
| Regulatório | 1 | MEC, sem universidades, institutos e hospitais federais | documento (o recorte é proposta) | 11,1 |
| Regulatório | 3 | MEC, só "Mais Médicos" | documento | 0 (ver decisão 2) |
| Regulatório | 1 | MDIC (inclui SUFRAMA, INMETRO, INPI) | documento | 3,5 |
| Tributário | 1 | CARF | descrição | 6,5 |
| Tributário | 1 | CONFAZ | proposta (ICMS na descrição) | 1,6 |
| Tributário | 1 | Fazenda / Gabinete do Ministro (portarias, INs, resoluções) | proposta | 0,2 |
| Tributário | 1 | PGFN; Comitê Gestor do IBS | proposta | 0 (nome não apareceu) |
| Societário | 1 | CADE | descrição | 2,6 |
| Societário | 1 | CVM | descrição | 1,4 |
| Societário | 1 | CRSFN | descrição | 0,1 |
| Societário | 1 | DREI | proposta | 0 (nome não apareceu) |
| Mercado de Capitais | 1 | CVM | descrição + matriz | 1,4 |
| Mercado de Capitais | 1 | CRSFN | proposta | 0,1 |
| Mercado de Capitais | 1 | SUSEP (só normas) | matriz | 0 |
| Mercado de Capitais | 1 | PREVIC (só normas) | proposta | 0 |
| Imobiliário | 1 | INCRA | proposta | 2,6 |
| Imobiliário | 1 | Cidades, Transportes, Portos e Aeroportos (Gabinete do Ministro) | proposta | 1,5 |
| Imobiliário | 1 | SPU | proposta | 0,8 |
| Imobiliário | 1 | ANA (resoluções); PPI | proposta | 0 |
| Ambiental | 1 | Ministério do Meio Ambiente (inclui IBAMA, ICMBio, CONAMA, SFB) | descrição + matriz | 0,5 |
| Propriedade Intelectual | 1 | INPI; ANPD | descrição + matriz | 0,2 |
| Propriedade Intelectual | 1 | Secretaria Nacional de Direitos Digitais | proposta | 0 |
| Solução de Conflitos | 1 | SENACON | matriz | 4,1 |
| Solução de Conflitos | 1 | STF; STJ (sem o CJF) | descrição (palavras-chave) | 1,1 |
| Solução de Conflitos | 1 | CNJ (normas) | proposta | 0 |

Receita Federal e Banco Central ficam de fora porque já chegam completos pelas
fontes próprias. Atos de unidades regionais e administrativas ficam de fora
de todas as regras, menos das que têm `termos` (Mais Médicos).

## Estimativa por Radar (regras atuais, 8 dias úteis)

Na Seção 1 saíram, em média, 346 atos por dia (de 293 a 435), e na Seção 3,
2.321 (de 2.121 a 2.540). Um ato pode ir para mais de um Radar (CADE no
Societário e no Regulatório, CVM no Societário e no Mercado).

| Radar | Atos/dia: média (mín.–máx.) | Com o agrupamento proposto |
|---|---|---|
| Regulatório e Óleo e Gás | 18,4 (8–53) | 10,2 (7–14) |
| Tributário | 8,4 (1–33) | 2,4 (1–6) |
| Solução de Conflitos | 5,2 (0–32) | 1,4 (0–3) |
| Imobiliário e Infraestrutura | 4,9 (2–9) | 3,2 (2–6) |
| Societário | 4,1 (2–6) | 4,1 (2–6) |
| Mercado de Capitais | 1,5 (1–3) | 1,5 (1–3) |
| Ambiental e ESG | 0,5 (0–2) | 0,5 (0–2) |
| Propriedade Intelectual | 0,2 (0–1) | 0,2 (0–1) |
| **Atos distintos no dia** | **39 (23–61)** | **19,4 notícias (13–27)** |

Os picos vêm de lotes: 46 portarias conjuntas iguais do MEC (02/10), 32
despachos sancionadores da SENACON contra postos de combustível (22/09) e 32
pautas de julgamento do CARF (23/09). Sem agrupamento, o teto de 20 atos
abertos é atingido quase todo dia (cerca de 22 créditos/dia); com o
agrupamento, abrem-se cerca de 18 (cerca de 20 créditos/dia).

## Proposta de agrupamento (não implementada)

1. **Lote**: a partir de 4 atos do mesmo órgão e do mesmo tipo na mesma
   edição e seção, uma notícia só. Pega as pautas do CARF, os despachos da
   SENACON e as portarias do INCRA.
2. **Série**: 2 ou 3 atos com o mesmo texto-base (mesmo órgão, tipo e começo
   de texto), também uma notícia só.
3. **Nunca agrupar** os órgãos em que cada ato é um caso próprio:
   CADE (despachos, editais de atos de concentração) e STF (decisões). A
   lista é configurável.

A notícia do grupo:

- **título**: "Secretaria Nacional do Consumidor: 32 despachos na mesma
  edição", com a faixa de números quando houver ("nº 217 a 262");
- **resumo e trecho**: os do ato aberto do grupo (um crédito por grupo);
- **lista**: "Atos do grupo (32): nº 398/2026 (POSTO PLANETA SATURNO…);
  nº 402/2026 (…)", com o link de cada ato e o que o distingue dos outros
  (as palavras que não se repetem no grupo);
- **no portal**: um cartão por grupo. Retirar o cartão retira o grupo, e o
  log guarda todos os atos.

## Decisões pendentes antes do merge

1. **Órgãos dos sete Radares** sem lista por escrito: validar a tabela
   reconstruída ou mandar a parte do documento com os órgãos.
2. **Mais Médicos**: nos 8 dias, os 6 atos com "Mais Médicos" (4 na Seção 1
   e 2 na Seção 3) eram do Ministério da Saúde (SGTES), nenhum do MEC. A
   regra literal "MEC, Seção 3" não pega nada. Proposta: "Mais Médicos" na
   Seção 3 venha do MEC ou do Ministério da Saúde.
3. **Trabalhista**: o template oficial tem a seção "Diário Oficial da União
   (Seção 1)", mas a lista do documento não inclui o Trabalhista.
4. **MEC na Seção 1**: confirmar o recorte (sem atos internos de
   universidades, institutos e hospitais federais) e se FNDE, INEP e CNE
   entram.
5. **Agrupamento**: aprovar a proposta acima (limiar de 4 e a lista de
   "nunca agrupar").

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
