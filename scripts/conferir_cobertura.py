"""
Cobertura: quantas publicacoes a fonte realmente tinha e quantas chegaram ao
boletim.json.

Para cada fonte, coleta a pagina oficial de quatro jeitos e compara com o que
a execucao registrou. Responde objetivamente onde a publicacao se perdeu:
na coleta, no corte de caracteres, no only_main_content ou na extracao.

    conteudo principal  = como o pipeline coleta hoje (only_main_content=True)
    pagina inteira      = only_main_content=False
    corte               = quanto o limite de MAX_CHARS descarta
    busca complementar  = o que o fc.search encontra na janela

Nao altera o pipeline: so le a fonte e o boletim.json. Precisa de
FIRECRAWL_API_KEY e respeita o intervalo entre chamadas.

Uso:
    python scripts/conferir_cobertura.py                       # todas as fontes
    python scripts/conferir_cobertura.py --fonte ANEEL ANVISA  # so algumas
    python scripts/conferir_cobertura.py --json cobertura.json
"""

import argparse
import datetime
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))

FONTES = BASE / "fontes.json"
BOLETIM = BASE / "output" / "boletim.json"

INTERVALO = 6.5
MAX_CHARS = 30000
BUSCA_LIMITE = 30

# Casos ja conhecidos, usados como controle de regressao. Se a conferencia
# disser que esta tudo certo nestes pontos, ou o problema foi resolvido ou a
# conferencia esta cega.
CONTROLES = [
    {
        "fonte": "ANEEL | Últimas Notícias",
        "sintoma": "perdeu seis publicacoes reais por corte de conteudo",
        "esperado": "pagina inteira maior que 30.000 chars; publicacoes fora do corte",
    },
    {
        "fonte": "ANVISA | Notícias",
        "sintoma": "nao capturou o cancelamento do registro do Elevidys",
        "esperado": "a publicacao aparece na pagina e nao no boletim.json",
        "termo": "elevidys",
    },
    {
        "fonte": "ANATEL | Notícias",
        "sintoma": "ja retornou entre 1.300 e 1.800 caracteres",
        "esperado": "conteudo principal muito menor que a pagina inteira",
    },
    {
        "fonte": "SUSEP | Notícias",
        "sintoma": "ja retornou entre 1.300 e 1.800 caracteres",
        "esperado": "conteudo principal muito menor que a pagina inteira",
    },
    {
        "fonte": "ANPD | Notícias",
        "sintoma": "ja retornou entre 1.300 e 1.800 caracteres",
        "esperado": "conteudo principal muito menor que a pagina inteira",
    },
]

LINK = re.compile(r"\[([^\]]{8,300})\]\((https?://[^\s)]+)\)")
DATA_BR = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
DATA_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

# Links que toda pagina de orgao publico tem e que nao sao publicacao.
RUIDO = (
    "/acesso-a-informacao", "/canais_atendimento", "/composicao", "/pt-br/acessibilidade",
    "facebook.com", "twitter.com", "x.com/", "instagram.com", "youtube.com",
    "linkedin.com", "whatsapp", "/agenda", "javascript:", "#", "/rss",
    "gov.br/pt-br", "/participamaisbrasil", "/fale-conosco", "/ouvidoria",
)


def normalizar_url(url):
    return str(url or "").split("#")[0].split("?")[0].rstrip("/").lower()


def escopo(url):
    p = urlparse(url)
    partes = [x for x in p.path.split("/") if x]
    if p.netloc.endswith("gov.br") and len(partes) >= 2:
        return p.netloc + "/" + "/".join(partes[:2])
    return p.netloc


def parece_publicacao(url, base):
    """Link que aponta para dentro do escopo da fonte e nao e navegacao."""
    alvo = normalizar_url(url)
    if not alvo or any(r in alvo for r in RUIDO):
        return False
    if escopo(base).split("/")[0] not in alvo:
        return False
    return alvo != normalizar_url(base)


