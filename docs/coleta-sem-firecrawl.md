# Coleta dentro de 1.000 créditos por mês

Restrição fixa do projeto: plano gratuito do Firecrawl, 1.000 créditos por mês,
uma execução por dia útil (cerca de 22 por mês), ou seja, **no máximo ~45
créditos por execução**, com folga para repetir uma execução que falhe.

Este documento mostra, fonte por fonte, como coletar sem o Firecrawl e quanto
sobra de consumo. **A coleta das fontes não foi alterada**: isto é a proposta.

## Como foi verificado

Tudo pelo workflow, porque a rede daqui bloqueia o gov.br. Foram quatro rodadas
do `scripts/investigar_alternativas.py` em 30/09, cerca de 500 requisições no
total e **nenhum crédito do Firecrawl**:

- identificação no User-Agent (`BoletimRadarBot/1.0`, coleta de publicações
  oficiais, baixa frequência);
- `robots.txt` lido em cada host e respeitado; onde ele não respondeu, o host
  foi tratado como proibido;
- 3 segundos entre requisições ao mesmo host;
- nenhuma tentativa de contornar bloqueio: resposta 401, 403 ou conexão
  derrubada foi registrada e deixada como está.

Para cada fonte foram testados: download direto, feed RSS/Atom, API pública e
busca por data no próprio site. O resultado bruto está nos commits
"Registra a investigação de coleta sem Firecrawl" desta branch, em
`output/alternativas.json` (rodadas 1 e 2) e `output/alternativas_sonda.json`
(sondagens das páginas montadas por JavaScript, da ANP e da Receita).

### O que cada caminho deu, em resumo

| Caminho | Resultado |
|---|---|
| Download direto | funciona em 20 fontes, com título, data, link e descrição no HTML |
| RSS/Atom | quase nada: 404 no gov.br; o da CVM está parado em pastas de anos antigos; CGU e MMA só têm o feed do site inteiro |
| API REST do Plone (gov.br clássico) | fechada: 401 para acesso anônimo |
| API do Volto (ANATEL, ANVISA, ANPD, SUSEP) | **aberta**, é a que o próprio navegador chama: 30 notícias com data e descrição |
| API de normativos do Banco Central | **aberta**, é a que a página de busca de normas usa |
| API do WordPress (Kollemata / Sinoreg-ES) | aberta |
| Busca por data do próprio site (`@@search` do Plone) | não devolve resultados no gov.br |

### Comparação com a execução real de 29/09

No único dia que as duas janelas compartilham (29/09, publicações até 16h59 ou
sem hora), o método sem Firecrawl **nunca trouxe menos** que a execução real e
trouxe mais em várias fontes:

| Fonte | Execução real | Sem Firecrawl |
|---|---|---|
| Banco Central | 0 | **6** normativos |
| SUSEP | 0 | **4** (três consultas públicas e uma lei) |
| ANEEL | 1 | **3** |
| ANVISA | 3 | **4** |
| ANP \| Notícias | 2 | **3** |
| B3 | 2 | **3** ofícios |
| Ministério da Fazenda | 1 | **2** |
| ANM, EPE, CCEE | 0, 0, 1 | **1, 1, 2** |
| CVM, INPI, ANTAQ, ANTT | iguais | iguais |

A diferença vem de dois lugares: o corte de 30.000 caracteres, que não existe
na coleta direta, e a extração pelo Gemini, que no dia 29 caiu para o modelo
mais fraco.

**A exceção que importa:** 2 dos 3 itens reais da Agricultura em 28/09 e uma
página da CVM não estão na listagem — vieram da busca complementar. Algumas
listagens do gov.br são seleções, não o total publicado. Por isso a busca fica
em alguns escopos.

## Tabela por fonte

Créditos por execução: hoje = última execução (coleta 1 crédito, busca com 30
resultados 6 créditos). Proposta: busca com 10 resultados, 2 créditos.

