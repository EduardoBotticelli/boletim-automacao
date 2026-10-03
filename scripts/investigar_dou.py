"""
Investiga se a leitura do jornal do DOU (in.gov.br/leiturajornal), baixada
pelo Firecrawl em HTML bruto, traz a lista completa de atos da edicao.

O in.gov.br derruba a conexao vinda do runner do GitHub, e o INLABS esta fora
do ar; o Firecrawl ja le o in.gov.br nos "Destaques do D.O.U.". Para cada
secao pedida, o script:

1. baixa a leitura do jornal com formats=["rawHtml"];
2. procura o JSON embutido (<script id="params">) e conta os atos, com
   titulo, tipo, orgao e endereco;
3. baixa a busca do proprio in.gov.br para a mesma data e secao, que diz o
   total de resultados da edicao, para comparar;
4. abre um ato de exemplo (CADE, MEC ou MDIC) e mede o texto que vem dele.

Nao altera o pipeline. Grava o HTML bruto e um resumo em
output/investigacao_dou, e registra os creditos gastos.

Uso:
    python scripts/investigar_dou.py --data 02-10-2026 --secoes dou1 dou3
"""

import argparse
import datetime
import html
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SAIDA = BASE / "output" / "investigacao_dou"
LEITURA = "https://www.in.gov.br/leiturajornal?secao={secao}&data={data}"
BUSCA = ("https://www.in.gov.br/consulta/-/buscar/dou?q=*&s={secao}&exactDate=personalizado"
         "&sortType=0&delta=20&publishFrom={data}&publishTo={data}")
# A busca do in.gov.br chama as secoes de do1, do2, do3.
SECAO_BUSCA = {"dou1": "do1", "dou2": "do2", "dou3": "do3", "do1": "do1", "do3": "do3", "dou1e": "do1e", "do1e": "do1e"}
ORGAOS_EXEMPLO = ("Conselho Administrativo de Defesa Econômica", "Ministério da Educação",
                  "Ministério do Desenvolvimento, Indústria, Comércio e Serviços")
# Atos abertos com --varios-atos: um de cada, para conferir a leitura do texto
# em orgaos e tipos diferentes. (secao, trecho do orgao, trecho do titulo)
VARIOS_ATOS = (
    ("dou1", "Conselho Administrativo de Defesa Econômica", ""),
    ("dou1", "Ministério da Educação", "Portaria"),
    ("dou1", "Ministério do Desenvolvimento, Indústria, Comércio e Serviços", ""),
    ("dou1", "Secretaria Especial da Receita Federal", ""),
    ("dou1", "Comissão de Valores Mobiliários", ""),
    ("dou1", "Instituto Nacional da Propriedade Industrial", ""),
    ("dou3", "Conselho Administrativo de Defesa Econômica", ""),
    ("dou3", "Ministério da Educação", "Mais Médicos"),
)
# Campos do JSON embutido que valem guardar para os testes.
CAMPOS_GUARDADOS = ("pubName", "urlTitle", "numberPage", "subTitulo", "titulo", "title", "pubDate", "content",
                    "editionNumber", "hierarchyLevelSize", "artType", "pubOrder", "hierarchyStr", "hierarchyList")
PAUSA = 7


def json_embutido(texto):
    achado = re.search(r'<script[^>]*id="params"[^>]*>(.*?)</script>', texto, re.S)
    if not achado:
        return None
    try:
        return json.loads(achado.group(1))
    except json.JSONDecodeError:
        return json.loads(html.unescape(achado.group(1)))


def texto_limpo(fragmento):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragmento or "")).split())


def total_da_busca(texto):
    """O total que a busca do in.gov.br mostra, onde quer que ele esteja."""
    achados = {}
    for rotulo, padrao in (
        ("texto_resultados", r"([\d\.]+)\s+resultados?"),
        ("json_totalHits", r'"totalHits"\s*:\s*(\d+)'),
        ("json_total", r'"total"\s*:\s*(\d+)'),
        ("json_numberOfResults", r'"numberOfResults"\s*:\s*(\d+)'),
    ):
        valores = [int(v.replace(".", "")) for v in re.findall(padrao, texto)]
        if valores:
            achados[rotulo] = sorted(set(valores))
    return achados