def datas_no_trecho(texto):
    achadas = []
    for dia, mes, ano in DATA_BR.findall(texto):
        try:
            achadas.append(datetime.date(int(ano), int(mes), int(dia)))
        except ValueError:
            pass
    for ano, mes, dia in DATA_ISO.findall(texto):
        try:
            achadas.append(datetime.date(int(ano), int(mes), int(dia)))
        except ValueError:
            pass
    return achadas


def publicacoes_no_markdown(markdown, base, inicio, fim):
    """
    Publicacoes visiveis na listagem, com a data mais proxima do link.

    Heuristica deliberadamente simples: o objetivo nao e extrair perfeitamente,
    e contar. Um numero aproximado de publicacoes reais ja responde se a perda
    esta na coleta ou na extracao.

    O vies e para cima: quando a data nao esta clara, o link pode ser contado
    como se estivesse na janela. Entao a cobertura que este script calcula e
    um piso — se ela ja aparece baixa, a perda e real.
    """
    encontradas = {}
    for achado in LINK.finditer(markdown):
        titulo, url = achado.group(1).strip(), achado.group(2).strip()
        if not parece_publicacao(url, base):
            continue

        # A data costuma estar na mesma linha ou logo abaixo. A janela para
        # no proximo link, para nao herdar a data da publicacao seguinte.
        cauda = markdown[achado.end(): achado.end() + 220]
        proximo = cauda.find("](http")
        if proximo != -1:
            cauda = cauda[:proximo]
        datas = datas_no_trecho(achado.group(0) + cauda)
        na_janela = [d for d in datas if inicio <= d <= fim]

        chave = normalizar_url(url)
        anterior = encontradas.get(chave)
        if anterior and anterior["na_janela"]:
            continue
        encontradas[chave] = {
            "titulo": " ".join(titulo.split())[:200],
            "url": url,
            "datas": sorted({d.isoformat() for d in datas}),
            "na_janela": bool(na_janela),
        }
    return list(encontradas.values())


def coletar(fc, url, principal):
    inicio = time.monotonic()
    resultado = fc.scrape(url, formats=["markdown"], only_main_content=principal)
    return (resultado.markdown or ""), time.monotonic() - inicio


def buscar(fc, url, inicio, fim):
    consulta = (
        f"site:{escopo(url)} after:{inicio.isoformat()} "
        f"before:{(fim + datetime.timedelta(days=1)).isoformat()}"
    )
    resultado = fc.search(consulta, limit=BUSCA_LIMITE)
    achados = []
    for item in getattr(resultado, "web", None) or []:
        endereco = str(getattr(item, "url", "") or "").strip()
        if endereco and normalizar_url(endereco) != normalizar_url(url):
            achados.append(
                {
                    "titulo": str(getattr(item, "title", "") or "").strip(),
                    "url": endereco,
                }
            )
    return achados


def itens_do_boletim(fonte):
    if not BOLETIM.exists():
        return [], ""
    dados = json.loads(BOLETIM.read_text(encoding="utf-8"))
    itens = [i for i in dados.get("itens") or [] if i.get("fonte") == fonte]
    return itens, dados.get("data_execucao", "")


