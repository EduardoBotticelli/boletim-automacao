# Radar sugerido sem IA e filtro de órgãos da Receita

Dois ajustes pedidos depois da execução de 30/09:

1. a publicação que a IA não devolve chega ao portal com um Radar sugerido,
   quando dá para sugerir com segurança, identificada como sugestão sem IA;
2. a Receita Federal manda ao Gemini só os atos dos órgãos centrais.

Tudo aqui foi medido com dados guardados, sem Firecrawl e sem Gemini.

## 1. Radar sugerido sem IA

### O problema

Em 30/09, com os três primeiros modelos da cascata em 503, o
`gemini-3.5-flash-lite` devolveu 43 das 82 publicações coletadas direto das
fontes. As 38 que faltaram (Banco Central 11, Receita 23, Fazenda 2, CCEE 2)
foram ao portal sem Radar, pelo ajuste do PR #9.

### Alternativas avaliadas

Base de avaliação: os itens de 13/07 a 29/09 (antes de 13/07 os Radares eram
outros), com a decisão da curadoria quando havia (58 itens, todos de setembro) e
a da IA nos demais, contando também quando a IA deixou o item sem Radar. Os métodos foram
testados nos 148 itens de 01/09 a 29/09, e o perfil da fonte foi calculado só
com 13/07 a 31/08, para não medir o método com a própria resposta. O texto
usado é o título: o histórico guarda o resumo escrito pela IA, não a descrição
da fonte, e o resumo da IA facilitaria o acerto.

| Método | Cobre | Igual à decisão | Radar errado | Em item sem Radar |
|---|---|---|---|---|
| Matriz (Filtro 1 com um Radar só) | 27 | 25 | 0 | 2 |
| Palavras-chave do prompt.md, sem restrição | 30 | 24 | 3 | 3 |
| Perfil da fonte (Radar predominante) | 24 | 23 | 0 | 1 |
| Matriz + palavras-chave sem restrição + perfil | 61 | 52 (85%) | 3 | 6 |
| **Matriz + palavras-chave com as regras abaixo + perfil (adotado)** | **49** | **46 (94%)** | **0** | **3** |

Com título e resumo, o método adotado cobre 67 dos 148, 61 iguais à decisão
(91%), 1 em Radar errado e 5 em itens sem Radar.

Também foram consideradas e deixadas de lado:

- **Vizinho mais parecido no histórico** (título parecido da mesma fonte):
  nos normativos do Banco Central os títulos são todos "Comunicado nº ...", e
  o método vira o perfil da fonte, só que mais caro, porque exige guardar e
  ler o histórico a cada execução.
- **Segunda passada da IA só com o que faltou**, em lote pequeno: não é "sem
  IA" e gasta cota do Gemini no dia em que ela já está no limite. Pode vir
  depois, antes da sugestão por regra, se fizer sentido.

### Regras adotadas (`scripts/sugestao_sem_ia.py`)

Antes de tudo, a definição da fonte pode tirar publicações da sugestão
(`sem_sugestao`). É o caso dos **atos internos do Banco Central**: Ato de
Diretor ou Ato do Presidente cujo título ou descrição fala de inquérito,
sindicância, servidores, lotação, função comissionada, substituição, férias,
delegação de competência, regimento ou estrutura organizacional. Vão sem
Radar, com o motivo "ato interno do Banco Central (comissão de inquérito,
pessoal ou organização interna)". O tipo sozinho não basta: o Ato do
Presidente que decreta a liquidação extrajudicial de uma distribuidora não é
interno e segue as regras abaixo.

Depois, a primeira regra que decide vale:

1. **Matriz**: se o Filtro 1 liga a fonte a um Radar só (Receita →
   Tributário, INPI → Propriedade Intelectual, B3 → Mercado de Capitais), é
   esse Radar.
2. **Palavras-chave do prompt.md**: os termos de "Palavras e temas
   indicativos" (e "Projetos em acompanhamento") de cada Radar, contados no
   título e na descrição, só entre os Radares do Filtro 1 da fonte.
   - Termo que aparece na lista de três ou mais Radares não conta.
   - O nome da própria fonte não conta ("Banco Central" numa norma do Banco
     Central, "CCEE" numa notícia da CCEE).
   - Sigla curta (ANA, CAT, NR, PLD) só casa em maiúsculas.
   - O Radar vencedor precisa de um termo composto ("oferta pública") ou de
     dois termos diferentes. Um termo solto ("energia") não basta.
   - Empate entre Radares só se resolve pelo perfil da fonte; sem perfil, o
     item fica sem Radar.
