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
  "decisoes": [
    {
      "id": "it-1a2b3c4d",
      "status": "aprovado",
      "status_portal": "ajustado",
      "origem": "scraper",
      "url": "https://www.gov.br/cvm/noticia-244",
      "fonte": "CVM | Notícias",
      "titulo": "CVM orienta sobre a Resolução 244",
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
| `decisoes`          | Uma entrada por item revisado, incluindo os rejeitados. |

### Campos da decisão

| Campo             | Papel |
|-------------------|-------|
| `status`          | Só `"aprovado"` ou `"rejeitado"`. É o que o gerador lê. |
| `status_portal`   | O que a pessoa fez (`aprovado`, `ajustado`, `rejeitado`, `pendente`). Só auditoria; o gerador ignora. |
| `origem`          | `"scraper"` (veio do pipeline) ou `"manual"` (adicionado na curadoria). |
| `url`, `fonte`, `titulo` | Valores originais. São a chave de casamento. |
| `radares_finais`  | Slugs de destino. `boletins` é o mesmo valor, aceito como alias. |
| `*_editado(a)`    | Opcionais. Só aparecem quando houve edição. |
| `noticia`         | Só quando `origem` é `"manual"`: o conteúdo completo do item. |

### Itens pendentes

O portal nunca exporta `status: "pendente"`. Um item que a pessoa deixou sem
decisão é exportado como `rejeitado`, com `status_portal: "pendente"`, e o
diálogo de confirmação avisa quantos itens serão descartados. Se um cliente
antigo mandar `"pendente"` em `status`, o gerador bloqueia a geração em vez
de adivinhar.

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
