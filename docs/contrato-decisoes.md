# Contrato entre o portal de curadoria e o gerador final

Este documento descreve o formato de `output/decisoes_alice.json`, o arquivo
que liga os dois repositórios:

- **Curadoria-Boletim** (portal Next.js na Vercel) grava o arquivo;
- **boletim-automacao** (`scripts/gerar_boletim_final.py`) lê o arquivo.

O teste `scripts/testar_decisoes_portal.py` valida este contrato e roda no
workflow antes de qualquer geração.

## Fluxo

```
gerar_boletim.py
  -> output/boletim.json                  (commitado em main)
  -> portal lê via raw.githubusercontent
  -> pessoa revisa
  -> POST /api/revisao
  -> output/decisoes_alice.json           (commitado via API do GitHub)
  -> repository_dispatch: confirmar-revisao
  -> gerar_boletim_final.py
  -> output/email_<slug>.html             (nove arquivos)
```

## Como um item é reconhecido

`boletim.json` **não tem campo de id**, e a posição do item no array muda a
cada execução do pipeline. Por isso a chave de casamento é o conteúdo:

1. a **URL** (normalizada, sem barra final);
2. na falta de URL, **fonte + título** normalizados (sem acento, minúsculas).

Consequência prática: os campos `url`, `fonte` e `titulo` de cada decisão
carregam sempre os valores **originais** do `boletim.json`. Qualquer alteração
feita na curadoria viaja em campos separados (`titulo_editado`,
`resumo_editado`, `fonte_editada`, `url_editada`,
`data_publicacao_editada`), que o gerador aplica por cima do item original.
Se a edição fosse gravada no próprio campo `url`, o item deixaria de ser
encontrado.

## Formato

```json
{
  "versao_formato": 2,
  "revisao_concluida": true,
  "origem": "portal-curadoria",
  "confirmado_em": "2026-08-27T18:00:00.000Z",
  "data_execucao": "2026-08-27",
  "total_itens": 10,
  "total_aprovados": 9,
  "total_rejeitados": 1,
  "total_sem_radar": 0,
  "radares_sem_conteudo_confirmados": ["contencioso-civel"],
  "decisoes": [
    {
      "id": "it-1a2b3c4d",
      "status": "aprovado",
      "status_portal": "ajustado",
      "acao_revisao": "radar_alterado",
      "origem": "scraper",
      "url": "https://www.gov.br/cvm/noticia-244",
      "fonte": "CVM | Notícias",
      "titulo": "CVM orienta sobre a Resolução 244",
      "radares_originais": ["mercado-capitais-fundos"],
      "radares_finais": ["mercado-capitais-fundos", "ambiental-esg"],
      "boletins": ["mercado-capitais-fundos", "ambiental-esg"]
    }
  ]
}
```

### Campos do envelope

| Campo               | Papel |
|---------------------|-------|
| `versao_formato`    | `2`. Serve para identificar o formato em uma futura mudança. |
| `revisao_concluida` | Tem de ser `true`. Com `false` o gerador para e preserva os e-mails anteriores. |
| `confirmado_em`     | Momento da confirmação, em ISO 8601. |
| `data_execucao`     | Edição do boletim que foi revisada. |
| `decisoes`          | Uma entrada por item da edição, incluindo os retirados e os sem Radar. |
| `total_sem_radar`   | Dos rejeitados, quantos chegaram sem Radar e ninguém atribuiu um. |
| `radares_sem_conteudo_confirmados` | Radares que saem sem nenhuma publicação, com ciência explícita de quem revisou. Lista vazia quando todos têm conteúdo. |

### Campos da decisão

| Campo             | Papel |
|-------------------|-------|
| `status`          | Só `"aprovado"` ou `"rejeitado"`. É o que o gerador lê. |
| `status_portal`   | Situação no portal: `aprovado` (chegou com Radar e ficou), `ajustado` (Radar mudado ou atribuído), `rejeitado` (retirado) ou `sem_radar` (chegou sem Radar e ninguém atribuiu). |
| `acao_revisao`    | O registro do que quem revisou fez no item: `mantida`, `radar_alterado`, `radar_atribuido`, `retirada`, `sem_radar` ou `adicionada`. |
| `radares_originais` | Radares com que o item chegou ao portal. Com `radares_finais`, mostra o que mudou. |
| `motivo`          | Só nos rejeitados: "Retirada na revisão." ou "Chegou sem Radar definido e nenhum Radar foi atribuído na revisão." |
| `origem`          | `"scraper"` (veio do pipeline) ou `"manual"` (adicionado na curadoria). |
| `url`, `fonte`, `titulo` | Valores originais. São a chave de casamento. |
| `radares_finais`  | Slugs de destino. `boletins` é o mesmo valor, aceito como alias. |
| `*_editado(a)`    | Opcionais. Só aparecem quando houve edição. |
| `noticia`         | Só quando `origem` é `"manual"`: o conteúdo completo do item. |

