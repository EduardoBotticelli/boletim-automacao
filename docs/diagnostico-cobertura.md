# Diagnóstico: por que os Radares estão saindo com poucas notícias

Medição feita sobre as execuções de **21, 22, 23 e 29 de setembro de 2026**,
com os artefatos que cada execução já commita (`output/boletim.json` e
`output/log_execucao.json`), mais as decisões de curadoria commitadas.

Reproduzível com:

```bash
python scripts/diagnostico_funil.py --execucoes 4 --fontes
```

**Nada foi alterado no pipeline.** Este documento e os dois scripts de
diagnóstico são o resultado da investigação; as mudanças propostas estão na
Etapa 4 e aguardam decisão.

---

## Limite desta medição

Duas coisas não foram possíveis neste ambiente e precisam ser ditas antes dos
números:

1. **A rede do container bloqueia `gov.br`.** Não consegui abrir as páginas
   oficiais para contar as publicações reais. A Etapa 2 foi entregue como
   ferramenta (`scripts/conferir_cobertura.py`), que roda onde há
   `FIRECRAWL_API_KEY` — no workflow ou na sua máquina. **Ela nunca foi
   executada contra as fontes reais**; a lógica de leitura do markdown foi
   testada com conteúdo sintético.
2. **O dossier não é guardado.** O pipeline não registra o conteúdo enviado ao
   Gemini nem quantos itens o Gemini devolveu antes da validação de data.
   Então as etapas 3 e 4 da sua lista (extraídas pelo Gemini / descartadas por
   data) não são mensuráveis hoje. Isso é, em si, um achado — ver P8.

---

## Etapa 1 — o funil, por etapa

Soma das quatro execuções:

| Etapa | Quantidade |
|---|---|
| Fontes coletadas com sucesso | 115 de 120 (30 por execução) |
| Caracteres entregues ao Gemini | **2.554.980** (481 mil a 676 mil por execução) |
| Fontes cortadas no limite de 30.000 caracteres | 50 de 120 (**42%**) |
| Publicações achadas pela busca complementar | **811** |
| — das quais entraram no dossier | 282 |
| — das quais foram **descartadas antes de chegar ao Gemini** | **529 (65%)** |
| Publicações extraídas pelo Gemini | **108** |
| Pares (publicação × Radar) sugeridos pela IA | 138 |
| — barrados pelo Filtro 1 (matriz) | 18 |
| — recusados pelo Filtro 2 (a própria IA) | 92 |
| Pares que chegaram ao portal | 120 |
| Rejeitados na curadoria | 6 de 61 itens (~10%) |

### A etapa que mais reduz

É a **passagem da coleta para a extração**: 2,5 milhões de caracteres e 811
publicações localizadas viram 108 publicações extraídas.

Tudo o que vem depois é pequeno em comparação: o Filtro 1 barrou 18 pares, o
Filtro 2 recusou 92, a curadoria rejeitou 6 itens. **A curadoria humana aprova
quase tudo o que recebe** — em três curadorias, 0, 0 e 6 rejeições. O gargalo
não está no fim do funil.

### Execução a execução

| Data | Modelo usado | Dossier | Cortadas | Busca descartada | Itens |
|---|---|---|---|---|---|
| 21/09 | gemini-3.7-flash | 642 mil | 13 | 155 | **47** |
| 22/09 | gemini-3.7-flash | 593 mil | 11 | 108 | **25** |
| 23/09 | gemini-3.5-flash-lite | 644 mil | 13 | 130 | **27** |
| 29/09 | gemini-3.5-flash-lite | 676 mil | 13 | 136 | **9** |

O dossier cresceu 5% entre 21/09 e 29/09 e o resultado caiu 80%.

---

## Etapa 2 — validação contra a fonte real

Entregue como `scripts/conferir_cobertura.py`. Para cada fonte ele coleta a
página de quatro maneiras e compara com o `boletim.json`:

