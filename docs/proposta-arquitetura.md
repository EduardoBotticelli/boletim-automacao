# Proposta de arquitetura para extrair o máximo dentro das cotas

Escrita a partir dos artefatos já commitados das execuções de 21, 22, 23 e 29
de setembro. **Nenhuma execução nova foi feita**, para preservar os créditos do
Firecrawl. Nada no pipeline foi alterado.

Onde diz "medido", veio do `log_execucao.json` daquela execução. Onde diz
"estimativa", é estimativa minha e está marcada como tal.

---

## Antes de propor: uma correção no diagnóstico anterior

O documento `diagnostico-cobertura.md` afirma, sobre a última execução, que
"o `429 RESOURCE_EXHAUSTED` não sumiu". **Isso está errado.** Conferindo
tentativa a tentativa:

| Execução | Erros 429 | Erros 503 | Modelo que venceu |
|---|---|---|---|
| 22/09 | 0 | 0 | `gemini-3.7-flash` |
| 23/09 | 3 | 3 | `3.5-flash-lite` |
| 29/09 (antes) | 3 | 4 | `3.5-flash-lite` |
| **29/09 (depois)** | **0** | **27** | 4 lotes em `3.5-flash-lite`, 1 em `3.6-flash` |

**Os lotes e o intervalo de 20 segundos resolveram a cota.** O que sobrou é
outro problema, com outra causa e outro remédio.

---

## O problema real de hoje: 503, não cota

Os 27 erros da última execução são todos:

```
503 UNAVAILABLE — This model is currently experiencing high demand.
Spikes in demand are usually temporary.
```

Isso é sobrecarga do lado do Google. Não tem relação com quanto texto mandamos,
nem com a camada gratuita. **Mandar menos texto não corrige nada disso.**

E a cascata reage a ele da pior maneira possível. Hoje são 2 tentativas por
modelo com 10 segundos entre elas, cinco modelos: a cascata inteira se esgota
em cerca de **100 segundos**. Um pico de demanda dura minutos. Ou seja, diante
de algo temporário por definição, o código corre até o modelo mais fraco e fica
lá.

A prova está no lote 4: ele venceu no `gemini-3.6-flash` enquanto os outros
quatro caíram no `3.5-flash-lite`. Não foi cota — foi sorte de momento.

**Consequência:** a maior perda de qualidade de extração hoje vem de uma
política de repetição errada, e custa zero para corrigir.

---

## A cota do Gemini, quando aparece, é de tokens de entrada

Nas execuções de 23/09 e 29/09 (antes), o 429 nomeia a métrica:

```
Quota exceeded for metric:
generativelanguage.googleapis.com/generate_content_free_tier_input_to…
```

Duas coisas, sem tocar na chave: **a chave está em camada gratuita**
(`free_tier`) e **o limite é de tokens de entrada**, não de requisições. A
mensagem é cortada em 400 caracteres pelo `erro_resumo`, então **não dá para
saber se a janela é por minuto ou por dia** — guardar a mensagem inteira custa
uma linha e é a primeira coisa a fazer.

O volume de hoje, medido na última execução:

| | Medido |
|---|---|
| Dossier | 687.556 caracteres |
| `prompt.md` repetido nos 5 lotes | 144.465 caracteres |
| **Entrada total** | **832.021 caracteres ≈ 277 mil tokens** |
| Saída | 33.560 caracteres ≈ 11 mil tokens |
| Saída por publicação | **1.082 caracteres** |

Reduzir isso é **prevenção**, não cura. Vale fazer — o 429 volta assim que o
volume crescer —, mas não é o que está travando hoje.

---

## Três desperdícios medidos na coleta

### 1. Metade das fontes bate no teto de caracteres

**16 das 30 fontes** fecharam exatamente em 30.000 caracteres na última
execução. Estamos ao mesmo tempo mandando texto demais ao Gemini e cortando
conteúdo na origem.

### 2. Buscas idênticas, pagas quatro vezes

O escopo da busca é derivado da URL, e mantém dois níveis de caminho em
`gov.br`. As quatro fontes da ANP compartilham `www.gov.br/anp/pt-br`. O log
mostra o resultado literalmente idêntico:

| Fonte | Achadas | Caracteres do bloco |
|---|---|---|
| ANP \| Notícias | 30 | 8.089 |
| ANP \| Consultas e Audiências | 30 | 8.089 |
| ANP \| Consultas Prévias | 30 | 8.089 |
| ANP \| Pautas e Atas | 30 | 8.089 |

MME \| Notícias e CNPE \| Comunicações idem, 5 achadas e 1.097 caracteres cada.

São **4 buscas pagas em duplicidade por execução** (24 créditos) e **25.364
caracteres de texto duplicado** dentro do dossier que mandamos ao Gemini.

### 3. A busca dispara pelo tamanho da página, não pela utilidade

