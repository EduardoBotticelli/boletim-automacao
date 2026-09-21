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

## Fontes roteadas para outra seção

Oito pares (Radar, fonte) que o Filtro 1 permite não têm seção própria no
template correspondente. Em vez de bloquear a edição, cada um foi mapeado
para uma seção que já existe no template, em `aliases_fonte`:

| Radar | Fonte | Seção usada | Por quê |
|---|---|---|---|
| societario-ma | ANEEL | Diário Oficial da União | Os atos da agência são publicados no DOU, que é a seção de publicações oficiais desse template |
| mercado-capitais-fundos | SUSEP | Ministério da Fazenda | A SUSEP é autarquia vinculada ao Ministério da Fazenda |
| imobiliario-infraestrutura | SUSEP | Ministério da Fazenda | idem |
| imobiliario-infraestrutura | ANATEL | Diário Oficial da União (Seção 1) | Sem seção própria; publicações oficiais |
| imobiliario-infraestrutura | ANTAQ | Diário Oficial da União (Seção 1) | idem |
| imobiliario-infraestrutura | ANTT | Diário Oficial da União (Seção 1) | idem |
| ambiental-esg | ANTT | Diário Oficial da União (Seção 1) | idem |
| ambiental-esg | SUSEP | Ministério da Fazenda | idem |

Nos Radares em que essas fontes têm seção própria (a ANTAQ no Regulatório,
por exemplo), o casamento automático resolve e o alias não é usado.

**O que isso implica.** A faixa da seção é lida como a origem da notícia.
Uma notícia da ANTAQ publicada sob "Diário Oficial da União" aparece com uma
procedência que não é exatamente a dela. É o preço de não criar seções novas
no template. A correção definitiva é o Marketing acrescentar as seções que
faltam; feito isso, basta remover o alias e o casamento automático assume.

`python scripts/inspecionar_templates.py` confirma que, hoje, toda fonte do
Filtro 1 tem destino.

## Item adicionado manualmente no portal

A fonte de um item manual é texto livre e pode não existir em nenhuma seção.
Por padrão esse item **bloqueia** a geração, para não sair sob o nome de uma
fonte que não é a dele.

Para liberar, preencha `secao_padrao_item_manual` no mapeamento com a âncora
da seção que deve receber esses itens no Radar:

```json
"secao_padrao_item_manual": {
  "contencioso-civel": "DiarioOficialUniao"
}
```

Vazio (o padrão) mantém o bloqueio. A alternativa sem esse efeito é
acrescentar um alias para a fonte específica, quando ela se repete.

## Defeitos observados nos templates entregues

Estes pontos vieram assim do Marketing e foram **preservados**, não
corrigidos:

- **Radar Tributário**: o sumário lista oito fontes, mas o template tem nove
  seções — "Portal Reforma Tributária" não tem entrada com link no sumário.
- **Voltar ao sumário**: o link aponta para `#Sumario`, e não existe âncora
  com esse nome em nenhum dos nove templates.
- **Radar Tributário**: os títulos de sete seções são links para âncoras que
  não existem (`#MinisteriodaFazenda`, `#Diariooficial`, `#DOU`, `#PLANALTO`,
  `#BANCOCENTRAL`).

## Consequência visual da remoção no sumário

O sumário é uma grade de três células por linha. Ao remover as fontes sem
notícia, as células restantes mantêm a largura original, então a grade pode
ficar irregular (uma linha com duas células, outra com uma). É o efeito
direto da regra "remover do sumário as fontes sem notícias" sobre uma grade
de largura fixa. Redistribuir as células mudaria a largura delas, o que
seria alterar o layout.
