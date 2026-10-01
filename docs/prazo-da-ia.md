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
   Etapa da IA: 16 fonte(s) em lotes de 6; prazo de 25 min, até 180 s por chamada.
   Lote 1/3 da IA: 6 fonte(s), 25 min até o prazo
     gemini-3.7-flash: sem resposta no tempo-limite em 180 s; passa ao próximo modelo
     gemini-3.6-flash: respondeu em 41 s
   ```

2. **Tempo-limite de cada chamada** (`TEMPO_CHAMADA = 180` s; nas execuções
   normais um lote volta em menos de um minuto). São duas camadas: o cliente sai
   com `http_options.timeout`, que derruba a conexão parada e avisa o servidor
   do limite, e uma guarda de relógio (`chamar_com_limite`) garante o corte
   mesmo se o HTTP não cair. A chamada sem resposta, e também o 504, desce para
   o próximo modelo na hora, sem repetir no mesmo.

3. **Prazo da etapa da IA** (`PRAZO_IA = 25` min, e nunca além de 45 min do
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