A regra de hoje é: buscar se a página tem menos de 5.000 ou mais de 30.000
caracteres, ou se é de um tipo específico. Quem fica no meio não busca. Na
última execução, **10 fontes não tiveram busca** — entre elas ANPD (28.984),
SUSEP (26.088), ANVISA (29.874), Planalto (28.792), B3, ONS, EPE e Banco
Central.

O critério é o tamanho do texto, mas o que decide se a busca é necessária é
**se a listagem expõe data de publicação**. Onde não expõe, só a busca
(`after:`/`before:`) sabe o que é da janela. ANATEL e Receita Federal foram
medidas assim na Etapa 2: **0 publicações com data em 30 e 31 listadas**. Para
as outras não temos essa medição — a conferência só rodou nas fontes que
produziam zero.

---

## A proposta

Em ordem de retorno sobre esforço. As três primeiras não gastam Firecrawl
nenhum.

### 1. Repetição certa para cada erro *(fazer primeiro)*

Separar os dois casos, que hoje são tratados igual:

- **503** → esperar e repetir **no mesmo modelo**, com espera crescente
  (30 s, 60 s, 120 s). Só descer de modelo depois que o topo falhar por vários
  minutos, não por 100 segundos.
- **429** → aí sim descer, porque insistir no mesmo modelo não adianta.

E registrar no boletim qual modelo foi usado por lote, para a queda nunca
passar despercebida.

| | |
|---|---|
| Ganho de cobertura | **o maior da lista.** 21/09 extraiu 47 publicações com o `3.7-flash`; 29/09 extraiu 31 com o `3.5-flash-lite` |
| Firecrawl | zero |
| Gemini | zero tokens a mais; alguns minutos a mais de execução |
| Risco de perder notícia | nenhum: só muda quando desistir |
| Manutenção | baixa: é uma função de repetição |

### 2. Guardar o dossier coletado

Gravar o markdown de cada fonte em `output/dossier/`. Sozinho não melhora
nada, mas destrava três coisas: reprocessar sem gastar Firecrawl quando o
Gemini falhar; **medir** o efeito do recorte de janela antes de confiar nele; e
investigar fonte por fonte sem ir à rede.

| | |
|---|---|
| Ganho | indireto, mas é pré-requisito dos itens 5 e 6 |
| Firecrawl | zero |
| Gemini | zero |
| Risco | nenhum |
| Manutenção | baixa. Alguns MB por execução no repositório |

### 3. Deduplicar busca e encurtar a resposta pedida

- Uma busca por **escopo**, não por fonte: as quatro da ANP passam a fazer uma,
  e o resultado é compartilhado. Vale como crédito **e** como token.
- Separar o pedido ao Gemini em dois: **extrair** (fonte, título, URL, data,
  descrição) e, só depois, classificar. A extração não precisa do `prompt.md`
  de 29 mil caracteres repetido cinco vezes; precisa de um prompt curto.
- Parar de pedir **motivo escrito para cada Radar recusado**. É de onde vêm os
  1.082 caracteres por publicação.

| | |
|---|---|
| Ganho de cobertura | indireto: afasta o 429 |
| Firecrawl | **−24 créditos por execução** |
| Gemini | entrada de 277 mil → **cerca de 130 mil tokens** (−53%), sem nenhum recorte de conteúdo: −129 mil caracteres de prompt repetido, −25 mil de busca duplicada. Saída de 1.082 → ~300 caracteres por item |
| Risco de perder notícia | nenhum: nada de conteúdo é removido |
| Manutenção | média: dois prompts em vez de um, e a classificação precisa continuar existindo (item 4) |

### 4. Classificar por matriz e palavra-chave, com a IA como reforço

Depois de extrair, decidir o Radar sem gastar modelo:

- **fonte específica** → os Radares que a matriz do Filtro 1 já permite;
- **fonte genérica** (Planalto, DOU, Destaques, Ministério da Fazenda) → casar
  título e descrição com as palavras-chave que já estão no `prompt.md`;
- **não casou** → vai ao portal **como pendente, sem Radar**, para a pessoa
  decidir. Nunca some.

O filtro de relevância por IA passa a rodar **só quando um Radar passa de N
publicações no dia** (sugiro 15, configurável). Se falhar ou faltar cota,
**tudo segue para o portal sem filtro**.

Isso atende diretamente à causa 5 do diagnóstico: em quatro execuções a IA
recusou 92 pares e a curadoria humana rejeitou 6 de 61 itens. A IA filtra mais
do que a pessoa que revisa.

| | |
|---|---|
| Ganho de cobertura | **estimativa: +20 a +40 pares por execução**, pela ordem de grandeza dos 92 pares recusados em 4 execuções |
| Firecrawl | zero |
| Gemini | remove a classificação do caminho principal |
| Risco de perder notícia | **menor que hoje**: o que não casa vira pendente em vez de recusa |
| Manutenção | **média-alta**: as palavras-chave viram configuração e vão precisar de ajuste. É a parte que mais pede acompanhamento |

### 5. Busca por característica da fonte, não por tamanho da página