3. **Perfil da fonte**: o Radar predominante da fonte no histórico, declarado
   em `radar_predominante` na definição dela, com a base do número. Hoje:
   - Banco Central | Normas → Mercado de Capitais (74 de 74);
   - ANP | Notícias → Regulatório (28 de 30);
   - ANEEL | Últimas Notícias → Regulatório (24 de 24).

   Critério usado para declarar: ao menos 20 publicações e 90% delas no mesmo
   Radar, contando as que a IA deixou sem Radar.

**Fontes genéricas** (Planalto, Diário Oficial, Destaques do DOU, Ministério
da Fazenda) não passam pela matriz nem pelo perfil. Só recebem sugestão por
palavras-chave, com dois termos diferentes do mesmo Radar e esse Radar à
frente dos outros. A sugestão é sempre de um Radar só. A fonte é tratada como
genérica pela marca `"generica": true`, pelo nome (Planalto, Diário Oficial,
DOU, Ministério da Fazenda) ou por ter no Filtro 1 todos os Radares. Nos 148
itens de teste havia 27 dessas fontes: 3 receberam Radar pelo título, todos
iguais à decisão.

**Seções dos templates**: o Radar sugerido precisa ter seção própria para a
fonte no template, pela mesma resolução do gerador final. Se os templates não
puderem ser lidos, nenhuma sugestão é feita e o log diz por quê. Hoje todo par
fonte-Radar do Filtro 1 tem seção (há teste para isso).

O que nenhuma regra decide continua indo sem Radar, com o motivo escrito.

### Como chega ao portal

A sugestão nunca entra em `boletins`. O item leva:

- `sugestao_sem_ia`: `{"radares": [...], "metodo": "matriz" | "palavras_chave" | "perfil_da_fonte", "evidencia": "..."}`, ou `radares` vazio e `motivo_sem_radar`;
- `nao_classificada_pela_ia: true`;
- `motivo_filtragem` começando por `[Sugestão sem IA: <Radar>, por <método>]`
  e dizendo que o Radar veio de regra fixa, não da IA; ou por `[Não
  classificada pela IA]` com o motivo de não haver sugestão.

No portal (PR separado no Curadoria-Boletim), o item chega **pendente**, com
o selo "Sugestão sem IA" e o Radar já marcado no painel. Só entra no boletim
se a pessoa confirmar; enquanto estiver pendente, a revisão não fecha. Sem o
PR do portal, o item aparece como hoje: pendente, sem Radar, com o motivo
escrito, então a ordem dos merges não abre brecha.

### Log

`log_execucao.json` ganha `distribuicao_sem_ia`:

```json
{"itens": 19, "com_radar_sugerido": 15,
 "por_metodo": {"matriz": 4, "palavras_chave": 1, "perfil_da_fonte": 10},
 "sem_radar": 4, "por_radar": {...}, "motivos_sem_radar": {...}, "por_fonte": {...}}
```

e `sugestao_indisponivel` quando os templates não puderam ser lidos. A
auditoria do `boletim.json` ganha `sugestoes_sem_ia`. O aviso do workflow diz
quantos itens voltaram ao portal e quantos com Radar sugerido.

### Resultado nos dados de 30/09

Reproduzido do dossier guardado e da resposta guardada da IA:

| | Itens | Com Radar sugerido | Matriz | Palavras-chave | Perfil | Sem Radar |
|---|---|---|---|---|---|---|
| Como foi (sem filtro de órgãos) | 38 | 33 | 23 | 1 | 9 | 5 |
| Com o filtro de órgãos da Receita | 19 | 14 | 4 | 1 | 9 | 5 |

Exemplos:

| Publicação | Sugestão | Por quê |
|---|---|---|
| Solução de Consulta Cosit nº 190 (IRRF, manutenção de elevadores) | Tributário | matriz: a Receita só alimenta o Tributário |
| Ato Declaratório Executivo Corat nº 79 | Tributário | matriz |
| BC Comunicado nº 46.038 (operações compromissadas, módulo Oferta Pública) | Mercado de Capitais | palavra-chave "oferta pública" |
| BC Comunicado nº 46.039 (TBF, Redutor R e TR de 29/09) | Mercado de Capitais | perfil da fonte (74 de 74) |
| BC Comunicado nº 46.037 (cancelamento de autorização de administradora de consórcios) | Mercado de Capitais | perfil da fonte |
| BC Ato de Diretor nº 705 (designa servidores para comissão de inquérito) | sem Radar | ato interno do Banco Central |
| CCEE: "Últimos dias para inscrição no curso de Formação de Preços" | sem Radar | só um termo solto ("energia") |
| CCEE: "Confira a apresentação e o vídeo do Encontro do PLD" | sem Radar | nenhuma palavra-chave |
| Fazenda: "Governo Central registra em agosto déficit primário" | sem Radar | fonte genérica sem palavra-chave |
| Fazenda: "Saldo de operações de crédito garantidas pela União" | sem Radar | fonte genérica sem palavra-chave |

