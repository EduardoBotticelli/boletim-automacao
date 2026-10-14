# Prazo da etapa da IA

## O que aconteceu em 01/10

Na execução #76 a coleta terminou em 1 min 40 s (10:40) e a primeira chamada ao
Gemini nunca respondeu. A biblioteca `google-genai` não tem tempo-limite por
padrão (`timeout=None`), então o script ficou esperando até o workflow ser
cancelado aos 60 minutos. O log do passo não mostrou nada nesse tempo, porque o
Python guarda a saída quando não escreve num terminal. O dossier foi guardado,
mas a edição do dia não saiu.

## O que mudou

1. **Andamento no log.** `PYTHONUNBUFFERED=1` no job e saída linha a linha no
   `gerar_boletim.py`. Cada lote e cada tentativa aparecem na hora, com a
   duração:

   ```
   Etapa da IA: 16 fonte(s) em lotes de 6; prazo de 15 min, até 180 s por chamada.
   Lote 1/3 da IA: 6 fonte(s), 15 min até o prazo
     gemini-3.7-flash: sem resposta no tempo-limite em 180 s; passa ao próximo modelo
     gemini-3.6-flash: respondeu em 41 s
   ```

2. **Tempo-limite de cada chamada** (`TEMPO_CHAMADA = 180` s; nas execuções
   normais um lote volta em menos de um minuto). São duas camadas: o cliente sai
   com `http_options.timeout`, que derruba a conexão parada e avisa o servidor
   do limite, e uma guarda de relógio (`chamar_com_limite`) garante o corte
   mesmo se o HTTP não cair. A chamada sem resposta, e também o 504, desce para
   o próximo modelo na hora, sem repetir no mesmo.

3. **Prazo da etapa da IA** (`PRAZO_IA = 15` min, até 05/10 eram 25; e nunca além de 45 min do
   início do script, `PRAZO_EXECUCAO`, para caber nos 60 do workflow mesmo com
   coleta lenta). O lote que já não cabe no prazo nem é enviado; espera por
   sobrecarga ou intervalo entre lotes que passaria do prazo é cortado. O que a
   IA não classificou:

   - as publicações das fontes de coleta estruturada (título, data e link já
     separados) seguem pelas regras sem IA ([sugestao-sem-ia.md](sugestao-sem-ia.md))
     e chegam ao portal com Radar quando a regra encontra um;
   - as fontes lidas só como página (pelo Firecrawl) não têm como ser lidas sem
     IA: ficam em `fontes_com_erro_tecnico`, com o motivo.

   **A edição sai sempre.** Vale também quando todos os lotes falham em todos os
   modelos: antes o script parava e mantinha a edição anterior
   (`falha_gemini`); agora a edição sai pelas regras, com o registro de tudo o
   que a IA não classificou.

## Execução #82 (05/10): 29,5 min, e o que mudou depois

A primeira coleta com o DOU levou 29 min 33 s. O DOU ficou em 2 min 34 s
(22 pedidos ao Firecrawl com 6,5 s de pausa entre eles); a etapa da IA, em
**24 min 39 s**, 21 s antes do prazo de 25 min:

| | Tempo | Resultado |
|---|---|---|
| `gemini-3.7-flash` | 16 min 18 s (11 min de espera: 30 + 60 + 120 s por lote) | 14 tentativas, todas 503 |
| `gemini-3.6-flash` | 2 min 3 s | 8 tentativas, todas 503 |
| `gemini-3.5-flash` antes de responder | 1 min 6 s | 503 |
| Respostas (`3.5-flash` e `3.5-flash-lite`) | 4 min 14 s | os 4 lotes |
| Intervalo entre lotes | 1 min | |

A cascata recomeçava do primeiro modelo em cada lote e pagava de novo as três
esperas. O reprocessamento de 01/10 (#77, 18 min sem coleta) teve o mesmo
padrão: 17 min 20 s de IA para 3 lotes.

Mudanças aprovadas:

1. **O modelo que respondeu vale para o resto da execução**
   (`ordem_da_cascata`). Nos lotes seguintes, o primeiro modelo ainda tem uma
   tentativa, sem espera (pode ter voltado; se responder, a cascata inteira
   volta a valer); depois vem o que respondeu, os de baixo dele e, por
   último, os que ele pulou, para nenhum modelo deixar de ser tentado antes
   de o lote falhar. A tentativa única fica marcada com `sondagem` em
   `lotes_gemini[].tentativas`, e o log do passo diz
   "passa a gemini-3.5-flash, que já respondeu nesta execução".
2. **Uma espera só por sobrecarga** no primeiro modelo (`ESPERAS_SOBRECARGA =
   (30,)`), e **teto de 3 min** (`TETO_ESPERA_SOBRECARGA`) somando a espera de
   todos os modelos e lotes. Os outros modelos continuam repetindo uma vez
   depois de 10 s, enquanto o teto deixar.
3. **Prazo da IA de 15 min.** O que não couber segue pelas regras sem IA, como
   antes.

Com as respostas da própria #82, na ordem em que cada modelo as deu, a etapa
da IA cai para **9 min 19 s** e a execução para cerca de **14 min**. Os lotes
3 e 4 iriam ao `3.5-flash-lite`, que respondeu o lote 2, e não ao
`3.5-flash`, que os respondeu na #82: é o preço de não insistir. No pior caso
(nenhum modelo responde), o prazo segura a etapa em 15 min e a execução em
cerca de 20.

## No log (`output/log_execucao.json`)

- `etapa_ia`: `situacao` (`completa`, `parcial` ou `sem_ia`), `prazo_s`,
  `duracao_s`, `tempo_limite_por_chamada_s`, `lotes`, `lotes_classificados`,
  `lotes_fora_do_prazo`, `lotes_que_falharam`, `chamadas_sem_resposta` e
  `fontes_nao_classificadas` (por fonte: `situacao`, `lote` e
  `publicacoes_seguem_pelas_regras`);
- em `lotes_gemini`, cada lote ganha `situacao` e `duracao_s`, e cada tentativa
  ganha `duracao_s`;
- `resultado.etapa_ia` repete a situação;
- no workflow, o aviso "Etapa da IA incompleta" diz quantos lotes ficaram sem IA
  e por quê.

## Ensaio com o dossier de 01/10

`main --reprocessar` com o dossier guardado e um Gemini falso, que devolve a
primeira publicação de cada fonte, sem rede e sem crédito; tempo-limite de 1 s
e prazo curto para o ensaio caber em segundos.

| Cenário | Etapa da IA | Itens na edição | Com Radar | Erro técnico |
|---|---|---|---|---|
| IA responde | completa (3 de 3 lotes) | 42 | 35 | 0 |
| 1º modelo trava sempre | completa, 3 chamadas sem resposta, lotes no 2º modelo | 42 | 35 | 0 |
| Todos os modelos travam | sem_ia, 3 lotes fora do prazo | 42 | 33 pelas regras | 16 fontes registradas; 3 delas (Planalto, Destaques do D.O.U., ONS) só tinham página |

Com a biblioteca `google-genai` de verdade, contra um servidor local que aceita a
conexão e nunca responde: o HTTP cai em `ReadTimeout` no tempo-limite, a guarda
de relógio corta antes quando o limite dela é menor, e o script termina sem
esperar a chamada abandonada.