| Coleta | Para quê |
|---|---|
| `only_main_content=True` | o que o pipeline coleta hoje |
| `only_main_content=False` | quanto a listagem perde com o parâmetro atual |
| conteúdo cortado em 30.000 | quantas publicações o limite descarta |
| `fc.search` na janela | o que a busca complementar encontra |

A saída responde, por fonte: **quantas publicações existiam na janela e
quantas chegaram ao `boletim.json`**.

O contador de publicações é uma heurística (links dentro do escopo da fonte,
com a data mais próxima, descartando navegação). O viés é para cima: na
dúvida, conta como se estivesse na janela. Então **a cobertura que ele calcula
é um piso** — se já aparece baixa, a perda é real.

### Controles de regressão

Os três casos que você citou estão codificados no script e são conferidos a
cada execução:

| Fonte | Sintoma registrado | Como o script detecta |
|---|---|---|
| ANEEL | perdeu seis publicações por corte | publicações presentes antes do corte e ausentes depois |
| ANVISA | não capturou o cancelamento do Elevidys | procura o termo entre as publicações da janela ausentes do boletim |
| ANATEL, SUSEP, ANPD | retornaram 1.300 a 1.800 caracteres | conteúdo principal abaixo de 5.000 contra a página inteira |

**Sobre o terceiro caso, o histórico já responde em parte.** Caracteres
entregues ao Gemini por execução:

| Fonte | 25/08 | 27/08 | 21/09 | 22/09 | 23/09 | 29/09 |
|---|---|---|---|---|---|---|
| ANATEL | 2.001 | 21.475 | 25.454 | 25.454 | 25.549 | 25.144 |
| SUSEP | 2.246 | 26.493 | 25.918 | 25.918 | 25.918 | 26.088 |
| ANPD | 2.110 | 27.719 | 28.252 | 28.982 | 28.982 | 28.962 |
| ANVISA | 4.668 | 22.885 | 13.098 | 8.276 | 7.028 | 29.916 |

O sintoma de conteúdo minúsculo **não reproduz desde 27/08**. Essas fontes hoje
entregam 25 mil caracteres. O problema atual delas é outro: entregam muito e
produzem quase nada — ver ANATEL abaixo.

---

## Etapa 3 — causas técnicas

### Causa 1 — a busca complementar é jogada fora exatamente onde mais importa

**Está no código, não é hipótese.** Em `scripts/gerar_boletim.py`:

```python
conteudo = bruto[:MAX_CHARS]                      # ja tem 30.000 caracteres
complementar = len(bruto) < LIMIAR_DINAMICO or len(bruto) > MAX_CHARS or ...
if complementar:
    descobertas = busca_complementar(fc, fonte, inicio, hoje)
    if descobertas:
        conteudo = (conteudo + "\n\n" + texto_busca(descobertas))[:MAX_CHARS]
```

Quando a página passa de 30.000 caracteres, `conteudo` já está no limite. O
texto da busca é concatenado **depois** e o corte em `MAX_CHARS` o elimina
inteiro. Ou seja: a busca complementar é disparada *porque* a página é grande,
gasta uma chamada de busca no Firecrawl, e o que ela encontrou nunca chega ao
Gemini.

O dossier ainda informa `publicacoes_localizadas: 30` ao modelo — o número,
sem as publicações.

Nas quatro execuções: **77 buscas executadas, 46 delas totalmente descartadas,
529 publicações perdidas aí**. Os maiores prejudicados:

| Fonte | Localizadas (4 execuções) | Itens extraídos |
|---|---|---|
| Ministério da Agricultura | 120 | 3 |
| SENACON | 113 | 5 |
| ANP \| Consultas e Audiências | 66 | **0** |
| ANP \| Notícias | 66 | 9 |
| ANTT | 54 | 13 |

### Causa 2 — a chamada única ao Gemini estoura a cota e derruba o modelo

