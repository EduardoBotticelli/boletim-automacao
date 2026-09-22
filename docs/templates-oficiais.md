# Templates oficiais dos Radares

Os nove e-mails finais são gerados a partir dos templates que o Marketing
entregou em `templates/`. O HTML **não é recriado** pelo código: ele é
extraído do template e preenchido.

## Por que o .msg não é editado diretamente

O artefato do Marketing é `.msg`, que é um container OLE (Compound File
Binary). Editar o corpo exigiria reescrever esse container, e isso não é
viável no runner Linux do GitHub Actions:

- `olefile` só regrava um stream **do mesmo tamanho** do original
  (`write_stream` levanta `ValueError: data must be the same size as the
  existing stream`). O corpo preenchido nunca tem o tamanho do corpo com
  placeholders.
- Não existe escritor de `.msg` em Python puro no PyPI. `extract-msg` e
  `compoundfiles` são leitores.
- Os escritores que existem (Outlook COM, MAPI, Redemption) exigem Windows
  com Outlook instalado.

Por isso o `.msg` é tratado como **fonte somente leitura** e a edição final
sai como `.eml`.

## O que é aproveitado do template

O corpo do `.msg` é HTML encapsulado em RTF (MS-OXRTFEX). Desencapsular
devolve exatamente o HTML que o Marketing escreveu:

```
.msg  ->  PR_RTF_COMPRESSED  ->  descompressão  ->  RTF  ->  HTML original
```

Desse HTML vêm, sem nenhuma alteração: a folha de estilos, as tabelas, o
banner, os comentários condicionais do Word, as âncoras do sumário, o
"Voltar ao sumário", o bloco de avaliação, o rodapé e os links
institucionais. As imagens saem dos anexos do `.msg`, byte a byte, com os
mesmos Content-ID que o HTML referencia em `cid:`.

## Como o preenchimento funciona

`scripts/templates_radar.py` localiza trechos do HTML **por deslocamento de
bytes** e monta a edição concatenando fatias do original. Nenhum
serializador de HTML é usado na saída.

Isso é deliberado: BeautifulSoup e lxml não devolvem o HTML do Word como
entrou. Num teste com o Radar Tributário, o HTML original tem 39.754 bytes;
`html.parser` devolveu 39.366 e o `lxml` alterou os comentários
condicionais do Word de 6 para 27 ocorrências. Qualquer um dos dois
descaracterizaria o template.

Regras aplicadas:

| Regra | Onde |
|---|---|
| Data da edição no lugar de `00.00.2026` | `preencher` |
| Título, link "Acesse a matéria" e descrição | `_preencher_unidade` |
| Duplicar a estrutura de notícia para vários itens | `_corpo_preenchido` |
| Remover placeholders excedentes | `_corpo_preenchido` |
| Remover seção de fonte sem notícia | `preencher` |
| Remover a fonte do sumário | `preencher` |
| Radar sem notícia exibe a mensagem padrão | `_unidade_sem_noticias` |

Links internos do sumário, "Voltar ao sumário", avaliação e rodapé nunca são
tocados.

## Artefatos gerados

| Arquivo | Papel |
|---|---|
| `output/email_<slug>.eml` | Mensagem pronta para envio. `multipart/alternative` com texto puro e `multipart/related`, carregando o corpo do template e as imagens embutidas. Abre no Outlook e é aceito pela Graph API. |
| `output/email_<slug>.html` | Prévia da mesma edição, com as imagens apontando para `recursos_radar/<slug>/`. Serve para conferir no navegador e para quem enviar por corpo HTML. |
| `output/recursos_radar/<slug>/` | Imagens do template, extraídas do `.msg`. |

As imagens ficam em uma pasta por Radar porque os templates reaproveitam os
mesmos nomes de arquivo para imagens diferentes: `image006.png`, por
exemplo, é um banner distinto em três Radares.

### Estrutura da mensagem

```
multipart/related; type="multipart/alternative"
  multipart/alternative
    text/plain          (texto puro, para quem não renderiza HTML)
    text/html           (o corpo do template)
  image/png   Content-Disposition: inline + Content-ID   x9
```

O `multipart/related` por fora é o formato que o próprio Outlook gera: deixa
as imagens visíveis para o corpo HTML qualquer que seja a alternativa
escolhida pelo cliente. O parâmetro `type` diz qual é a parte raiz.

Cada imagem vai com **`Content-Disposition: inline`**. Com `attachment` o
Outlook lista as doze imagens como anexos e não as resolve no corpo — todas
as imagens aparecem como caixas quebradas, inclusive banner, avaliação e
redes sociais.

Isso espelha o que o `.msg` oficial declara para cada anexo:

| Propriedade MAPI | Valor no template | Equivalente MIME |
|---|---|---|
| `PR_ATTACH_FLAGS` | `4` (ATT_MHTML_REF) | parte dentro do `multipart/related`, referenciada por `cid:` |
| `PR_ATTACHMENT_HIDDEN` | `1` | `Content-Disposition: inline` |
| `PR_RENDERING_POSITION` | `-1` | idem |

