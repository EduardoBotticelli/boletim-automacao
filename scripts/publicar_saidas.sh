#!/usr/bin/env bash
# Commita os arquivos indicados e os envia ao ramo da execucao.
#
# Uso: scripts/publicar_saidas.sh "<mensagem do commit>" <ramo> <caminho>...
#
# So entram no commit os caminhos passados que existirem. O resto da pasta
# de saida pode estar modificado e fora deste commit: o dossier e guardado
# antes do boletim.json, que so vai no commit oficial. Por isso o pull usa
# --autostash: guarda o que ficou fora, traz o que chegou no ramo durante a
# execucao (as decisoes do portal, um merge) e devolve o que foi guardado.
# Sem ele, 'git pull --rebase' se recusa a rodar com mudanca nao commitada,
# e foi isso que travou a coleta de 01/10 na etapa do dossier.
#
# Se o push for recusado porque o ramo andou de novo entre o pull e o push,
# tenta outra vez (PUBLICAR_TENTATIVAS, padrao 3). Conflito de verdade
# (o mesmo arquivo mudou aqui e no ramo) nao e resolvido aqui: o script para
# com erro, sem deixar rebase pela metade.
set -euo pipefail

if [ "$#" -lt 3 ]; then
  echo "Uso: $0 \"<mensagem>\" <ramo> <caminho>..." >&2
  exit 2
fi

mensagem="$1"
ramo="$2"
shift 2
tentativas="${PUBLICAR_TENTATIVAS:-3}"
espera="${PUBLICAR_ESPERA:-5}"

git config user.name >/dev/null || git config user.name "github-actions[bot]"
git config user.email >/dev/null || git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

caminhos=()
for caminho in "$@"; do
  if [ -e "$caminho" ]; then
    caminhos+=("$caminho")
  fi
done
if [ "${#caminhos[@]}" -eq 0 ]; then
  echo "Nada a publicar: nenhum dos caminhos existe."
  exit 0
fi

git add -f -- "${caminhos[@]}"
if git diff --staged --quiet; then
  echo "Nada a publicar: sem mudanca em ${caminhos[*]}."
  exit 0
fi
git commit -q -m "$mensagem"

for tentativa in $(seq 1 "$tentativas"); do
  if ! git pull -q --rebase --autostash origin "$ramo"; then
    git rebase --abort 2>/dev/null || true
    echo "::error title=Publicacao das saidas::O ramo $ramo mudou os mesmos arquivos durante a execucao; o commit \"$mensagem\" nao foi enviado."
    exit 1
  fi
  if [ -n "$(git diff --name-only --diff-filter=U)" ]; then
    echo "::error title=Publicacao das saidas::As mudancas guardadas pelo --autostash conflitaram com o ramo $ramo; elas continuam no git stash."
    exit 1
  fi
  if git push -q origin "HEAD:$ramo"; then
    echo "Publicado em $ramo: $mensagem"
    exit 0
  fi
  echo "Push recusado (tentativa $tentativa de $tentativas); trazendo o ramo de novo."
  sleep $((espera * tentativa))
done

echo "::error title=Publicacao das saidas::O push para $ramo falhou $tentativas vezes; o commit \"$mensagem\" nao foi enviado."
exit 1