O pipeline monta **um único prompt** com os 30 dossiers: 481 mil a 676 mil
caracteres (≈160 mil a 225 mil tokens), mais os 29 mil caracteres do
`prompt.md`.

O que o log registra nas tentativas:

| Data | Cascata |
|---|---|
| 21/09 | 3.7-flash na primeira tentativa |
| 22/09 | 3.7-flash na primeira tentativa |
| 23/09 | **6 tentativas falharam** — 503 e depois **429 RESOURCE_EXHAUSTED** em 3.7, 3.6 e 3.5 — caiu em 3.5-flash-lite |
| 29/09 | **7 tentativas falharam** pelo mesmo motivo — caiu em 3.5-flash-lite |

O `429 RESOURCE_EXHAUSTED` é cota, e uma requisição de 200 mil tokens a
consome de uma vez. A cascata então entrega o trabalho ao modelo mais fraco da
lista, que extrai menos. As duas execuções de 9 itens (27/08 e 29/09) foram as
duas que caíram para modelos de fallback.

A correlação não é perfeita — em 23/09 o `3.5-flash-lite` extraiu 27 itens.
Então o modelo não explica tudo sozinho. Mas **a cascata estar sendo acionada
por cota é um problema de confiabilidade por si só**, e ninguém é avisado: o
Radar sai menor e o único registro é o campo `modelo_gemini_utilizado`.

Testei a hipótese de "perder o que está no meio do contexto": os itens por
posição da fonte no dossier dão 46 / 23 / 39 no primeiro, segundo e terceiro
terços. Há uma queda no meio, mas ela se confunde com quais fontes estão ali.
**Não afirmo viés posicional com os dados que tenho.**

### Causa 3 — o formato de saída é caro por item

O prompt exige, para cada publicação: resumo, `motivo_filtragem`,
`palavras_chave_detectadas` e, em `boletins_rejeitados`, **um motivo escrito
por Radar recusado**. São ~1.100 caracteres de resposta por item, e o modelo
precisa avaliar os nove Radares de cada publicação.

Não há limite de itens no prompt — a restrição é o orçamento de resposta.

### Causa 4 — fontes que entregam muito e produzem nada

Em quatro execuções seguidas:

| Fonte | Chars médios | Itens | Leitura |
|---|---|---|---|
| ANATEL | 25.400 | **0** | coleta bem, não gera item nenhum |
| CNPE | 20.266 | **0** | idem, e a busca complementar nunca dispara |
| Receita Federal \| Normas | 30.000 | **0** | a URL é um formulário de consulta |
| ANP \| Consultas e Audiências | 30.000 | **0** | 66 localizadas, todas descartadas |
| ANP \| Consultas Prévias | 27.028 | **0** | 66 localizadas, entraram e não viraram item |
| ANP \| Pautas e Atas | 27.946 | **0** | idem |
| MME \| Consultas Públicas | 2.793 | **0** | SPA (`/home`), Firecrawl pega a casca |
| Kollemata | 4.926 | **0** | |
| COAF | 757 | **0** | **`erro_conteudo_origem` em 4 de 4 execuções** |

O COAF está quebrado há pelo menos quatro execuções e ninguém foi avisado.

`CNPE` cai numa faixa cega: com 20 mil caracteres não é pequena o bastante
(`< 5.000`) nem grande o bastante (`> 30.000`) para disparar a busca
complementar, e não tem `tipo_coleta`.

### Causa 5 — Radares famintos na origem, não no filtro

Fontes ativas que alimentam cada Radar, pela matriz do Filtro 1:

| Radar | Fontes ativas | Suspensas | Só por e-mail | Itens em 4 execuções |
|---|---|---|---|---|
| trabalhista-empresarial | **3** | 1 (CGU) | 0 | **0** |
| societario-ma | 4 | 0 | 1 | 2 |
| contencioso-civel | 4 | 0 | 0 | 4 |
| propriedade-intelectual | 5 | 0 | 0 | 9 |
| direito-tributario | 6 | 0 | 1 | 9 |
| mercado-capitais-fundos | 7 | 0 | 1 | 12 |
| ambiental-esg | 14 | 1 | 1 | 3 |
| imobiliario-infraestrutura | 18 | 0 | 4 | 35 |
| regulatorio-oleo-gas | 20 | 1 | 3 | 46 |