def conferir(fc, fonte, inicio, fim):
    url = fonte["url"]
    nome = fonte["fonte"]
    relato = {"fonte": nome, "url": url}

    try:
        principal, _ = coletar(fc, url, True)
    except Exception as erro:
        relato["erro"] = " ".join(str(erro).split())[:300]
        return relato

    time.sleep(INTERVALO)
    try:
        inteira, _ = coletar(fc, url, False)
    except Exception as erro:
        inteira = ""
        relato["erro_pagina_inteira"] = " ".join(str(erro).split())[:200]

    time.sleep(INTERVALO)
    try:
        achadas_busca = buscar(fc, url, inicio, fim)
    except Exception as erro:
        achadas_busca = []
        relato["erro_busca"] = " ".join(str(erro).split())[:200]

    pub_principal = publicacoes_no_markdown(principal, url, inicio, fim)
    pub_inteira = publicacoes_no_markdown(inteira, url, inicio, fim) if inteira else []
    pub_cortada = publicacoes_no_markdown(principal[:MAX_CHARS], url, inicio, fim)

    itens, data_execucao = itens_do_boletim(nome)
    urls_boletim = {normalizar_url(i.get("url")) for i in itens}

    referencia = pub_inteira or pub_principal
    na_janela = [p for p in referencia if p["na_janela"]]
    faltando = [
        p for p in na_janela if normalizar_url(p["url"]) not in urls_boletim
    ]

    relato.update(
        {
            "data_execucao_comparada": data_execucao,
            "chars_conteudo_principal": len(principal),
            "chars_pagina_inteira": len(inteira),
            "chars_perdidos_no_corte": max(0, len(principal) - MAX_CHARS),
            "publicacoes_conteudo_principal": len(pub_principal),
            "publicacoes_pagina_inteira": len(pub_inteira),
            "publicacoes_depois_do_corte": len(pub_cortada),
            "perdidas_pelo_corte": max(0, len(pub_principal) - len(pub_cortada)),
            "perdidas_pelo_only_main_content": max(
                0, len(pub_inteira) - len(pub_principal)
            ),
            "publicacoes_na_janela": len(na_janela),
            "chegaram_ao_boletim": len(itens),
            "faltando_no_boletim": len(faltando),
            "achadas_pela_busca": len(achadas_busca),
            "exemplos_faltando": [
                {"titulo": p["titulo"], "url": p["url"], "datas": p["datas"]}
                for p in faltando[:8]
            ],
        }
    )
    return relato