| Fonte | Método proposto | Créditos hoje → proposta | Título / data / link / descrição sem Firecrawl | Risco de perder publicação, comparado a hoje |
|---|---|---|---|---|
| Planalto \| Resenha Diária | Firecrawl (o servidor derruba a conexão do runner, em HTTP e HTTPS) | 1 → **1** | — (continua como hoje) | igual |
| Destaques do D.O.U. | Firecrawl (in.gov.br derruba a conexão) | 1 → **1** | — | igual |
| ONS \| Notícias | Firecrawl (a página é montada por JavaScript; a API por trás exige token) | 1 → **1** | — | igual |
| Banco Central \| Normas | API de normativos do BC | 1 → **0** | ✓ ✓ ✓ ✓ (13 de 13) | **menor** (6 contra 0 em 29/09) |
| ANATEL \| Notícias | API do Volto | 7 → **0** | ✓ ✓ ✓ ✓ (30 de 30) | **menor**: hoje a listagem chega sem data |
| ANVISA \| Notícias | API do Volto | 1 → **0** | ✓ ✓ ✓ ✓ (30 de 30) | **menor** (4 contra 3) |
| ANPD \| Notícias | API do Volto | 1 → **0** | ✓ ✓ ✓ ✓ (30 de 30) | menor |
| SUSEP \| Notícias | API do Volto | 1 → **0** | ✓ ✓ ✓ ✓ (30 de 30) | **menor** (4 contra 0) |
| Receita Federal \| Normas | download direto, leitor da tabela de resultados | 7 → **0** | ✓ ✓ ✓ ✓ (tipo, número, órgão, publicação, ementa) | **menor**: hoje não produz nada — os resultados vêm depois de 80 mil caracteres de formulário, e o corte de 30 mil os descartava, inclusive via Firecrawl |
| B3 \| Ofícios e Comunicados | download direto (data no formato dd/mm/aa) | 1 → **0** | ✓ ✓ ✓ (PDF) ✓ | menor (3 contra 2) |
| Ministério da Fazenda | download direto + busca | 7 → **2** | ✓ ✓ ✓ ✓ (30 de 30) | menor |
| CVM \| Notícias | download direto + busca | 7 → **2** | ✓ ✓ ✓ ✓ (30 de 30) | igual: a busca fica porque achou página fora da listagem |
| ANP \| Notícias | download direto + **uma** busca para as quatro da ANP | 7 → **2** | ✓ ✓ ✓ parcial (19 de 31) | menor (3 contra 2) |
| ANP \| Consultas e Audiências | página do ano corrente (`.../2026`) | 7 → **0** | ✓ ✓ ✓ ✓ (20 de 21) | menor: hoje a página chega sem as abas, que carregam por JavaScript |
| ANP \| Consultas Prévias | página do ano corrente | 7 → **0** | ✓ ✓ ✓ ✓ (uma só em 2026) | menor, idem |
| ANP \| Pautas e Atas | página do ano corrente | 7 → **0** | ✓ ✓ ✓ parcial (8 de 13) | menor, idem |
| MME \| Notícias | download direto + busca (vale também para o CNPE) | 7 → **2** | ✓ ✓ ✓ ✓ | igual |
| CNPE \| Comunicações | download direto | 7 → **0** | ✓ ✓ (última modificação) ✓ ✓ | igual |
| ANEEL | download direto | 7 → **0** | ✓ ✓ ✓ ✓ (31 de 32) | **menor** (3 contra 1); a busca achou 0 na última execução |
| Ministério da Agricultura | download direto + busca | 7 → **2** | ✓ ✓ ✓ parcial (20 de 30) | igual: a busca fica, porque a listagem é seleção |
| INPI | download direto | 7 → **0** | ✓ ✓ ✓ pouca (3 de 27) | igual (2 contra 2) |
| SENACON | download direto + busca | 7 → **2** | ✓ ✓ ✓ ✓ | igual |
| ANM | download direto + busca | 7 → **2** | ✓ ✓ ✓ ✓ | menor |
| EPE | download direto | 1 → **0** | ✓ ✓ ✓ ✓ | menor (1 contra 0) |
| ANTAQ | download direto | 7 → **0** | ✓ ✓ ✓ ✓ | igual |
| ANTT | download direto + busca | 7 → **2** | ✓ ✓ ✓ ✓ | igual |
| CCEE | download direto (a própria busca por data da CCEE) + busca | 7 → **2** | ✓ ✓ ✓ ✓ | menor (2 contra 1) |
| Kollemata \| Decretos | download direto + API do WordPress no lugar da busca | 7 → **0** | ✓ ✓ ✓ ✓ | igual: a API traz as mesmas postagens do Sinoreg-ES que a busca trazia |
| COAF \| Notícias | **suspensa** (conteúdo restrito) | 7 → **0** | — | — |
| MME \| Consultas Públicas | **suspensa** (página montada por JavaScript, sem listagem) | 7 → **0** | — | — |
| **Total por execução** | | **156 → 21** | | |