O Trabalhista saiu **vazio nas quatro execuções**, e quase não teve nem
rejeição: não há o que rejeitar. Suas três fontes ativas são genéricas
(Planalto, DOU, Ministério da Fazenda) e a única específica, a CGU, está
suspensa por defeso eleitoral. **Nenhum filtro vai resolver isso** — falta
fonte trabalhista (MTE, TST, CARF, Diário da Justiça).

O mesmo vale, em menor grau, para Societário (Latin Lawyer só por e-mail) e
Solução de Conflitos.

### Causas que não consegui confirmar

| Ponto da sua lista | Situação |
|---|---|
| URLs apontando para índice em vez de listagem | provável em Receita Federal, MME Consultas Públicas e Kollemata; **precisa da Etapa 2 rodando** |
| Carregamento dinâmico | provável em MME Consultas Públicas (SPA) e B3; **precisa da Etapa 2** |
| Efeito do `only_main_content` | **não medido** — é exatamente o que a Etapa 2 mede |
| Paginação | **não medido**; nenhuma fonte tem tratamento de paginação hoje |
| Corte de 30.000 | **confirmado**: 42% das coletas batem no teto |
| Qualidade da busca complementar | encontra bastante (811 em 4 execuções); a qualidade dos resultados não foi avaliada porque eles não são guardados |
| Chamada única ao Gemini | **confirmado como causa de falha de cota** |
| Descarte por data | **não mensurável** hoje; nas execuções lidas, nenhum item ficou sem data |
| Deduplicação | não é causa: não há dedup na coleta; a do gerador final casa por URL exata |
| Página de erro/bloqueio | **confirmado**: COAF em 4 de 4 |

---

## Etapa 4 — propostas

Ordenadas por ganho esperado dividido por risco. Nada disso foi aplicado.

### P1 — reservar espaço para a busca complementar *(fazer primeiro)*

Trocar "concatena e corta" por "reserva o espaço antes de cortar": o bloco da
busca entra inteiro e o conteúdo da página ocupa o que sobra de `MAX_CHARS`.

- **Ganho:** as 529 publicações descartadas passam a ser vistas pelo modelo —
  ~132 por execução. É o maior ganho isolado do diagnóstico.
- **Firecrawl:** **zero a mais**; ao contrário, recupera 46 de 77 buscas que
  hoje são pagas e jogadas fora.
- **Gemini:** o dossier não cresce (o teto por fonte continua o mesmo).
- **Risco:** baixo. Desloca o fim do conteúdo da página, que já era cortado
  arbitrariamente, em favor de publicações com título, URL e data.

### P2 — dividir a chamada ao Gemini em lotes

Em vez de um prompt com 30 fontes, N prompts com 5 ou 6 fontes cada, mantendo
a cascata de modelos em cada lote.

- **Ganho:** ataca o `429` direto. Cada lote fica em ~35 mil tokens, o modelo
  bom passa a ser usado de fato. Recupera a diferença entre 9 e 27–47 itens.
- **Gemini (custo):** o `prompt.md` é reenviado por lote — com 6 lotes, +40 mil
  tokens de entrada por execução (~25% a mais). Saída praticamente igual.
- **Gemini (tempo):** 6 chamadas sequenciais menores; tempo total parecido ou
  menor, porque hoje se gastam 7 tentativas falhas antes de uma que funciona.
- **Firecrawl:** nenhum impacto.
- **Risco:** médio-baixo. Duas coisas a cuidar: a instrução de não duplicar
  entre fontes só vale dentro do lote (mitigação: agrupar fontes correlatas no
  mesmo lote — as quatro da ANP juntas, energia junto); e as três listas de
  situação das fontes passam a vir por lote e precisam ser unidas.

