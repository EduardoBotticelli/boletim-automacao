"""
Compara as duas maneiras de separar as publicacoes de uma listagem, sem o
Gemini no meio:

  1. LEITURA NOSSA  - a mesma logica do conferir_cobertura.py, aplicada ao
                      markdown que o Firecrawl ja devolve hoje;
  2. FIRECRAWL JSON - o modo de extracao estruturada do proprio Firecrawl,
                      que recebe um schema e devolve as publicacoes separadas.

Mede as duas na mesma pagina, no mesmo momento, para a comparacao ser justa.
Nao altera o pipeline: e so medicao.

Importante sobre a opcao 2: o formato json do Firecrawl aceita 'prompt' e
'schema' e tem opcao 'check_prompt_injection'. E uma interface de modelo de
linguagem. Ela nao tira a IA da extracao — troca o Gemini, que hoje cai por
cota, pela IA do Firecrawl, que e cobrada em credito.

Uso:
    python scripts/comparar_extracao.py --fonte ANEEL ANVISA ANATEL
"""

import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))

import conferir_cobertura as cc  # noqa: E402

FONTES = BASE / "fontes.json"
INTERVALO = 6.5

ESQUEMA = {
    "type": "object",
    "properties": {
        "publicacoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "titulo": {"type": "string"},
                    "url": {"type": "string"},
                    "data_publicacao": {"type": "string"},
                    "descricao": {"type": "string"},
                },
                "required": ["titulo"],
            },
        }
    },
    "required": ["publicacoes"],
}

INSTRUCAO = (
    "Liste as publicacoes da listagem desta pagina. Para cada uma, extraia o "
    "titulo exato, a URL da publicacao, a data de publicacao no formato "
    "AAAA-MM-DD e a descricao ou chamada, quando houver. Nao invente data nem "
    "descricao: deixe vazio se a pagina nao mostrar. Ignore menu, rodape, "
    "banner e links de navegacao."
)


def dentro(valor, inicio, fim):
    try:
        data = datetime.date.fromisoformat(str(valor or "")[:10])
    except ValueError:
        return False
    return inicio <= data <= fim


def pela_leitura_nossa(fc, fonte, inicio, fim):
    resultado = fc.scrape(
        fonte["url"],
        formats=["markdown"],
        only_main_content=not fonte.get("pagina_inteira"),
    )
    markdown = resultado.markdown or ""
    publicacoes = cc.publicacoes_no_markdown(markdown, fonte["url"], inicio, fim)
    return {
        "chars": len(markdown),
        "publicacoes": len(publicacoes),
        "com_data": len([p for p in publicacoes if p["datas"]]),
        "na_janela": len([p for p in publicacoes if p["na_janela"]]),
        "exemplos": [p["titulo"][:70] for p in publicacoes if p["na_janela"]][:4],
    }


def pelo_firecrawl(fc, fonte, inicio, fim):
    resultado = fc.scrape(
        fonte["url"],
        formats=[{"type": "json", "prompt": INSTRUCAO, "schema": ESQUEMA}],
        only_main_content=not fonte.get("pagina_inteira"),
    )
    dados = getattr(resultado, "json", None) or {}
    if isinstance(dados, str):
        dados = json.loads(dados)
    publicacoes = dados.get("publicacoes") or []
    na_janela = [p for p in publicacoes if dentro(p.get("data_publicacao"), inicio, fim)]
    return {
        "publicacoes": len(publicacoes),
        "com_data": len([p for p in publicacoes if str(p.get("data_publicacao") or "").strip()]),
        "com_descricao": len([p for p in publicacoes if str(p.get("descricao") or "").strip()]),
        "na_janela": len(na_janela),
        "exemplos": [str(p.get("titulo", ""))[:70] for p in na_janela][:4],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fonte", nargs="*", default=[])
    parser.add_argument("--dias", type=int, default=1)
    args = parser.parse_args()

    if not os.getenv("FIRECRAWL_API_KEY"):
        raise SystemExit("FIRECRAWL_API_KEY e obrigatoria.")

    from firecrawl import Firecrawl

    fim = datetime.datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    inicio = fim - datetime.timedelta(days=args.dias)

    fontes = json.loads(FONTES.read_text(encoding="utf-8"))
    fontes = [f for f in fontes if f.get("ativo", True) and not f.get("suspenso")]
    if args.fonte:
        alvos = [a.lower() for a in args.fonte]
        fontes = [f for f in fontes if any(a in f["fonte"].lower() for a in alvos)]
    if not fontes:
        raise SystemExit("Nenhuma fonte selecionada.")

    fc = Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"])
    print(f"Janela: {inicio.isoformat()} a {fim.isoformat()} | {len(fontes)} fonte(s)")
    print()

    somas = {"leitura": 0, "firecrawl": 0}
    chamadas = {"leitura": 0, "firecrawl": 0}

    for indice, fonte in enumerate(fontes, 1):
        print(f"[{indice}/{len(fontes)}] {fonte['fonte']}")

        try:
            nossa = pela_leitura_nossa(fc, fonte, inicio, fim)
            chamadas["leitura"] += 1
            print(
                f"    leitura nossa : {nossa['publicacoes']:>3} publicacoes | "
                f"{nossa['com_data']:>3} com data | {nossa['na_janela']:>3} na janela"
            )
            for titulo in nossa["exemplos"]:
                print(f"        - {titulo}")
            somas["leitura"] += nossa["na_janela"]
        except Exception as erro:
            print(f"    leitura nossa : ERRO {' '.join(str(erro).split())[:110]}")

        time.sleep(INTERVALO)

        try:
            deles = pelo_firecrawl(fc, fonte, inicio, fim)
            chamadas["firecrawl"] += 1
            print(
                f"    firecrawl json: {deles['publicacoes']:>3} publicacoes | "
                f"{deles['com_data']:>3} com data | {deles['na_janela']:>3} na janela | "
                f"{deles['com_descricao']:>3} com descricao"
            )
            for titulo in deles["exemplos"]:
                print(f"        - {titulo}")
            somas["firecrawl"] += deles["na_janela"]
        except Exception as erro:
            print(f"    firecrawl json: ERRO {' '.join(str(erro).split())[:110]}")

        if indice < len(fontes):
            time.sleep(INTERVALO)

    print()
    print("=" * 72)
    print("TOTAL DE PUBLICACOES NA JANELA")
    print(f"  leitura nossa : {somas['leitura']:>4}   ({chamadas['leitura']} scrape(s))")
    print(f"  firecrawl json: {somas['firecrawl']:>4}   ({chamadas['firecrawl']} scrape(s) com extracao)")


if __name__ == "__main__":
    main()