class Coletor:
    def __init__(self):
        from firecrawl import Firecrawl

        self.fc = Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"])
        self.creditos = 0
        self.chamadas = []

    def baixar(self, url, formatos=("rawHtml",)):
        if self.chamadas:
            time.sleep(PAUSA)
        comeco = time.monotonic()
        doc = self.fc.scrape(url, formats=list(formatos), only_main_content=False)
        meta = getattr(doc, "metadata", None)
        creditos = getattr(meta, "credits_used", None)
        self.creditos += creditos if isinstance(creditos, int) else 1
        registro = {
            "url": url, "status_http": getattr(meta, "status_code", None), "creditos": creditos,
            "cache": getattr(meta, "cache_state", None), "proxy": getattr(meta, "proxy_used", None),
            "segundos": round(time.monotonic() - comeco, 1),
            "bytes_html": len(getattr(doc, "raw_html", "") or ""),
        }
        self.chamadas.append(registro)
        print(f"  {url}: HTTP {registro['status_http']}, {registro['bytes_html']} bytes, {creditos} crédito(s)")
        return doc, registro


def resumir_atos(dados):
    atos = dados.get("jsonArray") or []
    chaves = Counter(k for a in atos for k in a)
    tipos = Counter(a.get("artType", "") for a in atos)
    orgaos = Counter((a.get("hierarchyStr") or "").split("/")[0] for a in atos)
    conteudo = sorted(len(texto_limpo(a.get("content"))) for a in atos)
    return {
        "chaves_do_json": sorted(dados.keys()),
        "atos": len(atos),
        "campos_por_ato": dict(chaves.most_common()),
        "sem_titulo": sum(not (a.get("title") or a.get("titulo")) for a in atos),
        "sem_tipo": sum(not a.get("artType") for a in atos),
        "sem_orgao": sum(not a.get("hierarchyStr") for a in atos),
        "sem_endereco": sum(not a.get("urlTitle") for a in atos),
        "tipos": dict(tipos.most_common(25)),
        "orgaos_de_primeiro_nivel": dict(orgaos.most_common(60)),
        "edicoes": dict(Counter(str(a.get("editionNumber", "")) for a in atos)),
        "pubName": dict(Counter(a.get("pubName", "") for a in atos)),
        "paginas": [min((int(re.sub(r"\D", "", str(a.get("numberPage") or 0)) or 0) for a in atos), default=0),
                    max((int(re.sub(r"\D", "", str(a.get("numberPage") or 0)) or 0) for a in atos), default=0)],
        "tamanho_do_content": {"min": conteudo[0] if conteudo else 0, "mediana": conteudo[len(conteudo) // 2] if conteudo else 0,
                               "max": conteudo[-1] if conteudo else 0},
        "exemplos": atos[:3],
    }


def escolher_exemplo(atos):
    for orgao in ORGAOS_EXEMPLO:
        for ato in atos:
            if orgao in (ato.get("hierarchyStr") or "") and ato.get("urlTitle"):
                return ato
    return next((a for a in atos if a.get("urlTitle")), None)


def ler_ato(texto):
    """O texto do ato na pagina dele: o bloco texto-dou do in.gov.br."""
    achado = re.search(r'<div[^>]*class="[^"]*texto-dou[^"]*"[^>]*>(.*?)</div>\s*(?:<div|<p class="dou-assina|</article|<!--)', texto, re.S)
    bloco = achado.group(1) if achado else ""
    return {
        "achou_texto_dou": bool(achado),
        "texto": texto_limpo(bloco)[:4000],
        "caracteres": len(texto_limpo(bloco)),
        "identifica": texto_limpo((re.search(r'<p[^>]*class="identifica"[^>]*>(.*?)</p>', texto, re.S) or [None, ""])[1]),
        "ementa": texto_limpo((re.search(r'<p[^>]*class="ementa"[^>]*>(.*?)</p>', texto, re.S) or [None, ""])[1]),
        "orgao": texto_limpo((re.search(r'class="orgao-dou-data"[^>]*>(.*?)</span>', texto, re.S) or [None, ""])[1]),
    }


def guardar_atos(secao, atos):
    compactos = [{k: a.get(k) for k in CAMPOS_GUARDADOS if k in a} for a in atos]
    (SAIDA / f"atos_{secao}.json").write_text(json.dumps(compactos, ensure_ascii=False), encoding="utf-8")


def abrir_varios(coletor, atos_por_secao):
    abertos = []
    for secao, orgao, termo in VARIOS_ATOS:
        ato = next((a for a in atos_por_secao.get(secao, []) if orgao in (a.get("hierarchyStr") or "") and a.get("urlTitle")
                    and termo.lower() in (str(a.get("title")) + " " + str(a.get("content"))).lower()), None)
        if not ato:
            abertos.append({"secao": secao, "orgao": orgao, "termo": termo, "achado": False})
            continue
        url = f"https://www.in.gov.br/web/dou/-/{ato['urlTitle']}"
        doc, registro = coletor.baixar(url)
        bruto = getattr(doc, "raw_html", "") or ""
        nome = f"ato_{secao}_{len(abertos):02d}.html"
        (SAIDA / nome).write_text(bruto, encoding="utf-8")
        abertos.append({"secao": secao, "orgao": orgao, "termo": termo, "achado": True, "arquivo": nome, "url": url,
                        "chamada": registro, "lido_da_pagina": ler_ato(bruto)})
    return abertos


def investigar(coletor, secao, data, sem_busca=False):
    print(f"Seção {secao}, {data}")
    resultado = {"secao": secao}
    doc, registro = coletor.baixar(LEITURA.format(secao=secao, data=data))
    bruto = getattr(doc, "raw_html", "") or ""
    (SAIDA / f"leitura_{secao}.html").write_text(bruto, encoding="utf-8")
    resultado["leitura"] = registro
    dados = json_embutido(bruto)
    resultado["json_embutido"] = dados is not None
    if dados is None:
        resultado["trecho_inicial"] = bruto[:1500]
        return resultado, []
    resultado.update(resumir_atos(dados))
    atos = dados.get("jsonArray") or []
    guardar_atos(secao, atos)
    if sem_busca:
        return resultado, atos

    doc, registro = coletor.baixar(BUSCA.format(secao=SECAO_BUSCA.get(secao, secao), data=data))
    bruto_busca = getattr(doc, "raw_html", "") or ""
    (SAIDA / f"busca_{secao}.html").write_text(bruto_busca, encoding="utf-8")
    resultado["busca"] = dict(registro, totais_encontrados=total_da_busca(bruto_busca))
    return resultado, atos


def abrir_exemplo(coletor, atos, secao):
    ato = escolher_exemplo(atos)
    if not ato:
        return None
    url = f"https://www.in.gov.br/web/dou/-/{ato['urlTitle']}"
    doc, registro = coletor.baixar(url, formatos=("rawHtml", "markdown"))
    bruto = getattr(doc, "raw_html", "") or ""
    (SAIDA / f"ato_{secao}.html").write_text(bruto, encoding="utf-8")
    (SAIDA / f"ato_{secao}.md").write_text(getattr(doc, "markdown", "") or "", encoding="utf-8")
    lido = ler_ato(bruto)
    return {"url": url, "orgao_no_json": ato.get("hierarchyStr"), "tipo_no_json": ato.get("artType"),
            "titulo_no_json": ato.get("title"), "content_no_json": texto_limpo(ato.get("content")),
            "chamada": registro, "lido_da_pagina": lido, "caracteres_markdown": len(getattr(doc, "markdown", "") or "")}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", required=True, help="DD-MM-AAAA")
    parser.add_argument("--secoes", nargs="+", default=["dou1", "dou3"])
    parser.add_argument("--sem-atos", action="store_true", help="nao abre o ato de exemplo")
    parser.add_argument("--sem-busca", action="store_true", help="nao baixa a busca do in.gov.br (o total)")
    parser.add_argument("--varios-atos", action="store_true", help="abre um ato de cada orgao de VARIOS_ATOS")
    args = parser.parse_args()
    datetime.datetime.strptime(args.data, "%d-%m-%Y")
    if not os.getenv("FIRECRAWL_API_KEY"):
        raise SystemExit("FIRECRAWL_API_KEY é obrigatória.")
    SAIDA.mkdir(parents=True, exist_ok=True)
    coletor = Coletor()
    resumo = {"data": args.data, "secoes": {}, "atos_abertos": {}}
    atos_por_secao = {}
    for secao in args.secoes:
        try:
            resultado, atos = investigar(coletor, secao, args.data, args.sem_busca)
            atos_por_secao[secao] = atos
            if not args.sem_atos and not args.varios_atos and atos:
                resumo["atos_abertos"][secao] = abrir_exemplo(coletor, atos, secao)
        except Exception as erro:  # registra e segue para a proxima secao
            resultado = {"secao": secao, "erro": f"{type(erro).__name__}: {erro}"[:600]}
            print(f"  erro: {resultado['erro']}")
        resumo["secoes"][secao] = resultado
    if args.varios_atos:
        resumo["atos_abertos"] = abrir_varios(coletor, atos_por_secao)
        for aberto in resumo["atos_abertos"]:
            lido = aberto.get("lido_da_pagina") or {}
            print(f"  {aberto['secao']} {aberto['orgao'][:40]}: achado={aberto['achado']} texto={lido.get('caracteres')} identifica={lido.get('identifica', '')[:80]!r}")
    resumo["chamadas_firecrawl"] = coletor.chamadas
    resumo["creditos_firecrawl"] = coletor.creditos
    (SAIDA / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
    for secao, r in resumo["secoes"].items():
        print(f"{secao}: json={r.get('json_embutido')} atos={r.get('atos')} busca={((r.get('busca') or {}).get('totais_encontrados'))}")
    print(f"Créditos do Firecrawl: {coletor.creditos}")


if __name__ == "__main__":
    sys.exit(main())