### P3 — consertar as fontes que não produzem nada

Uma a uma, começando pelas que estão quebradas:

| Fonte | Ação | Firecrawl |
|---|---|---|
| COAF | conferir a URL; `erro_conteudo_origem` há 4 execuções | igual |
| MME Consultas Públicas | achar a listagem real ou a API por trás do SPA | igual |
| Receita Federal Normas | trocar o formulário de consulta por URL de resultado | igual |
| CNPE | dar `tipo_coleta` para a busca complementar disparar | +1 busca/execução |
| ANATEL, Kollemata | rodar a Etapa 2 antes de decidir | +2 chamadas, uma vez |

- **Ganho:** difícil estimar sem a Etapa 2 rodando; são 9 fontes com 0 itens em
  4 execuções, das quais 3 alimentam o Regulatório e o Imobiliário.
- **Risco:** baixo, mudança por fonte.

### P4 — alertar quando a cascata cair

Registrar no boletim, e falhar de forma visível no workflow, quando a execução
não usou o primeiro modelo.

- **Ganho:** nenhum em cobertura; evita que uma execução ruim passe despercebida.
- **Custo:** nenhum. **Risco:** nenhum.

### P5 — guardar o que hoje não é medido

Gravar, no `log_execucao.json`: quantos itens o Gemini devolveu **antes** da
validação de data, quantos foram descartados por data, e o dossier (ou um
resumo por fonte: quantos blocos com data na janela).

- **Ganho:** torna as etapas 3 e 4 mensuráveis. Hoje o diagnóstico tem um
  buraco exatamente onde está o gargalo.
- **Custo:** alguns KB por execução. **Risco:** nenhum.

### P6 — pré-extrair os registros da janela antes de mandar ao Gemini

Usar a mesma leitura do `conferir_cobertura.py` para, antes do Gemini, separar
do markdown os blocos com data dentro da janela, e mandar **esse extrato mais
o conteúdo bruto limitado**.

- **Ganho:** o dossier cairia de ~650 mil para a ordem de dezenas de milhares
  de caracteres úteis; o modelo bom nunca mais bateria na cota e trabalharia
  com sinal em vez de ruído.
- **Gemini:** queda grande de entrada, e portanto de custo.
- **Risco:** **o mais alto da lista.** Se a heurística errar, a publicação some
  antes de o modelo ver. Por isso a proposta é mandar os dois: extrato **e**
  bruto. Só vale depois que a Etapa 2 mostrar que a heurística acerta.

### P7 — paginação e coleta individual

Coletar a listagem e depois cada publicação.

- **Ganho:** o maior possível em fidelidade.
- **Firecrawl:** **proibitivo hoje.** Seriam 30 + N chamadas por execução; com
  ~15 publicações por fonte relevante, passa de 200 chamadas, contra as ~49 de
  hoje. Com o intervalo de 6,5 s isso é mais de 20 minutos só de espera.
- **Recomendação:** não fazer agora. Reavaliar para um punhado de fontes
  específicas depois de P1, P2 e P3.

### Ordem sugerida

1. **P1** (corrige um defeito, custo zero, maior ganho isolado)
2. **P4 + P5** (baratos, e dão a medição para avaliar o resto)
3. **P2** (resolve a queda para modelos fracos)
4. **P3** (fonte a fonte, com a Etapa 2 rodando)
5. **P6** só depois que a Etapa 2 provar a heurística; **P7** não agora

---

## Etapa 5 — o filtro de aderência temática

Só faz sentido mexer aqui depois de P1 e P2. Mas os números já dizem duas
coisas.

**O Filtro 2 recusa mais do que a curadoria.** Em quatro execuções, a IA
recusou 92 pares (publicação × Radar) e deixou passar 120. A curadoria humana,
que vê o que passou, rejeitou 6 itens de 61. Ou seja: a IA é mais restritiva do
que a pessoa que revisa — e agora existe a curadoria para filtrar, o que antes
não existia.