Trocar a regra de disparo por uma marcação em `fontes.json`: a fonte declara se
a listagem expõe data. Onde não expõe, a busca é obrigatória, independente do
tamanho. Onde expõe, é dispensável.

**Não dá para fazer isso direito antes do item 2**, porque hoje só ANATEL e
Receita Federal foram medidas. Com o dossier guardado, a medição sai sem gastar
crédito.

| | |
|---|---|
| Ganho de cobertura | **estimativa: médio.** Hoje 10 fontes não buscam, algumas provavelmente precisando |
| Firecrawl | **+2 créditos por fonte que passar a buscar**; ver o orçamento abaixo |
| Gemini | mais conteúdo relevante, menos ruído |
| Risco | baixo, e reversível fonte a fonte |
| Manutenção | baixa: um campo por fonte |

### 6. Recorte da janela, no nosso código

Sobre o dossier guardado, separar os blocos com data dentro da janela; **o que
não tem data reconhecível vai junto**. O recorte nunca decide o que é
relevante, só tira o que está comprovadamente fora da janela.

| | |
|---|---|
| Ganho de cobertura | indireto: resolve o teto de 30.000 que hoje corta 16 fontes |
| Gemini | **estimativa: mais 30 a 50% de redução de entrada**, sobre os 130 mil do item 3 |
| Risco de perder notícia | **o maior da proposta.** Se a heurística errar, a publicação some antes de o modelo ver |
| Manutenção | **média**: é código nosso sobre markdown de terceiros, e precisa de teste com dossier real guardado |

**Recomendo deixar este por último e só ligar depois de medir o item 2 contra
uma execução real.** Ele resolve um problema que, hoje, não é o que está
travando.

---

## O que eu faria e o que eu não faria

**Faria agora, nesta ordem:** 1, 2, 3. Somados, recuperam o modelo bom, tiram
53% da entrada do Gemini sem cortar uma linha de conteúdo, economizam 24
créditos por execução e não têm risco de perder publicação.

**Faria em seguida, com acompanhamento:** 4, depois 5.

**Deixaria para depois de medir:** 6.

**Não faria agora:** coleta individual por publicação (P7 do diagnóstico) —
passa de 200 chamadas por execução, inviável no plano atual. E não trocaria o
Gemini pelo modo JSON do Firecrawl: a comparação que rodamos mostrou que ele
extrai mais (37 contra 11 na mesma janela), mas custa 5 créditos por página, o
que daria 150 créditos só de extração por execução.

---

## O orçamento do Firecrawl, que é o teto de verdade

Medido na última execução: 30 coletas (1 crédito cada) + 21 buscas com 30
resultados (6 créditos cada) = **156 créditos por execução**. Com **455
créditos até 26/10, são menos de 3 execuções.**

| Cenário | Coletas | Buscas | Créditos/execução | Execuções em 1.000 |
|---|---|---|---|---|
| Hoje | 30 | 21 × 30 resultados | **156** | 6,4 |
| Sem escopo duplicado | 30 | 17 × 30 | 132 | 7,5 |
| + 10 resultados por busca | 30 | 17 × 10 | 64 | 15,6 |
| + busca em todas as fontes que precisam | 30 | 23 × 10 | **76** | **13,1** |
| + sem coletar onde só a busca serve | 24 | 23 × 10 | **70** | **14,2** |

**Mesmo com tudo otimizado, o plano gratuito dá cerca de 14 execuções por mês,
contra 21 dias úteis.** Isso não é problema de código: é o teto do plano.

As saídas, na minha ordem de preferência:

1. **Rodar em dias úteis alternados** — 11 execuções por mês, 770 créditos, com
   folga para repetir uma execução que falhe e para rodar a conferência de
   cobertura.
2. **Aposentar as duas fontes sem conserto conhecido** — COAF (acesso
   restrito, três URLs alternativas testadas e reprovadas) e MME Consultas
   Públicas (SPA sem listagem acessível). Zero publicações em quatro execuções,
   e liberam 6 créditos por execução.
3. **Plano pago do Firecrawl**, se o Radar precisa ser diário com 30 fontes.
   Não sei o preço — a documentação está bloqueada na rede daqui.

Recomendo 1 e 2 juntos por enquanto, e reavaliar 3 quando a cobertura estiver
estabilizada.

---

## A regra obrigatória, ponto a ponto

"Falha ou falta de cota nunca pode remover notícia sem registro."

| Situação | O que acontece na proposta |
|---|---|
| 503 no Gemini | repete no mesmo modelo; se desistir, registra o modelo usado por lote |
| 429 no Gemini | desce de modelo, registrado; com o dossier guardado, dá para reprocessar depois sem Firecrawl |
| Extração falha de todo | o dossier fica guardado e a fonte entra no log com o erro, como hoje |
| Nenhum Radar casa na classificação | vai ao portal como pendente, não é descartada |
| Filtro de relevância falha | passa tudo sem filtrar |
| Recorte da janela (item 6) | só remove bloco com data comprovadamente fora; sem data vai junto |
