"""
Funil de perda das execucoes do pipeline, etapa por etapa.

Le os artefatos que cada execucao ja commita (output/boletim.json e
output/log_execucao.json), direto do historico do git, e mostra onde as
publicacoes somem entre a coleta e a publicacao.

Nao acessa rede, nao precisa de chave e nao altera nada: e so leitura.

Uso:
    python scripts/diagnostico_funil.py                # ultimas 6 execucoes
    python scripts/diagnostico_funil.py --execucoes 12
    python scripts/diagnostico_funil.py --fontes       # detalhe por fonte
"""

import argparse
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
BOLETIM = "output/boletim.json"
LOG = "output/log_execucao.json"
DECISOES = "output/decisoes_alice.json"


def git(*args):
    return subprocess.run(
        ["git", "-C", str(BASE), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def commits(caminho, limite):
    saida = git("log", "--format=%H", "-n", str(limite), "--", caminho)
    return [linha for linha in saida.stdout.split() if linha]


def ler(commit, caminho):
    saida = git("show", f"{commit}:{caminho}")
    if saida.returncode != 0:
        return None
    try:
        return json.loads(saida.stdout)
    except json.JSONDecodeError:
        return None


def execucoes(limite):
    """As execucoes mais recentes, com boletim e log da mesma revisao."""
    encontradas = []
    for commit in commits(BOLETIM, limite * 3):
        boletim = ler(commit, BOLETIM)
        if not boletim or not isinstance(boletim.get("itens"), list):
            continue
        log = ler(commit, LOG) or {}
        if log.get("data_execucao") != boletim.get("data_execucao"):
            # Commit de curadoria, que reescreve o boletim sem reexecutar a
            # coleta: o log daquele commit e de outra execucao.
            log = {}
        encontradas.append((commit, boletim, log))
        if len(encontradas) >= limite:
            break
    return encontradas


def pares_por_etapa(boletim):
    """
    Conta pares (publicacao x Radar) em cada etapa de filtro.

    O par e a unidade certa: a mesma publicacao pode entrar em varios
    Radares, e cada filtro age por Radar, nao por publicacao.
    """
    itens = boletim.get("itens") or []
    sugeridos = filtro1 = filtro2 = publicados = 0
    institucional = orfaos = sem_data = 0

    for item in itens:
        sugeridos += len([s for s in item.get("boletins_confirmados") or [] if s])
        publicados += len(item.get("boletins") or [])

        if not item.get("boletins"):
            orfaos += 1
        if item.get("exclusao_editorial_automatica"):
            institucional += 1
        if not str(item.get("data_publicacao") or "").strip():
            sem_data += 1

        for rejeicao in item.get("boletins_rejeitados") or []:
            if not isinstance(rejeicao, dict):
                continue
            if str(rejeicao.get("motivo", "")).startswith("Filtro 1:"):
                filtro1 += 1
            else:
                filtro2 += 1

    return {
        "itens": len(itens),
        "pares_sugeridos": sugeridos,
        "pares_filtro1": filtro1,
        "pares_filtro2": filtro2,
        "pares_publicados": publicados,
        "itens_institucionais": institucional,
        "itens_orfaos": orfaos,
        "itens_sem_data": sem_data,
    }


def coleta(log):
    """O que a coleta entregou: tamanho, corte e busca complementar."""
    processadas = log.get("fontes_processadas") or []
    chars = sum(x.get("tamanho_chars", 0) for x in processadas)
    truncadas = [x for x in processadas if x.get("conteudo_truncado")]
    buscas = [x for x in processadas if x.get("busca_complementar_executada")]

    # A busca complementar e concatenada ao conteudo e o resultado e cortado
    # em MAX_CHARS. Quando o conteudo ja chegou no limite, o que a busca
    # encontrou nao entra no dossier.
    localizadas_uteis = sum(
        x.get("publicacoes_localizadas", 0)
        for x in buscas
        if not x.get("conteudo_truncado")
    )
    localizadas_perdidas = sum(
        x.get("publicacoes_localizadas", 0)
        for x in buscas
        if x.get("conteudo_truncado")
    )

    return {
        "fontes": len(processadas),
        "fontes_ok": len([x for x in processadas if x.get("status") == "ok"]),
        "chars_dossier": chars,
        "fontes_truncadas": len(truncadas),
        "buscas_executadas": len(buscas),
        "localizadas_no_dossier": localizadas_uteis,
        "localizadas_descartadas": localizadas_perdidas,
    }


def curadoria(commit_boletim, data_execucao):
    """
    O que a curadoria fez com os itens daquela execucao.

    A decisao e commitada depois do boletim, entao procuramos pela
    data_execucao em vez de pelo commit.
    """
    for commit in commits(DECISOES, 40):
        decisoes = ler(commit, DECISOES)
        if not isinstance(decisoes, dict):
            continue
        if decisoes.get("data_execucao") != data_execucao:
            continue
        lista = decisoes.get("decisoes") or []
        aprovados = [d for d in lista if d.get("status") == "aprovado"]
        pares = sum(
            len(d.get("radares_finais") or d.get("boletins") or [])
            for d in aprovados
        )
        return {
            "decididos": len(lista),
            "aprovados": len(aprovados),
            "rejeitados": len(lista) - len(aprovados),
            "pares_publicados": pares,
        }
    return None


def linha_funil(rotulo, valor, referencia):
    proporcao = "" if not referencia else f"  ({100 * valor // referencia}%)"
    return f"  {rotulo:<44}{valor:>8}{proporcao}"


def relatorio(limite, detalhe_fontes):
    dados = execucoes(limite)
    if not dados:
        print("Nenhuma execucao encontrada no historico.")
        return

    por_fonte = defaultdict(
        lambda: {
            "execucoes": 0,
            "chars": [],
            "truncadas": 0,
            "buscas": 0,
            "localizadas": 0,
            "itens": 0,
            "status": Counter(),
        }
    )

    totais = Counter()

    for commit, boletim, log in reversed(dados):
        data = boletim.get("data_execucao", "?")
        modelo = boletim.get("modelo_gemini_utilizado", "?")
        etapas = pares_por_etapa(boletim)
        origem = coleta(log) if log else {}
        final = curadoria(commit, data)

        print("=" * 72)
        print(f"{data}   modelo: {modelo}")
        if log:
            tentativas = log.get("tentativas_gemini") or []
            falhas = [t for t in tentativas if t.get("status") != "sucesso"]
            if falhas:
                print(
                    f"  cascata: {len(falhas)} tentativa(s) falharam antes de "
                    f"{modelo}"
                )

        if origem:
            print(linha_funil("fontes coletadas com sucesso", origem["fontes_ok"], origem["fontes"]))
            print(linha_funil("caracteres entregues ao Gemini", origem["chars_dossier"], 0))
            print(linha_funil("fontes cortadas no limite de caracteres", origem["fontes_truncadas"], origem["fontes"]))
            print(linha_funil("publicacoes achadas pela busca -> dossier", origem["localizadas_no_dossier"], 0))
            print(linha_funil("publicacoes achadas pela busca -> descartadas", origem["localizadas_descartadas"], 0))

        print(linha_funil("publicacoes extraidas pelo Gemini", etapas["itens"], 0))
        print(linha_funil("  sem data reconhecida", etapas["itens_sem_data"], etapas["itens"]))
        print(linha_funil("  excluidas por conteudo institucional", etapas["itens_institucionais"], etapas["itens"]))
        print(linha_funil("  sem nenhum Radar no fim (orfas)", etapas["itens_orfaos"], etapas["itens"]))
        print(linha_funil("pares (publicacao x Radar) sugeridos", etapas["pares_sugeridos"], 0))
        print(linha_funil("  barrados pelo Filtro 1 (matriz)", etapas["pares_filtro1"], 0))
        print(linha_funil("  recusados pelo Filtro 2 (IA)", etapas["pares_filtro2"], 0))
        print(linha_funil("pares que chegaram ao portal", etapas["pares_publicados"], 0))

        if final:
            print(linha_funil("  rejeitados na curadoria", final["rejeitados"], final["decididos"]))
            print(linha_funil("pares publicados nos Radares", final["pares_publicados"], 0))
        else:
            print("  (sem decisao de curadoria registrada para esta data)")

        for chave, valor in etapas.items():
            totais[chave] += valor
        for chave, valor in origem.items():
            totais[chave] += valor

        if log:
            val = {x["fonte"]: x for x in boletim.get("validacao_fontes") or []}
            for processada in log.get("fontes_processadas") or []:
                nome = processada["fonte"]
                acumulado = por_fonte[nome]
                acumulado["execucoes"] += 1
                acumulado["chars"].append(processada.get("tamanho_chars", 0))
                acumulado["truncadas"] += 1 if processada.get("conteudo_truncado") else 0
                acumulado["buscas"] += 1 if processada.get("busca_complementar_executada") else 0
                acumulado["localizadas"] += processada.get("publicacoes_localizadas", 0)
                acumulado["itens"] += val.get(nome, {}).get("publicacoes_aprovadas", 0)
                acumulado["status"][processada.get("status", "?")] += 1

    print("=" * 72)
    print(f"SOMA DE {len(dados)} EXECUCOES")
    print(linha_funil("caracteres entregues ao Gemini", totais["chars_dossier"], 0))
    print(linha_funil("publicacoes achadas pela busca -> dossier", totais["localizadas_no_dossier"], 0))
    print(linha_funil("publicacoes achadas pela busca -> descartadas", totais["localizadas_descartadas"], 0))
    print(linha_funil("publicacoes extraidas pelo Gemini", totais["itens"], 0))
    print(linha_funil("pares barrados pelo Filtro 1", totais["pares_filtro1"], 0))
    print(linha_funil("pares recusados pelo Filtro 2", totais["pares_filtro2"], 0))
    print(linha_funil("pares que chegaram ao portal", totais["pares_publicados"], 0))

    if not detalhe_fontes:
        print()
        print("Use --fontes para o detalhe por fonte.")
        return

    print()
    print("=" * 96)
    print("DETALHE POR FONTE (soma das execucoes lidas)")
    print(f"{'FONTE':<42}{'CHARS MED':>10}{'CORTES':>7}{'BUSCAS':>7}{'ACHADAS':>8}{'ITENS':>6}  PROBLEMAS")
    print("-" * 96)
    for nome, dado in sorted(por_fonte.items(), key=lambda kv: kv[1]["itens"]):
        media = sum(dado["chars"]) // max(len(dado["chars"]), 1)
        problemas = ",".join(
            f"{k}:{v}" for k, v in dado["status"].items() if k != "ok"
        )
        print(
            f"{nome[:42]:<42}{media:>10}{dado['truncadas']:>7}{dado['buscas']:>7}"
            f"{dado['localizadas']:>8}{dado['itens']:>6}  {problemas}"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execucoes", type=int, default=6)
    parser.add_argument("--fontes", action="store_true")
    args = parser.parse_args()
    relatorio(args.execucoes, args.fontes)


if __name__ == "__main__":
    main()