**Onde afrouxar renderia mais.** Pares recusados pelo Filtro 2 em Radares que
terminaram o dia com menos de 5 publicações:

| Data | Radar | Publicados | Recusados pelo Filtro 2 |
|---|---|---|---|
| 23/09 | contencioso-civel | 0 | **10** |
| 22/09 | contencioso-civel | 3 | 6 |
| 22/09 | societario-ma | 2 | 6 |
| 21/09 | societario-ma | 0 | 5 |
| 23/09 | direito-tributario | 1 | 4 |
| 29/09 | direito-tributario | 1 | 4 |
| 23/09 | mercado-capitais-fundos | 0 | 4 |

### Proposta: resgate por escassez, sem mexer no prompt

Sua ideia de aplicar o filtro rígido só quando o Radar tem muitos itens é boa,
e há um jeito de implementá-la **sem tornar o prompt mais permissivo** — o que
afetaria todos os Radares de uma vez.

O modelo já entrega, em `boletins_rejeitados`, os Radares que considerou
"tematicamente possíveis, mas insuficientes", com o motivo. Isso é uma lista de
quase-acertos pronta. A proposta é: **depois da classificação**, para cada
Radar que ficou abaixo de um piso (5, por exemplo), promover os pares recusados
pelo Filtro 2 até atingir o piso, marcando-os como resgatados.

- O Filtro 1 continua valendo: só se promove o que a matriz permite.
- O item resgatado chega ao portal identificado como tal, e a pessoa decide.
- Radar cheio não muda em nada.
- Não mexe no prompt, no portal, no contrato nem no gerador.

Teria levado o Contencioso de 0 para até 5 em 23/09, e o Societário de 0 para 5
em 21/09.

**O que isso não resolve:** o Trabalhista. Ele não teve recusas para resgatar,
porque não teve candidatos. Ali o problema é falta de fonte (Causa 5), e só
fonte nova resolve.

---

## Resumo em cinco linhas

1. A perda está entre a coleta e a extração, não nos filtros nem na curadoria.
2. **65% do que a busca complementar encontra é descartado por um defeito de
   ordem no corte de caracteres** — 529 publicações em quatro execuções.
3. A chamada única ao Gemini estoura a cota, derruba a execução para o modelo
   mais fraco e ninguém é avisado.
4. Nove fontes produziram zero itens em quatro execuções; o COAF está quebrado
   há pelo menos quatro.
5. O Trabalhista não tem problema de filtro: tem três fontes genéricas e
   nenhuma específica.

---

# Resultado: Etapa 2 executada e execução completa

Rodado em 29/09/2026 pelo workflow, com a chave do Firecrawl. O que abaixo diz
"medido" foi medido contra as fontes reais, não inferido.

## O que a conferência de cobertura encontrou

Primeiro, uma correção na própria ferramenta: a listagem do gov.br embrulha o
título no link da miniatura (`.../noticia/imagem.jpg/@@images/image/mini`).
Sem tirar esse sufixo, a comparação por URL nunca casava e **toda** publicação
aparecia como faltando. A primeira medição, de 28% de cobertura, estava
subestimada por isso. O casamento passou a aceitar também o título
normalizado.

### A causa que não estava na lista de hipóteses

`only_main_content=True` **elimina todos os links de publicação** em cinco
fontes:

| Fonte | Links no conteúdo principal | Links na página inteira |
|---|---|---|
| ANP \| Notícias | **0** | 262 |
| ANP \| Consultas e Audiências | **0** | 261 |
| ANP \| Consultas Prévias | **0** | 261 |
| ANP \| Pautas e Atas | **0** | 262 |
| CNPE | **0** | 67 |