def conferir_controles(relatos):
    """Compara o resultado com os casos ja conhecidos."""
    por_fonte = {r["fonte"]: r for r in relatos}
    linhas = []
    for controle in CONTROLES:
        relato = por_fonte.get(controle["fonte"])
        if not relato:
            linhas.append((controle["fonte"], "nao conferida", controle["sintoma"]))
            continue
        if relato.get("erro"):
            linhas.append((controle["fonte"], "erro na coleta", relato["erro"][:60]))
            continue

        if controle.get("termo"):
            termo = controle["termo"].lower()
            achou = any(
                termo in p["titulo"].lower() for p in relato.get("exemplos_faltando", [])
            )
            situacao = "REPRODUZ" if achou else "nao reproduz"
            detalhe = f"{relato['faltando_no_boletim']} publicacao(oes) da janela fora do boletim"
        elif "corte" in controle["sintoma"]:
            situacao = "REPRODUZ" if relato["perdidas_pelo_corte"] else "nao reproduz"
            detalhe = (
                f"{relato['perdidas_pelo_corte']} publicacao(oes) apos o corte; "
                f"{relato['chars_perdidos_no_corte']} chars descartados"
            )
        else:
            pequeno = relato["chars_conteudo_principal"] < 5000
            situacao = "REPRODUZ" if pequeno else "nao reproduz"
            detalhe = (
                f"conteudo principal {relato['chars_conteudo_principal']} chars; "
                f"pagina inteira {relato['chars_pagina_inteira']} chars"
            )
        linhas.append((controle["fonte"], situacao, detalhe))
    return linhas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fonte", nargs="*", default=[])
    parser.add_argument("--json", default="")
    parser.add_argument("--dias", type=int, default=1)
    parser.add_argument(
        "--testar-url",
        nargs="*",
        default=[],
        help="URLs candidatas a testar, sem comparar com o boletim. Serve "
        "para conferir se uma fonte quebrada tem endereco novo.",
    )
    args = parser.parse_args()

    if not os.getenv("FIRECRAWL_API_KEY"):
        raise SystemExit("FIRECRAWL_API_KEY e obrigatoria.")

    from firecrawl import Firecrawl

    agora = datetime.datetime.now(ZoneInfo("America/Sao_Paulo"))
    fim = agora.date()
    inicio = fim - datetime.timedelta(days=args.dias)
    fc = Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"])

    if args.testar_url:
        print("TESTE DE URLS CANDIDATAS")
        for indice, url in enumerate(args.testar_url, 1):
            try:
                markdown, _ = coletar(fc, url, True)
                marcador = ""
                minusculo = markdown.lower()
                for termo in ("estamos em manuten", "conte\u00fado restrito", "conteudo restrito", "access denied", "not found", "internal server error"):
                    if termo in minusculo:
                        marcador = termo
                        break
                publicacoes = publicacoes_no_markdown(markdown, url, inicio, fim)
                print(f"  {url}")
                print(
                    f"    {len(markdown)} chars | {len(publicacoes)} link(s) de publicacao"
                    + (f" | PAGINA DE ERRO: {marcador}" if marcador else "")
                )
                for pub in publicacoes[:5]:
                    print(f"      - {pub['titulo'][:70]}")
            except Exception as erro:
                print(f"  {url}\n    erro: {' '.join(str(erro).split())[:160]}")
            if indice < len(args.testar_url):
                time.sleep(INTERVALO)
        print()
        if not args.fonte:
            return

    fontes = json.loads(FONTES.read_text(encoding="utf-8"))
    fontes = [f for f in fontes if f.get("ativo", True) and not f.get("suspenso")]
    if args.fonte:
        alvos = [a.lower() for a in args.fonte]
        fontes = [f for f in fontes if any(a in f["fonte"].lower() for a in alvos)]

    if not fontes:
        raise SystemExit("Nenhuma fonte selecionada.")

    print(f"Janela: {inicio.isoformat()} a {fim.isoformat()} | {len(fontes)} fonte(s)")
    print()

    relatos = []
    for indice, fonte in enumerate(fontes, 1):
        print(f"[{indice}/{len(fontes)}] {fonte['fonte']}")
        relato = conferir(fc, fonte, inicio, fim)
        relatos.append(relato)
        if relato.get("erro"):
            print(f"    erro: {relato['erro'][:90]}")
        else:
            print(
                f"    chars: {relato['chars_conteudo_principal']} principal / "
                f"{relato['chars_pagina_inteira']} inteira"
            )
            print(
                f"    publicacoes: {relato['publicacoes_na_janela']} na janela / "
                f"{relato['chegaram_ao_boletim']} no boletim / "
                f"{relato['faltando_no_boletim']} faltando"
            )
            if relato["perdidas_pelo_corte"]:
                print(f"    perdidas pelo corte de 30.000: {relato['perdidas_pelo_corte']}")
            if relato["perdidas_pelo_only_main_content"]:
                print(
                    "    perdidas pelo only_main_content: "
                    f"{relato['perdidas_pelo_only_main_content']}"
                )
        if indice < len(fontes):
            time.sleep(INTERVALO)

    print()
    print("=" * 78)
    print("RESUMO")
    reais = sum(r.get("publicacoes_na_janela", 0) for r in relatos)
    chegaram = sum(r.get("chegaram_ao_boletim", 0) for r in relatos)
    print(f"  publicacoes na janela, vistas na fonte: {reais}")
    print(f"  publicacoes no boletim.json:            {chegaram}")
    if reais:
        print(f"  cobertura:                              {100 * chegaram // reais}%")

    print()
    print("CONTROLES DE REGRESSAO")
    for fonte, situacao, detalhe in conferir_controles(relatos):
        print(f"  {situacao:<14} {fonte[:34]:<34} {detalhe}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(relatos, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print()
        print(f"Detalhe gravado em {args.json}")


if __name__ == "__main__":
    main()