### Nada fica à espera de decisão

O item com Radar definido pelo pipeline (pela IA ou pelas regras sem IA)
chega ao portal já incluído. Quem revisa só age para retirar um item ou mudar
o Radar dele. O item sem Radar fica numa lista recolhida, "Sem Radar
definido", que não bloqueia a confirmação: se ninguém atribuir um Radar, ele
vai no arquivo como `status: "rejeitado"`, `status_portal: "sem_radar"` e o
motivo escrito. Assim "foi retirado por alguém" e "não tinha Radar" continuam
distinguíveis depois de gravado.

O gerador registra no `resumo_geracao_final.json`, em `fora_do_email`, cada
item que não foi para o e-mail, com o motivo e a `acao_revisao`. Decisão
antiga, sem `motivo`, recebe o motivo pelo `status_portal`. O resumo passa a
ser commitado junto com os e-mails.

Se chegar um `status: "pendente"` de um cliente antigo, o gerador continua
bloqueando a geração em vez de adivinhar, e preserva os e-mails anteriores.

### Radar sem conteúdo

Um Radar pode acabar sem nenhuma publicação. Em vez de sair só com a mensagem
padrão sem que ninguém tenha reparado, o portal bloqueia a conclusão da
revisão e oferece, para cada Radar vazio, as publicações coletadas naquela
edição que não estão nele. Um botão ("Enviar sem publicações") confirma todos
os Radares vazios de uma vez.

Para liberar, quem revisa faz uma das duas coisas:

- inclui pelo menos uma publicação no Radar — o que é o mesmo ajuste manual
  de Radar que já existia, e viaja em `radares_finais` como qualquer outro; ou
- marca que o Radar pode sair vazio mesmo assim — e aí o slug entra em
  `radares_sem_conteudo_confirmados`.

A marcação vale para o Radar que está vazio no momento. Se ele receber uma
publicação depois, a marcação é descartada: voltando a ficar vazio, a decisão
precisa ser tomada de novo.

**O gerador não inclui nada por conta própria.** Ele lê a lista só para
registrar, no `resumo_geracao_final.json`, quais Radares saíram vazios
(`radares_sem_conteudo.gerados_vazios`), quais tinham confirmação
(`confirmados_no_portal`) e quais saíram vazios sem registro
(`sem_registro_de_confirmacao`, que acontece com payload de um portal antigo).
Nenhum desses casos bloqueia a geração.

## Quando o gerador se recusa a gerar

Em todos estes casos o script sai com código diferente de zero, grava o
motivo em `output/resumo_geracao_final.json` e **preserva** os
`email_<slug>.html` da edição anterior:

- `decisoes_alice.json` ausente, inválido ou sem decisões reconhecíveis;
- `revisao_concluida` marcado como falso, rascunho ou pendente;
- algum item do `boletim.json` sem decisão correspondente;
- decisão com status não reconhecido;
- item aprovado sem nenhum Radar válido.

Decisões sem item correspondente que **não** trazem conteúdo embutido são
registradas em `decisoes_sem_item_correspondente` e ignoradas, sem bloquear:
é o caso de o pipeline ter rodado de novo entre a revisão e a geração.

## Os nove slugs

`trabalhista-empresarial`, `direito-tributario`, `societario-ma`,
`mercado-capitais-fundos`, `regulatorio-oleo-gas`,
`imobiliario-infraestrutura`, `ambiental-esg`, `propriedade-intelectual`,
`contencioso-civel`.

Os slugs são técnicos e estão replicados em `scripts/gerar_boletim_final.py`
(`SLUGS`), `scripts/gerar_boletim.py` (`SLUGS`) e, no portal, em
`lib/boletins.ts` e `lib/types.ts`. Qualquer slug fora dessa lista é
descartado em silêncio pelo gerador.