### Recursos referenciados só dentro de comentário

Entram na mensagem apenas os recursos cujo `cid` o corpo referencia **fora
de comentário HTML**. Hoje isso exclui os três `.wmz`.

O Word emite cada botão de avaliação em duas versões:

```html
<!--[if gte vml 1]><v:shape ...><v:imagedata src="cid:image001.wmz@..."/></v:shape><![endif]-->
<![if !vml]><a href="..."><img src="cid:image003.png@..." alt=NEUTRA></a><![endif]>
```

`<!--[if ...]>` é comentário HTML de verdade; `<![if ...]>` não é. O Outlook
decide o que esconder da lista de anexos casando Content-ID com as
referências do corpo, e essa varredura ignora comentário. Resultado: os nove
PNG somem da lista e os três `.wmz` apareciam como anexos visíveis.

O tipo não é o motivo: o `.msg` original usa o mesmo
`application/x-ms-wmz` e mesmo assim os esconde, porque o MAPI tem a
propriedade `PR_ATTACHMENT_HIDDEN`, **que não tem equivalente em MIME**.
`Content-Disposition: inline` é o mais próximo e não basta para uma parte
que o cliente não associa ao corpo.

Sem os `.wmz` os botões continuam aparecendo: a versão em PNG está em
`<![if !vml]>`, fora de comentário, e é a que o Outlook usa. Verificado no
Outlook, abrindo uma edição sem os três — os botões EXCELENTE, NEUTRA e
RUIM renderizam normalmente.

A regra é geral, não uma exceção para `.wmz`: qualquer recurso que só seja
referenciado de dentro de comentário fica fora da mensagem, porque só teria
o efeito de virar anexo visível. Os arquivos continuam sendo extraídos para
`recursos_radar/`, para a prévia em HTML.

A mensagem leva `Subject`, `Date`, `Message-ID` e `X-Unsent: 1`. O
`X-Unsent` faz o Outlook abrir o arquivo como mensagem nova, pronta para
endereçar e enviar, em vez de mensagem recebida sem remetente. `From` e
`To` ficam em branco por padrão e podem ser preenchidos em
`templates/mapeamento_radares.json` (`remetente` e `destinatario`).

A função `conferir_eml` valida essa estrutura antes de gravar: se a
montagem regredir, a geração falha e os e-mails da edição anterior são
preservados.

### Sobre o envio por corpo HTML

O corpo do `.eml` usa `cid:`, que só resolve dentro de uma mensagem. Se o
disparo for feito colando HTML (por exemplo no "Send an email (V2)" do Power
Automate), as imagens `cid:` **não** aparecem: nesse caminho é preciso
hospedar os arquivos de `recursos_radar/` em URL pública e apontar os `src`
para lá, ou anexá-los como inline com os mesmos Content-ID. Enviar o `.eml`
evita esse problema.

## Fontes e seções

Cada seção do template corresponde a uma fonte. O casamento compara o nome
da fonte do `boletim.json` (a parte antes do `|`) com o nome da seção, sem
acento e sem pontuação. O que não casa sozinho é resolvido em
`templates/mapeamento_radares.json`, no bloco `aliases_fonte`.

Uma notícia aprovada cuja fonte não tem seção no template **bloqueia a
geração**, com o item identificado em `output/resumo_geracao_final.json`.
Publicar o Radar sem ela esconderia uma decisão humana, que é justamente o
que o resto do fluxo evita.

Para ver as âncoras disponíveis e as fontes ainda sem seção:

```bash
python scripts/inspecionar_templates.py
```

## Ajustes aplicados sobre o template

Os `.msg` não podem ser reescritos no Linux (ver acima), então dois ajustes
autorizados são aplicados ao HTML extraído, na geração. Estão declarados em
`templates/ajustes_templates.json` e implementados em
`scripts/ajustes_templates.py`.

Os dois precisam ser incorporados oficialmente pelo Marketing. A lista para
envio está no fim deste documento.

### Ajuste 1 — âncora do "VOLTAR AO SUMÁRIO"

O link aponta para `#Sumario` e essa âncora não existe em nenhum dos nove
templates, então o link não leva a lugar nenhum.

É inserido `<a name="Sumario"></a>` dentro do primeiro parágrafo da linha do
rótulo do sumário ("navegue pelas fontes"). A âncora é um elemento vazio:
não ocupa espaço, não muda texto, cor, fonte, espaçamento nem estrutura.

A linha do rótulo foi escolhida porque é o começo do sumário e é a única
parte dele que sobrevive na edição vazia, quando a grade de fontes é
removida inteira. Assim o link funciona também nessa edição.

### Ajuste 2 — seções de fonte que faltavam

Oito pares (Radar, fonte) que o Filtro 1 permite não tinham seção:

| Radar | Fontes acrescentadas | Seção copiada |
|---|---|---|
| societario-ma | ANEEL | Banco Central (Normas) |
| mercado-capitais-fundos | SUSEP | COAF |
| imobiliario-infraestrutura | ANATEL, ANTAQ, ANTT, SUSEP | ANEEL |
| ambiental-esg | ANTT, SUSEP | ANEEL |

Cada seção nova é **cópia literal** de uma seção existente do mesmo
template: a mesma linha de cabeçalho e a mesma linha de notícias, com a
troca apenas da âncora e do nome da fonte. Cor de faixa, fonte, altura,
espaçamento e marcação do Word vêm intactos da seção de origem. O código
confere o resultado: se o texto do cabeçalho copiado não ficar exatamente
igual ao nome da fonte nova, a geração falha.

A entrada no sumário é cópia de uma entrada existente e ocupa a primeira
célula livre da grade. A grade sempre tem três células por linha e mantém
as que sobram vazias; é esse mesmo comportamento que é usado. Só o Radar
Imobiliário e Infraestrutura precisou de uma linha nova, copiada da última
linha existente. Nenhuma largura de célula foi alterada.

**Critério de posição:** a seção nova entra depois da última seção
existente, e a entrada no sumário ocupa a primeira posição livre. É a única
posição que não desloca nenhuma entrada já definida pelo Marketing nem muda
a largura de célula alguma, e mantém sumário e corpo na mesma ordem. Entre
as novas, a ordem é alfabética. Se o Marketing preferir agrupar por tema
(as agências junto das outras agências, antes das publicações oficiais), é
só reposicionar quando incorporar oficialmente.

### Aliases

Com as seções criadas, os aliases que desviavam ANEEL, ANATEL, ANTAQ, ANTT e
SUSEP para outras seções foram **removidos**: cada notícia passa a sair sob
a própria fonte. O mecanismo continua disponível em `aliases_fonte` para
casos futuros, e hoje resolve apenas diferenças de nome — por exemplo
"Ministério da Agricultura" que no template se chama "MAPA".

## Defeitos do template: o que foi corrigido e o que resta

A entrega de 22/09/2026 corrigiu, no Radar Tributário, as âncoras com erro de
digitação e os links de título de seção que apontavam para âncoras
inexistentes. Resta um defeito, tratado pelo Ajuste 1 acima e **ainda
pendente** no arquivo oficial:

- o "VOLTAR AO SUMÁRIO" aponta para `#Sumario`, e nenhum dos nove templates
  tem âncora com esse nome.

## Consequência visual da remoção no sumário

O sumário é uma grade de três células por linha. Ao remover as fontes sem
notícia, as células restantes mantêm a largura original, então a grade pode
ficar irregular (uma linha com duas células, outra com uma). É o efeito
direto da regra "remover do sumário as fontes sem notícias" sobre uma grade
de largura fixa. Redistribuir as células mudaria a largura delas, o que
seria alterar o layout.

## Lista para o Marketing

Alterações que o pipeline aplica hoje sobre o HTML dos templates e que
precisam ser incorporadas aos arquivos `.msg` oficiais. Enquanto não forem,
o pipeline continua aplicando por cima, sem prejuízo.

**1. Âncora de destino do "VOLTAR AO SUMÁRIO" — nos nove Radares**

O link já existe e aponta para `#Sumario`, mas a âncora de destino não
existe. Criar, no bloco do sumário (na linha do rótulo "navegue pelas
fontes"), um indicador invisível chamado `Sumario`. No Word: posicionar o
cursor no início dessa linha e inserir um **indicador** (Inserir →
Indicador) com o nome `Sumario`. Não muda nada visualmente.

**2. Seções de fonte que faltam**

Criar, duplicando uma seção existente do mesmo Radar (faixa verde + bloco de
notícias) e acrescentando a fonte ao sumário:

| Radar | Fonte a criar |
|---|---|
| Radar Societário, Fusões e Aquisições | ANEEL |
| Radar Mercado de Capitais e Fundos de Investimento | SUSEP |
| Radar Negócios Imobiliários e Infraestrutura | ANATEL |
| Radar Negócios Imobiliários e Infraestrutura | ANTAQ |
| Radar Negócios Imobiliários e Infraestrutura | ANTT |
| Radar Negócios Imobiliários e Infraestrutura | SUSEP |
| Radar Ambiental e ESG | ANTT |
| Radar Ambiental e ESG | SUSEP |

São fontes que o Filtro 1 já autoriza para esses Radares. Sem a seção, uma
notícia delas não teria onde ser publicada.

Cada seção precisa de: a faixa verde com o nome da fonte, o indicador
(âncora) com o mesmo nome, o bloco de notícias no mesmo formato das demais,
e a entrada correspondente no sumário com link para o indicador.

A posição adotada pelo pipeline é depois da última seção existente, com a
entrada do sumário na primeira célula livre da grade de três colunas. Se
preferirem agrupar por tema, fiquem à vontade: o pipeline lê a ordem do
arquivo.

**3. Nada além disso**

Cabeçalho, data, imagens, bloco de avaliação, rodapé, links institucionais e
as seções que já existiam não foram tocados.