A partir de 26/10, com o fim do defeso, voltam CGU, Secretaria de Prêmios e
Apostas e Meio Ambiente. A de Prêmios e Apostas já funciona por download direto
(10 de 10 com data). CGU e MMA hoje mostram "Conteúdo Restrito" e só dá para
testar depois do defeso; no pior caso somam 2 a 6 créditos.

## Consumo

| | Por execução | Por mês (22 execuções) |
|---|---|---|
| Hoje | 156 | 3.432 |
| Com os itens 1, 2 e 3 já implementados | 126 | 2.772 |
| **Proposta** | **21** | **462** |
| Proposta + reserva para queda de método (até 5 fontes/dia no Firecrawl) | 26 | 572 |
| Proposta + reserva depois de 26/10 (CGU e MMA ainda a testar) | 26 a 32 | 572 a 704 |

Sobra entre 300 e 540 créditos por mês para repetir execuções e para testes.

**Os 455 créditos até 26/10.** São 16 dias úteis de 01/10 a 23/10. Com o
pipeline atual (126 por execução), eles acabam na 4ª execução. Com a proposta
(21 a 26), cobrem as 16. Se precisar rodar antes da coleta nova ficar pronta,
baixar a busca para 10 resultados é uma linha e leva a execução a 62 créditos.

## Regras que valem para todas as fontes

1. **Queda para o Firecrawl, registrada.** Se o método gratuito falhar (erro de
   rede, HTTP de erro, página que mudou e passou a vir sem publicações), a fonte
   é coletada pelo Firecrawl naquele dia e o log diz por quê. É a reserva de 5
   créditos da tabela.
2. **Zero suspeito é falha.** Fonte que costuma trazer publicações e de repente
   traz zero, com HTTP 200, conta como leitor quebrado: vai para o Firecrawl e
   gera aviso no workflow.
3. **Nada é descartado sem registro.** A página inteira fica no dossier
   guardado; o que sai da janela por data fica anotado.
4. **Respeito ao site**: a mesma identificação, `robots.txt` e intervalo usados
   na investigação.

## Efeito colateral no Gemini

Com título, data, link e descrição já separados, o dossier deixa de levar a
página inteira dessas fontes: vai só o que cai na janela. A estimativa é sair
de ~690 mil para ~100 mil caracteres por execução, de 277 mil para cerca de 55
mil tokens de entrada. Isso também afasta o 429.

## Correções a registros anteriores

- **Receita Federal**: o diagnóstico dizia que a URL "é um formulário de
  consulta". É, mas os resultados estão no mesmo HTML, depois do formulário. O
  corte de 30 mil caracteres os descartava, inclusive na coleta pelo Firecrawl.
- **Kollemata**: a conclusão "não publicou" vale para a página de decretos, que
  é estática. As postagens novas do Sinoreg-ES (5 em 29/09) só chegavam pela
  busca complementar; a API do WordPress traz as mesmas, de graça.
- **COAF e MME Consultas Públicas ainda estão ativas no `fontes.json`.** A
  tabela já as conta como suspensas; a suspensão entra junto com a mudança de
  coleta, depois do seu ok.
- **Passo "Testar DOU" do workflow**: roda por padrão em toda coleta, gasta 1
  crédito e uma chamada ao Gemini com 60 mil caracteres, sempre para a data
  fixa de 24/08. Sugiro desligar por padrão (22 créditos por mês).