Limites conhecidos:

- O perfil da fonte sugere o Radar predominante mesmo para publicação
  irrelevante da fonte que não esteja em `sem_sugestao`. A matriz faz o mesmo
  com aviso operacional ("Serviços do INPI estão temporariamente indisponíveis"). Nos
  148 itens de teste foram 3 sugestões em itens que ficaram sem Radar (os
  avisos de sistema fora do ar do INPI e da ANP e uma notícia de projeto de
  lei do Kollemata). Como o item chega pendente, a pessoa rejeita.
- O perfil é declarado no `fontes.json` (e no `gerar_boletim.py` para o
  Banco Central). Não se atualiza sozinho: se a fonte mudar de perfil, a
  declaração precisa ser revista.
- As palavras-chave são as do prompt.md. Mudar a lista lá muda a sugestão
  aqui, sem outra configuração.

## 2. Receita Federal: só órgãos centrais

A definição da Receita no `fontes.json` ganhou a lista `orgaos`:

```
RFB, SRF, Sutri, Suara, Sufis, Suari, Cosit, Coana, Corat, Codac, Cofis, Cocad, Cocaj, Cetad
```

O órgão de cada ato vem da tabela do SIJUT e vale pela parte antes da barra:
`ALF/BSB` é a alfândega de Brasília (sai), `DRF/SOR` a delegacia de Sorocaba
(sai), `SRRF08` a superintendência da 8ª região (sai), `RFB/PGFN` é ato
conjunto da RFB (fica). Ato sem órgão informado continua indo, porque não dá
para saber de onde é.

Nada some: o ato excluído fica na coleta e no dossier guardado com `enviar`
falso e `excluida_pelo_filtro` explicando o órgão. O log traz, por fonte,
`excluidas_pelo_filtro_de_orgao` e `orgaos_excluidos`, e o topo do log traz
`filtro_de_orgaos`. Se a coleta direta da Receita falhar e a fonte cair para
o Firecrawl, o filtro não se aplica naquele dia (a página vai inteira ao
Gemini, como antes).

### Nos 52 atos do ensaio de 30/09 (janela 29/09 a 30/09)

**Ficam 13:**

| Data | Ato |
|---|---|
| 30/09 | Ato Declaratório Executivo Corat nº 79 (altera anexos dos ADE Corat 63 e 78) |
| 30/09 | Ato Declaratório Executivo Sutri nº 9 (vincula a RFB e uma pessoa jurídica a um termo; a descrição vem cortada na tabela) |
| 30/09 | Solução de Consulta Cosit nº 195 (IRPJ, repasses de recursos) |
| 30/09 | Solução de Consulta Cosit nº 190 (IRRF, manutenção elétrica e de elevadores) |
| 30/09 | Ato Declaratório Executivo Coana nº 136 (certifica Operador Econômico Autorizado) |
| 29/09 | Ato Declaratório Executivo Corat nº 78 (Agenda Tributária de outubro) |
| 29/09 | Soluções de Consulta Cosit nº 185, 187, 188, 189, 191, 192 e 193 |

**Saem 39:** DRF 20 (Sorocaba 17, Novo Hamburgo 2, Belo Horizonte 1),
ALF 9 (Belo Horizonte 4, Manaus 3, Brasília 1, Viracopos 1), Decex 4 (Rio 1,
São Paulo 3), superintendências regionais 5 (SRRF08 2, SRRF10 1, SRRF03 1,
SRRF09 1) e IRF 1 (São Luís). São habilitações ao Reidi, registros especiais
de bebidas, inscrições de ajudantes de despachante, certificações de OEA
regionais, horários de atendimento e atos internos das unidades.

Na execução de 30/09, que coletou 24 atos só do dia 30, o filtro teria
mandado 5 ao Gemini e deixado 19 no registro.