Elas entregavam de 20 a 35 mil caracteres de texto sem um único link de
publicação. É a explicação de as quatro últimas fecharem quatro execuções em
zero. Passaram a ser coletadas com a página inteira.

### Causa por fonte, das que produziam zero

| Fonte | Publicações na listagem | Com data | Na janela | Causa | Ação |
|---|---|---|---|---|---|
| ANP ×4, CNPE | 0 / 261 na inteira | — | — | `only_main_content` | página inteira |
| ANATEL | 30 | **0** | 0 | listagem sem data | dispara a busca |
| Receita Federal | 31 | **0** | 0 | listagem sem data | P1 já resolve |
| Kollemata | 10 | 10 | **0** | **não publicou** | nenhuma |
| MME Consultas Públicas | 0 | 0 | 0 | SPA; busca acha 0 | **sem correção clara** |
| COAF | 2 ("Conteúdo Restrito") | 0 | 0 | acesso restrito | **sem substituta** |

As três URLs candidatas do COAF foram testadas e falharam:
`/assuntos/noticias` também restrito, `/centrais-de-conteudo/noticias` não
existe, e a home não é listagem.

### Controles de regressão

| Controle | Resultado |
|---|---|
| ANEEL, seis publicações por corte | **não reproduz**: 8.977 caracteres além do limite, nenhuma publicação datada na cauda |
| ANVISA, Elevidys | **não reproduz** o Elevidys, mas faltam 2 outras da janela (SNCR e o memorando com Hong Kong) |
| ANATEL, SUSEP, ANPD com 1.300 a 1.800 caracteres | **não reproduz**: hoje entregam 25 a 29 mil |

## A execução completa, contra as anteriores

| | 21/09 | 22/09 | 23/09 | 29/09 antes | **29/09 depois** |
|---|---|---|---|---|---|
| Modelo | 3.7-flash | 3.7-flash | 3.5-lite | 3.5-lite | 3.5-lite + 3.6-flash |
| Publicações extraídas | 47 | 25 | 27 | 9 | **31** |
| Busca complementar no dossier | 92 | 41 | 70 | 79 | **223** |
| Busca complementar descartada | 155 | 108 | 130 | 136 | **0** |
| Radares com conteúdo | 6 | 8 | 5 | 5 | **9** |
| Resgates por escassez | — | — | — | — | 7 |

A comparação justa é a última coluna contra a penúltima: **mesma janela, mesmo
dia, 9 publicações viraram 31**, e pela primeira vez os nove Radares saíram com
conteúdo.

Publicações por Radar na execução nova: trabalhista 1, tributário 5,
societário 1, mercado de capitais 7, regulatório 10, imobiliário 8, ambiental
3, propriedade intelectual 2, contencioso 2.

O Trabalhista, zerado nas quatro execuções anteriores, saiu com 1 — pelo
resgate. Continua valendo o que o diagnóstico disse: ali o problema é falta de
fonte, e o resgate só ameniza.

## O que ainda não está resolvido

**A cota do Gemini continua estourando.** Em quatro dos cinco lotes a cascata
desceu até o `3.5-flash-lite`, com seis tentativas falhas cada. Os lotes menores
ajudaram — 31 itens contra 9 —, mas o `429 RESOURCE_EXHAUSTED` não sumiu: a cota
é por minuto e cinco chamadas em sequência com 4 segundos de intervalo ainda a
estouram.

O intervalo entre lotes passou de 4 para 20 segundos por causa disso. **Esse
ajuste não foi validado em execução**: custa cerca de um minuto e meio a mais e
a próxima execução real dirá se leva o primeiro modelo da lista a ser usado.

**ANP Consultas e Audiências, ANP Consultas Prévias, CNPE e ANATEL continuam em
zero** mesmo com a página inteira e a busca complementar. O conteúdo agora
chega; o modelo é que não extrai publicação dele. Com o `3.5-flash-lite` em
quatro dos cinco lotes, vale reavaliar depois que a cota deixar de derrubar a
cascata.
