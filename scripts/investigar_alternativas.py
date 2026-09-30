"""
Verifica, fonte por fonte, se a coleta pode ser feita sem o Firecrawl.

Para cada fonte, testa sem gastar credito nenhum:

  1. download direto da listagem, quando o HTML ja traz as publicacoes sem
     depender de JavaScript;
  2. feed RSS ou Atom, anunciado na pagina ou nos enderecos padrao do Plone,
     a plataforma do gov.br;
  3. API publica: a REST do Plone (listagem e busca ordenada por data), o JSON
     da leitura do Diario Oficial, a busca de normativos do Banco Central e a
     API do WordPress;
  4. busca por data no proprio site.

Mede, para cada metodo, quantas publicacoes vieram com titulo, data, link e
descricao, e quantas caem na janela da execucao.

Respeito ao site:
  - le o robots.txt de cada host e nao acessa o que ele proibe;
  - se identifica no User-Agent (COLETA_CONTATO acrescenta um contato);
  - espera INTERVALO_HOST segundos entre requisicoes ao mesmo host, ou o
    Crawl-delay do robots.txt, se for maior;
  - nao contorna bloqueio: 401, 403, 429 ou pagina de desafio sao
    registrados como bloqueio, sem nova tentativa e sem trocar de
    identificacao.

Nao usa o Firecrawl nem chave nenhuma. So mede: nao altera o pipeline.

Uso:
    python scripts/investigar_alternativas.py --json output/alternativas.json
    python scripts/investigar_alternativas.py --fonte ANEEL ANATEL
    python scripts/investigar_alternativas.py --autoteste
"""

import argparse
import datetime
import email.utils
import gzip
import json
import os
import re
import sys
import time
import types
import unicodedata
import urllib.error
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
import zlib
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))

from coleta_direta import (  # noqa: E402
    AGENTE,
    BLOCO,
    Cliente,
    DATA_BR,
    DATA_EXTENSO,
    DATA_ISO,
    DATA_PONTO,
    DESAFIOS,
    DOMINIOS_RUIDO,
    FUSO,
    HORA,
    IGNORAR,
    IMAGEM,
    INTERVALO_HOST,
    LIMITE_BYTES,
    LINK_MD,
    LIXO_DESCRICAO,
    Leitor,
    MARCAS_RESULTADOS,
    MARCAS_SPA,
    MESES,
    NAVEGACAO,
    PAGINACAO,
    SEGMENTOS_RUIDO,
    TIMEOUT,
    USER_AGENT,
    _bloqueio,
    _campo,
    _decodificar,
    _host,
    _limpar_descricao,
    _local,
    data_de_campo,
    datas_em,
    enxuto,
    itens_json_generico,
    itens_plone,
    ler_feed,
    ler_html,
    parece_publicacao,
    parece_spa,
    plataforma,
    primeira_lista_de_objetos,
    publicacoes_da_listagem,
    regiao_de_resultados,
    sem_acento,
)

TETO_MINUTOS = 45
AMOSTRA = 3
# Fontes cujo texto lido fica guardado no resultado, para examinar a estrutura
# das que o leitor generico nao entendeu.
GUARDAR_TEXTO = {
    "Receita Federal | Normas", "B3 | Ofícios e Comunicados", "ONS | Notícias", "CCEE | Noticias",
    "ANP | Consultas e Audiências Públicas", "ANP | Consultas Prévias",
    "ANP | Pautas e Atas da Diretoria Colegiada", "ANATEL | Notícias", "Ministério do Meio Ambiente | Notícias",
    "CGU | Notícias", "Planalto | Resenha Diaria", "Ministério da Fazenda | Notícias", "Destaques do D.O.U.",
}

def resumo(publicacoes, inicio=None, fim=None):
    return {
        "publicacoes": len(publicacoes),
        "com_titulo": sum(1 for p in publicacoes if p.get("titulo")),
        "com_link": sum(1 for p in publicacoes if p.get("url")),
        "com_data": sum(1 for p in publicacoes if p.get("data")),
        "com_descricao": sum(1 for p in publicacoes if p.get("descricao")),
        "na_janela": sum(1 for p in publicacoes if p.get("na_janela")),
        "data_mais_antiga": min((p["data"] for p in publicacoes if p.get("data")), default=""),
        "data_mais_recente": max((p["data"] for p in publicacoes if p.get("data")), default=""),
        "amostra": [
            {k: p.get(k, "") for k in ("titulo", "data", "url", "descricao")}
            for p in ([p for p in publicacoes if p.get("na_janela")] or publicacoes)[:AMOSTRA]
        ],
        "na_janela_lista": [
            {k: (p.get(k, "") or "")[:200] for k in ("titulo", "data", "hora", "url", "descricao")}
            for p in publicacoes if p.get("na_janela")
        ][:60],
        "primeiras": [
            {k: (p.get(k, "") or "")[:120] for k in ("titulo", "data", "url")}
            for p in publicacoes[:8]
        ],
        "ordenada_por_data": _ordenada([p.get("data") for p in publicacoes if p.get("data")]),
    }


def _ordenada(datas):
    """A listagem vem da mais nova para a mais antiga? None se nao da para dizer."""
    if len(datas) < 3:
        return None
    fora = sum(1 for a, b in zip(datas, datas[1:]) if b > a)
    return fora <= max(1, len(datas) // 10)


def pistas_de_api(html_texto):
    """Enderecos de API citados no HTML de uma pagina montada por JavaScript."""
    achados = re.findall(r"""["'](https?://[^"'\s]+?/api/[^"'\s]{3,120}|/api/[^"'\s]{3,120})["']""", html_texto[:500_000])
    return sorted(set(achados))[:12]


# ---------------------------------------------------------------------------
# Investigacao por fonte
# ---------------------------------------------------------------------------


def raiz_plone(url):
    """Raiz do escopo no gov.br: os dois primeiros niveis, como a busca faz."""
    p = urlparse(url)
    partes = [x for x in p.path.split("/") if x]
    if p.netloc.endswith("gov.br") and len(partes) >= 2:
        return f"{p.scheme}://{p.netloc}/{partes[0]}/{partes[1]}"
    return f"{p.scheme}://{p.netloc}"


def testar_feed(cliente, url, anunciado, inicio, fim):
    registro = cliente.baixar(url, aceitar="application/rss+xml,application/atom+xml,application/xml,text/xml;q=0.9,*/*;q=0.5")
    saida = {"metodo": "feed", "url": url, "anunciado": anunciado, "http": enxuto(registro)}
    if registro["status"] != 200 or not registro["corpo"]:
        return saida
    try:
        saida.update(resumo(ler_feed(registro["corpo"], inicio, fim)))
        saida["ok"] = saida["publicacoes"] > 0
    except Exception as erro:
        saida["erro_leitura"] = " ".join(str(erro).split())[:160]
    return saida


def testar_json(cliente, nome, url, inicio, fim, leitura):
    registro = cliente.baixar(url, aceitar="application/json")
    saida = {"metodo": nome, "url": url, "http": enxuto(registro)}
    if registro["status"] != 200:
        return saida
    try:
        dados = json.loads(registro["texto"])
    except ValueError:
        saida["erro_leitura"] = "resposta nao e JSON (" + (registro["tipo"] or "sem tipo") + ")"
        return saida
    try:
        publicacoes = leitura(dados)
    except Exception as erro:
        saida["erro_leitura"] = " ".join(str(erro).split())[:160]
        return saida
    saida.update(resumo(publicacoes))
    saida["ok"] = saida["publicacoes"] > 0
    lista = primeira_lista_de_objetos(dados)
    if lista:
        saida["chaves_do_item"] = sorted(lista[0].keys())[:25]
    if isinstance(dados, dict):
        saida["total_declarado"] = dados.get("items_total") or dados.get("TotalRows") or dados.get("total")
    datas = sorted(p["data"] for p in publicacoes if p.get("data"))
    # Ordenado por data decrescente: se o mais antigo do lote ja e anterior a
    # janela, o lote cobre a janela inteira.
    saida["cobre_a_janela"] = bool(datas and datas[0] < inicio.isoformat())
    return saida


PUBLICADO = re.compile(r"publicad[oa]\s+em\s*:?\s*([^\n]{6,40})", re.I)
META_DATA = ("article:published_time", "dc.date.created", "dc.date.issued", "dcterms.created", "dcterms.issued", "date", "publishdate")


def datar_pelas_paginas(cliente, publicacoes, inicio, fim, limite=8):
    """
    Data de cada publicacao lida na propria pagina dela.

    Para listagem que mostra titulo e link mas nao a data (ANATEL, ANVISA,
    ANPD, SUSEP). Visita as primeiras, na ordem da listagem, e para ao achar
    uma anterior a janela, se a listagem estiver em ordem.
    """
    visitadas = []
    for publicacao in publicacoes[:limite]:
        registro = cliente.baixar(publicacao["url"])
        item = {"titulo": publicacao["titulo"][:120], "url": publicacao["url"], "status": registro["status"],
                "data": "", "hora": "", "descricao": "", "fonte_da_data": ""}
        if registro["status"] == 200 and registro["texto"]:
            leitor = ler_html(registro["texto"], registro["url_final"])
            data = None
            for nome in META_DATA:
                data = data_de_campo(leitor.meta.get(nome))
                if data:
                    item["fonte_da_data"] = "meta " + nome
                    break
            texto = leitor.texto()
            if not data:
                achado = PUBLICADO.search(sem_acento(texto))
                if achado:
                    datas = datas_em(achado.group(1))
                    if datas:
                        data, item["fonte_da_data"] = datas[0], "publicado em"
                        hora = HORA.search(achado.group(1))
                        item["hora"] = hora.group(0) if hora else ""
            if not data:
                datas = datas_em(texto[:4000])
                if datas:
                    data, item["fonte_da_data"] = datas[0], "primeira data do texto"
            item["data"] = data.isoformat() if data else ""
            item["descricao"] = " ".join((leitor.meta.get("description") or leitor.meta.get("og:description") or "").split())[:200]
        visitadas.append(item)
        if item["data"] and item["data"] < inicio.isoformat():
            break
    na_janela = [v for v in visitadas if v["data"] and inicio.isoformat() <= v["data"] <= fim.isoformat()]
    return {
        "metodo": "download_direto_com_paginas",
        "visitadas": len(visitadas),
        "com_data": sum(1 for v in visitadas if v["data"]),
        "com_descricao": sum(1 for v in visitadas if v["descricao"]),
        "na_janela": len(na_janela),
        "publicacoes": len(visitadas),
        "paginas": visitadas,
        "ok": bool(na_janela) or any(v["data"] for v in visitadas),
    }


def investigar_sharepoint(cliente, url, inicio, fim):
    """Busca REST do SharePoint, a mesma que serve a pagina do Banco Central."""
    p = urlparse(url)
    raiz = f"{p.scheme}://{p.netloc}"
    caminho = url.split("?")[0].rstrip("/")
    consultas = [
        f"{raiz}/_api/search/query?querytext='path:\"{caminho}\"'&rowlimit=30"
        "&sortlist='LastModifiedTime:descending'&selectproperties='Title,Path,Created,LastModifiedTime,Description'",
        f"{raiz}/_api/search/query?querytext='*'&refinementfilters='path:\"{caminho}\"'&rowlimit=30"
        "&sortlist='Created:descending'&selectproperties='Title,Path,Created,Description'",
    ]

    def leitura(dados):
        linhas = (((dados.get("PrimaryQueryResult") or {}).get("RelevantResults") or {}).get("Table") or {}).get("Rows") or []
        itens = []
        for linha in linhas:
            celulas = {c.get("Key"): c.get("Value") for c in linha.get("Cells") or []}
            itens.append({"Title": celulas.get("Title"), "Path": celulas.get("Path"), "Created": celulas.get("Created"),
                          "Description": celulas.get("Description")})
        return itens_json_generico(itens, inicio, fim)

    return [testar_json(cliente, "api_sharepoint_busca", c, inicio, fim, leitura) for c in consultas]


def investigar_dou(cliente, inicio, fim):
    """Leitura do jornal: o HTML traz o JSON com todos os atos do dia."""
    resultados = []
    dia = inicio
    while dia <= fim:
        url = f"https://www.in.gov.br/leiturajornal?data={dia.strftime('%d-%m-%Y')}&secao=do1"
        registro = cliente.baixar(url)
        saida = {"metodo": "api_dou_leiturajornal", "url": url, "http": enxuto(registro)}
        if registro["status"] == 200:
            leitor = ler_html(registro["texto"], url)
            params = next((j for j in leitor.json_embutido if j["id"] == "params"), None)
            if params:
                try:
                    dados = json.loads(params["texto"])
                    lista = dados.get("jsonArray") or []
                    publicacoes = itens_json_generico(
                        lista, inicio, fim,
                        montar_url=lambda x: f"https://www.in.gov.br/web/dou/-/{x.get('urlTitle', '')}" if x.get("urlTitle") else "",
                    )
                    saida.update(resumo(publicacoes))
                    saida["ok"] = bool(lista)
                    saida["chaves_do_item"] = sorted(lista[0].keys()) if lista else []
                    orgaos, tipos = {}, {}
                    for x in lista:
                        orgao = str(x.get("hierarchyStr") or "").split("/")[0].strip() or "?"
                        orgaos[orgao] = orgaos.get(orgao, 0) + 1
                        tipo = str(x.get("artType") or "?")
                        tipos[tipo] = tipos.get(tipo, 0) + 1
                    saida["atos_por_orgao"] = dict(sorted(orgaos.items(), key=lambda kv: -kv[1])[:25])
                    saida["atos_por_tipo"] = dict(sorted(tipos.items(), key=lambda kv: -kv[1])[:15])
                    saida["chars_json"] = len(params["texto"])
                except ValueError as erro:
                    saida["erro_leitura"] = str(erro)[:160]
            else:
                saida["erro_leitura"] = "sem <script id=params> no HTML"
                saida["pistas_de_api"] = pistas_de_api(registro["texto"])
        resultados.append(saida)
        dia += datetime.timedelta(days=1)
    return resultados


def investigar_bcb(cliente, inicio, fim):
    fim_mais = fim + datetime.timedelta(days=1)
    consulta = (
        "https://www.bcb.gov.br/api/search/app/normativos/buscanormativos?"
        "querytext=ContentType:normativo%20AND%20contentSource:normativos"
        "&rowlimit=40&startrow=0&sortlist=Data1OWSDATE:descending"
        f"&refinementfilters=Data:range(datetime({inicio.isoformat()}),datetime({fim_mais.isoformat()}))"
    )

    def leitura(dados):
        lista = primeira_lista_de_objetos(dados)

        def url(x):
            tipo = _campo(x, "tipodonormativo", "tipo")
            numero = _campo(x, "numeroowsnmbr", "numero")
            if tipo and numero:
                return f"https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo?tipo={tipo}&numero={numero.split('.')[0]}"
            return _campo(x, "link", "url", "path")

        return itens_json_generico(lista, inicio, fim, montar_url=url)

    return [testar_json(cliente, "api_bcb_buscanormativos", consulta, inicio, fim, leitura)]


def investigar_wordpress(cliente, url, inicio, fim):
    p = urlparse(url)
    raiz = f"{p.scheme}://{p.netloc}"
    consulta = f"{raiz}/wp-json/wp/v2/posts?per_page=20&_fields=date,link,title,excerpt"
    resultados = [testar_json(cliente, "api_wordpress", consulta, inicio, fim,
                              lambda d: itens_json_generico(d if isinstance(d, list) else [], inicio, fim))]
    for candidato in (url.rstrip("/") + "/feed/", raiz + "/feed/"):
        resultados.append(testar_feed(cliente, candidato, False, inicio, fim))
    return resultados


def investigar_fonte(cliente, fonte, inicio, fim, escopos):
    url = fonte["url"]
    saida = {"fonte": fonte["fonte"], "url": url, "estado": fonte.get("_estado", "ativa"),
             "host": urlparse(url).netloc, "metodos": []}
    leitor_robots, info = cliente.regras(url)
    if url.startswith("http://") and info.get("status") is None:
        # O servidor derrubou a conexao em HTTP: tenta o mesmo endereco em
        # HTTPS, que e o protocolo que o navegador usaria.
        url = "https://" + url[len("http://"):]
        saida["url_https"] = url
        leitor_robots, info = cliente.regras(url)
    saida["robots"] = dict(info, listagem_permitida=leitor_robots.can_fetch(AGENTE, url))

    # 1. Download direto
    registro = cliente.baixar(url)
    direto = {"metodo": "download_direto", "url": url, "http": enxuto(registro)}
    plataforma_detectada, leitor = "desconhecida", None
    if registro["status"] == 200 and registro["texto"]:
        leitor = ler_html(registro["texto"], registro["url_final"])
        plataforma_detectada = plataforma(registro["texto"], leitor, registro["url_final"])
        texto = leitor.texto()
        publicacoes = publicacoes_da_listagem(texto, registro["url_final"], inicio, fim)
        direto.update(resumo(publicacoes))
        direto.update({
            "plataforma": plataforma_detectada,
            "titulo_pagina": " ".join(leitor.titulo.split())[:120],
            "chars_texto": len(texto),
            "links": leitor.links,
            "scripts": leitor.scripts,
            "parece_spa": parece_spa(registro["texto"], leitor),
            "feeds_anunciados": leitor.feeds,
        })
        direto["ok"] = direto["publicacoes"] > 0 and not direto["parece_spa"] and not registro["bloqueio"]
        if direto["parece_spa"] or not direto["publicacoes"]:
            direto["pistas_de_api"] = pistas_de_api(registro["texto"])
        if fonte["fonte"] in GUARDAR_TEXTO:
            saida.setdefault("textos", {})["download_direto"] = texto[:40_000]
    saida["metodos"].append(direto)
    if direto.get("publicacoes") and direto.get("com_data", 0) < 0.3 * direto["publicacoes"] and not direto.get("parece_spa"):
        candidatas = publicacoes_da_listagem(texto, registro["url_final"], inicio, fim)
        saida["metodos"].append(datar_pelas_paginas(cliente, candidatas, inicio, fim))
    saida["plataforma"] = plataforma_detectada

    host = urlparse(url).netloc.lower()

    # 2. Feeds: os anunciados e, no Plone, os enderecos padrao de sindicacao.
    tentados = set()
    for feed in (leitor.feeds if leitor else []):
        if feed["url"] not in tentados:
            tentados.add(feed["url"])
            saida["metodos"].append(testar_feed(cliente, feed["url"], True, inicio, fim))
    if plataforma_detectada == "plone":
        for sufixo in ("rss.xml", "RSS"):
            candidato = url.rstrip("/") + "/" + sufixo
            if candidato not in tentados:
                tentados.add(candidato)
                saida["metodos"].append(testar_feed(cliente, candidato, False, inicio, fim))

    # 3. APIs
    if plataforma_detectada == "plone" and host.endswith("gov.br") and "planalto" not in host:
        campos = "metadata_fields=effective&metadata_fields=created&metadata_fields=Description"
        saida["metodos"].append(testar_json(
            cliente, "api_plone_listagem", f"{url.rstrip('/')}?b_size=40&{campos}",
            inicio, fim, lambda d: itens_plone(d, inicio, fim)))
        saida["metodos"].append(testar_json(
            cliente, "api_plone_busca_na_listagem",
            f"{url.rstrip('/')}/@search?sort_on=effective&sort_order=descending&b_size=40&{campos}",
            inicio, fim, lambda d: itens_plone(d, inicio, fim)))
        raiz = raiz_plone(url)
        if raiz in escopos:
            saida["metodos"].append({"metodo": "api_plone_busca_no_escopo", "url": raiz,
                                     "compartilhado_com": escopos[raiz]})
        else:
            escopos[raiz] = fonte["fonte"]
            saida["metodos"].append(testar_json(
                cliente, "api_plone_busca_no_escopo",
                f"{raiz}/@search?sort_on=effective&sort_order=descending&b_size=60&{campos}",
                inicio, fim, lambda d: itens_plone(d, inicio, fim)))
    if host.endswith("in.gov.br"):
        saida["metodos"].extend(investigar_dou(cliente, inicio, fim))
    if host.endswith("bcb.gov.br"):
        saida["metodos"].extend(investigar_bcb(cliente, inicio, fim))
    if plataforma_detectada == "wordpress":
        saida["metodos"].extend(investigar_wordpress(cliente, url, inicio, fim))
    if plataforma_detectada == "sharepoint" and not direto.get("ok"):
        saida["metodos"].extend(investigar_sharepoint(cliente, url, inicio, fim))

    # 4. Busca por data no proprio site (Plone classico), so se a API falhou.
    api_ok = any(m.get("ok") for m in saida["metodos"] if str(m.get("metodo", "")).startswith("api_plone"))
    if plataforma_detectada == "plone" and not api_ok:
        raiz = raiz_plone(url)
        busca = (f"{raiz}/@@search?SearchableText=&sort_on=Date&sort_order=reverse"
                 f"&created.query:record:list:date={inicio.isoformat()}&created.range:record=min")
        registro = cliente.baixar(busca)
        metodo = {"metodo": "busca_por_data_no_site", "url": busca, "http": enxuto(registro)}
        if registro["status"] == 200:
            regiao = regiao_de_resultados(registro["texto"])
            metodo["regiao_de_resultados"] = bool(regiao)
            if regiao:
                leitor_busca = ler_html(regiao, registro["url_final"])
                texto_busca = leitor_busca.texto()
                # A busca ja filtrou por data de criacao: todo resultado conta
                # como da janela, com ou sem data impressa ao lado.
                publicacoes = publicacoes_da_listagem(texto_busca, raiz_plone(url) + "/", inicio, fim, minimo_titulo=10)
                for publicacao in publicacoes:
                    publicacao["na_janela"] = not publicacao["data"] or inicio.isoformat() <= publicacao["data"] <= fim.isoformat()
                metodo.update(resumo(publicacoes))
                anuncio = re.search(r"[^.<>]{0,40}\d+\s+(?:itens|resultados?)[^.<>]{0,40}", sem_acento(texto_busca), re.I)
                metodo["total_anunciado"] = " ".join(anuncio.group(0).split())[:90] if anuncio else ""
                metodo["ok"] = metodo["na_janela"] > 0
                if fonte["fonte"] in GUARDAR_TEXTO:
                    saida.setdefault("textos", {})["busca_por_data_no_site"] = texto_busca[:40_000]
        saida["metodos"].append(metodo)

    return saida


def fontes_da_execucao(hoje):
    """As mesmas fontes que o pipeline coleta, inclusive as montadas por data."""
    for nome in ("firecrawl", "google", "google.genai", "google.genai.types"):
        if nome not in sys.modules:
            try:
                __import__(nome)
            except ImportError:
                sys.modules[nome] = types.ModuleType(nome)
    sys.modules["firecrawl"].__dict__.setdefault("Firecrawl", object)
    sys.modules["google"].__dict__.setdefault("genai", sys.modules["google.genai"])
    sys.modules["google.genai"].__dict__.setdefault("Client", object)
    sys.modules["google.genai"].__dict__.setdefault("types", sys.modules["google.genai.types"])
    sys.modules["google.genai.types"].__dict__.setdefault("GenerateContentConfig", object)
    import gerar_boletim as gb

    agora = datetime.datetime.now(FUSO)
    inicio = hoje - datetime.timedelta(days=3 if hoje.weekday() == 0 else 1)
    fontes = gb.fontes_execucao(datetime.datetime.combine(inicio, datetime.time(), tzinfo=FUSO), agora, hoje)
    for fonte in fontes:
        fonte["_estado"] = gb.estado(fonte, hoje)
    return fontes, inicio


def imprimir(resultado):
    print(f"\n### {resultado['fonte']}  [{resultado['estado']}]  {resultado['plataforma']}")
    robots = resultado["robots"]
    print(f"    robots.txt {robots.get('status')} ({robots.get('regras')}); listagem permitida: {robots.get('listagem_permitida')}"
          + (f"; crawl-delay {robots['crawl_delay']}" if robots.get("crawl_delay") else ""))
    for m in resultado["metodos"]:
        http = m.get("http") or {}
        estado = http.get("status")
        if "compartilhado_com" in m:
            print(f"    - {m['metodo']:<28} (mesmo escopo de {m['compartilhado_com']})")
            continue
        base = f"    - {m['metodo']:<28} {str(estado):>6} {http.get('ms', 0):>6}ms"
        if http.get("bloqueio"):
            base += f"  BLOQUEIO: {http['bloqueio']}"
        if http.get("erro") and estado != 200:
            base += f"  {http['erro'][:70]}"
        if "publicacoes" in m:
            base += (f"  pub={m['publicacoes']} data={m['com_data']} desc={m['com_descricao']}"
                     f" janela={m['na_janela']}")
            if m.get("cobre_a_janela") is not None and m["metodo"].startswith("api"):
                base += f" cobre={m['cobre_a_janela']}"
        if m.get("parece_spa"):
            base += "  SPA"
        if m.get("erro_leitura"):
            base += f"  leitura: {m['erro_leitura'][:70]}"
        print(base + ("  <- OK" if m.get("ok") else ""))
        for a in (m.get("amostra") or [])[:2]:
            print(f"        {a.get('data') or 'sem data':<10} {a.get('titulo', '')[:80]}")
            if a.get("descricao"):
                print(f"                   {a['descricao'][:90]}")


# ---------------------------------------------------------------------------
# Sondagem: de onde vem o conteudo que o HTML nao traz
# ---------------------------------------------------------------------------

SONDAR = [
    ("ANATEL | Notícias", "https://www.gov.br/anatel/pt-br/assuntos/noticias"),
    ("ANVISA | Notícias", "https://www.gov.br/anvisa/pt-br/assuntos/noticias-anvisa"),
    ("ANPD | Notícias", "https://www.gov.br/anpd/pt-br/assuntos/noticias"),
    ("SUSEP | Notícias", "https://www.gov.br/susep/pt-br/central-de-conteudos/noticias"),
    ("ONS | Notícias", "https://www.ons.org.br/paginas/imprensa/noticias"),
    ("Receita Federal | Normas", "http://normas.receita.fazenda.gov.br/sijut2consulta/consulta.action?ordemColuna=Publicacao&ordemDirecao=DESC&tipoData=2&p=1"),
    ("ANP | Consultas e Audiências Públicas", "https://www.gov.br/anp/pt-br/assuntos/consultas-e-audiencias-publicas/consulta-audiencia-publica"),
    ("ANP | Consultas Prévias", "https://www.gov.br/anp/pt-br/assuntos/consultas-e-audiencias-publicas/consulta-previa"),
    ("ANP | Pautas e Atas da Diretoria Colegiada", "https://www.gov.br/anp/pt-br/composicao/diretoria-colegiada/reunioes-da-diretoria-colegiada/pautas-atas-e-calendario-de-reunioes-da-diretoria-colegiada"),
    ("CNPE | Comunicações", "https://www.gov.br/mme/pt-br/assuntos/conselhos-e-comites/cnpe/comunicacoes"),
    ("CGU | Notícias", "https://www.gov.br/cgu/pt-br/assuntos/noticias/ultimas-noticias"),
    ("Ministério do Meio Ambiente | Notícias", "https://www.gov.br/mma/pt-br/assuntos/noticias/ultimas-noticias"),
    ("busca por data do gov.br", "https://www.gov.br/fazenda/pt-br/@@search?SearchableText=&sort_on=Date&sort_order=reverse&created.query:record:list:date={inicio}&created.range:record=min"),
]
PALAVRAS_DADOS = re.compile(r"(noticia|_api/|getbytitle|ajax|fetch\(|\$\.get|\$\.post|@@|/api/|\.json|listagem|resultado|idAto|link\.action)", re.I)
MARCAS_PRINCIPAL = ('id="content-core"', 'id="content"', 'id="main-content"', "<main", 'role="main"')


def sondar(cliente, url):
    registro = cliente.baixar(url)
    html_texto = registro["texto"] or ""
    saida = {"url": url, "http": enxuto(registro)}
    saida["scripts"] = re.findall(r"<script[^>]+src=[\"']([^\"']+)", html_texto, re.I)[:40]
    saida["atributos_data"] = sorted(set(re.findall(
        r"data-[\w-]+=[\"']([^\"']*(?:/|@@|\.json|api|search|busca|noticia)[^\"']*)[\"']", html_texto, re.I)))[:40]
    trechos = []
    for m in re.finditer(r"<script(?![^>]*src=)[^>]*>(.*?)</script>", html_texto, re.S | re.I):
        corpo = m.group(1)
        for k in PALAVRAS_DADOS.finditer(corpo):
            trechos.append(" ".join(corpo[max(0, k.start() - 200): k.start() + 300].split()))
            if len(trechos) >= 10:
                break
        if len(trechos) >= 10:
            break
    saida["trechos_de_script"] = trechos
    saida["formularios"] = re.findall(r"<form[^>]*action=[\"']([^\"']+)[\"'][^>]*", html_texto, re.I)[:10]
    saida["marcadores"] = {m: html_texto.count(m) for m in (
        "idAto", "link.action", "resultado", "tileItem", "searchResults", "search-results", "Carregando",
        "summary", "documentByLine", "collection", "listagem", "{{")}
    for marca in MARCAS_PRINCIPAL:
        posicao = html_texto.find(marca)
        if posicao != -1:
            leitor = ler_html(html_texto[posicao:posicao + 600_000], registro["url_final"])
            saida["regiao_principal"] = marca
            saida["texto_principal"] = leitor.texto()[:30_000]
            break
    # Scripts do proprio site costumam guardar o endereco que alimenta a pagina.
    host = urlparse(registro["url_final"]).netloc
    proprios = [urljoin(registro["url_final"], s) for s in saida["scripts"]]
    proprios = [s for s in proprios if urlparse(s).netloc == host and not re.search(r"jquery|bootstrap|analytics|gtag|recaptcha|vlibras|barra", s, re.I)]
    achados = []
    for script in proprios[:6]:
        codigo = cliente.baixar(script, aceitar="*/*")
        corpo = codigo["texto"] or ""
        for k in PALAVRAS_DADOS.finditer(corpo):
            achados.append({"script": script[-80:], "trecho": " ".join(corpo[max(0, k.start() - 160): k.start() + 240].split())})
            if len(achados) >= 16:
                break
    saida["trechos_em_scripts_do_site"] = achados
    return saida


VOLTO = {
    "ANATEL | Notícias": ("anatel", "pt-br/assuntos/noticias"),
    "ANVISA | Notícias": ("anvisa", "pt-br/assuntos/noticias-anvisa"),
    "ANPD | Notícias": ("anpd", "pt-br/assuntos/noticias"),
    "SUSEP | Notícias": ("susep", "pt-br/central-de-conteudos/noticias"),
}
ANOS_ANP = {
    "ANP | Consultas e Audiências Públicas": "https://www.gov.br/anp/pt-br/assuntos/consultas-e-audiencias-publicas/consulta-audiencia-publica/{ano}",
    "ANP | Consultas Prévias": "https://www.gov.br/anp/pt-br/assuntos/consultas-e-audiencias-publicas/consulta-previa/{ano}",
    "ANP | Pautas e Atas da Diretoria Colegiada": "https://www.gov.br/anp/pt-br/composicao/diretoria-colegiada/reunioes-da-diretoria-colegiada/pautas-atas-e-calendario-de-reunioes-da-diretoria-colegiada/{ano}",
}
CAMPOS_PLONE = "metadata_fields=effective&metadata_fields=created&metadata_fields=Description"


def descrever_json(dados):
    if isinstance(dados, dict):
        blocos = dados.get("blocks") or {}
        return {
            "chaves": sorted(dados.keys())[:30],
            "tipo": dados.get("@type"),
            "itens": len(dados.get("items") or []),
            "tipos_de_bloco": sorted({str(b.get("@type")) for b in blocos.values() if isinstance(b, dict)}),
            "consultas_de_bloco": [b.get("querystring") for b in blocos.values() if isinstance(b, dict) and b.get("querystring")][:3],
        }
    return {"tipo_python": type(dados).__name__}


def sondar_volto(cliente, site, caminho, inicio, fim):
    base = f"https://www.gov.br/{site}"
    tentativas = [
        ("conteudo", f"{base}/++api++/{caminho}"),
        ("busca", f"{base}/++api++/{caminho}/@search?sort_on=effective&sort_order=descending&b_size=30&{CAMPOS_PLONE}"),
        ("busca_noticias", f"{base}/++api++/{caminho}/@search?portal_type=News%20Item&sort_on=effective&sort_order=descending&b_size=30&{CAMPOS_PLONE}"),
        ("conteudo_raiz", f"https://www.gov.br/++api++/{site}/{caminho}"),
    ]
    saida = []
    for nome, url in tentativas:
        registro = cliente.baixar(url, aceitar="application/json")
        item = {"tentativa": nome, "url": url, "http": enxuto(registro)}
        if registro["status"] == 200:
            try:
                dados = json.loads(registro["texto"])
                item["json"] = descrever_json(dados)
                if isinstance(dados, dict) and dados.get("items"):
                    item.update(resumo(itens_plone(dados, inicio, fim)))
            except ValueError:
                item["erro_leitura"] = "nao e JSON (" + (registro["tipo"] or "?") + ")"
        saida.append(item)
    return saida


def sondar_receita(cliente, url, inicio, fim):
    registro = cliente.baixar(url)
    html_texto = registro["texto"] or ""
    pedacos = html_texto.split('class="linhaResultados')[1:]
    linhas = []
    for pedaco in pedacos[:60]:
        trecho = pedaco[:4000]
        ato = re.search(r"link\.action\?[^\"'\s>]*idAto=(\d+)[^\"'\s>]*", trecho)
        texto_linha = " ".join(re.sub(r"<[^>]+>", " ", trecho).split())
        datas = datas_em(texto_linha)
        linhas.append({
            "idAto": ato.group(1) if ato else "",
            "url": urljoin(registro["url_final"], ato.group(0)) if ato else "",
            "texto": texto_linha[:260],
            "datas": [d.isoformat() for d in datas][:4],
        })
    return {"http": enxuto(registro), "linhas": len(pedacos), "amostra_linhas": linhas[:6],
            "trecho_html": ('class="linhaResultados' + pedacos[0][:2500]) if pedacos else "",
            "com_data_na_janela": sum(1 for l in linhas if any(inicio.isoformat() <= d <= fim.isoformat() for d in l["datas"]))}


def sondar_ons(cliente):
    raiz = "https://www.ons.org.br"
    achados = []
    for caminho in ("/Style Library/custom/js/interna.js", "/Style Library/custom/js/script.js",
                    "/Style Library/custom/js/global.js", "/Style Library/custom/js/ready.js",
                    "https://www.ons.org.br/cdn/SiteAssets/custom/js/variables.js"):
        url = caminho if caminho.startswith("http") else raiz + caminho.replace(" ", "%20")
        registro = cliente.baixar(url, aceitar="*/*")
        corpo = registro["texto"] or ""
        for marca in ("noticiasLoad", "_api/", "getbytitle", "Noticias", "apiUrl", "urlApi", "https://"):
            posicao = corpo.find(marca)
            if posicao != -1:
                achados.append({"script": url[-50:], "status": registro["status"], "marca": marca,
                                "trecho": " ".join(corpo[max(0, posicao - 300): posicao + 1200].split())})
        if not corpo:
            achados.append({"script": url[-50:], "status": registro["status"], "marca": "", "trecho": ""})
    return achados


def sondar_receita_html(cliente, inicio, fim, destino):
    """O HTML em volta dos primeiros atos, nas duas URLs, para escrever o leitor da Receita."""
    resultado = {}
    for url in ("http://normas.receita.fazenda.gov.br/sijut2consulta/consulta.action?ordemColuna=Publicacao&ordemDirecao=DESC&tipoData=2&p=1",
                "https://normas.receita.fazenda.gov.br/sijut2consulta/consulta.action?ordemColuna=Publicacao&ordemDirecao=DESC&tipoData=2&p=1"):
        registro = cliente.baixar(url)
        html_texto = registro["texto"] or ""
        posicoes = [m.start() for m in re.finditer("idAto", html_texto)]
        resultado[url] = {
            "http": enxuto(registro),
            "idAto": len(posicoes),
            "trechos": [html_texto[max(0, p - 1500): p + 1500] for p in posicoes[:1]] + [html_texto[posicoes[2] - 800: posicoes[2] + 800]] if len(posicoes) > 2 else [],
            "classes_em_volta": sorted(set(re.findall(r'class="([^"]*)"', html_texto[posicoes[0] - 3000: posicoes[0] + 3000])))[:30] if posicoes else [],
        }
        print(url[:5], registro["status"], "idAto", len(posicoes))
    Path(destino).write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")


def sondar_dou(cliente, inicio, fim, destino):
    """Onde o DOU pode ser baixado sem Firecrawl: PDF completo, pagina e leitura."""
    resultado = []
    dia = fim
    while len(resultado) < 2 * 6 and dia >= fim - datetime.timedelta(days=5):
        if dia.weekday() < 5:
            a, m, d = dia.strftime("%Y"), dia.strftime("%m"), dia.strftime("%d")
            testes = [
                ("pdf_secao1_completo", f"https://download.in.gov.br/do/secao1/{a}/{a}_{m}_{d}/{a}_{m}_{d}_ASSINADO_do1.pdf", {"Range": "bytes=0-4095"}),
                ("pdf_pagina_1", f"https://pesquisa.in.gov.br/imprensa/servlet/INPDFViewer?jornal=515&pagina=1&data={d}/{m}/{a}&captchafield=firstAccess", {"Range": "bytes=0-4095"}),
                ("visualizador_pagina_1", f"https://pesquisa.in.gov.br/imprensa/jsp/visualiza/index.jsp?jornal=515&pagina=1&data={d}/{m}/{a}", None),
                ("leitura_do_jornal", f"https://www.in.gov.br/leiturajornal?data={d}-{m}-{a}&secao=do1", None),
                ("inlabs", "https://inlabs.in.gov.br/", None),
            ]
            for nome, url, extras in testes:
                if nome == "inlabs" and any(r["teste"] == "inlabs" for r in resultado):
                    continue
                registro = cliente.baixar(url, aceitar="*/*", extras=extras)
                item = {"dia": dia.isoformat(), "teste": nome, "url": url, "http": enxuto(registro),
                        "comeco": (registro["corpo"] or b"")[:8].decode("latin-1", "replace")}
                if nome == "leitura_do_jornal" and registro["status"] == 200:
                    leitor = ler_html(registro["texto"], url)
                    params = next((j for j in leitor.json_embutido if j["id"] == "params"), None)
                    item["atos"] = len(json.loads(params["texto"]).get("jsonArray") or []) if params else 0
                resultado.append(item)
                h = item["http"]
                print(f"{dia} {nome:<22} {h.get('status')} {h.get('tipo','')[:30]:<30} {h.get('tamanho_declarado','')} {item['comeco']!r} {h.get('erro','')[:60]} {item.get('atos','')}")
            break
        dia -= datetime.timedelta(days=1)
    info = {h: i for h, (_, i) in cliente.robots.items()}
    print("robots:", {h: (i.get("status"), i.get("regras")) for h, i in info.items()})
    Path(destino).write_text(json.dumps({"testes": resultado, "robots": info}, ensure_ascii=False, indent=1), encoding="utf-8")


def sondar_paginacao_receita(cliente, inicio, fim, destino):
    """Como a tabela da Receita pagina: links, formulario e campos de data."""
    url = "https://normas.receita.fazenda.gov.br/sijut2consulta/consulta.action?ordemColuna=Publicacao&ordemDirecao=DESC&tipoData=2&p=1"
    registro = cliente.baixar(url)
    html_texto = registro["texto"] or ""
    resultado = {
        "http": enxuto(registro),
        "links_de_pagina": sorted(set(re.findall(r"""(?:href|onclick)=["']([^"']*(?:p=\d|pagina|Pagina|paginacao)[^"']*)["']""", html_texto)))[:30],
        "formularios": re.findall(r"<form[^>]*>", html_texto, re.I)[:5],
        "campos": sorted(set(re.findall(r"""<(?:input|select)[^>]*name=["']([^"']+)["'][^>]*>""", html_texto, re.I)))[:60],
        "trechos_paginacao": [" ".join(html_texto[max(0, m.start() - 400): m.start() + 600].split())
                              for m in re.finditer(r"pagina(?:cao|ção)|class=['\"]pagination", html_texto, re.I)][:4],
        "scripts_com_p": [" ".join(t.split())[:600] for t in re.findall(r"<script[^>]*>(.*?)</script>", html_texto, re.S) if re.search(r"\bp=|pagina", t)][:4],
    }
    for chave, valor in resultado.items():
        print(chave, json.dumps(valor, ensure_ascii=False)[:1500])
    Path(destino).write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")


def ensaiar_coleta(cliente, inicio, fim, destino):
    """
    A coleta gratuita de producao contra os sites reais, sem Firecrawl e sem
    Gemini: o que cada fonte devolve, antes de uma execucao que gasta.
    """
    import coleta_direta

    fontes, _ = fontes_da_execucao(fim)
    so = os.getenv("ENSAIO_FONTE", "")
    resultado = []
    for fonte in fontes:
        if fonte["_estado"] != "ativa" or fonte.get("coleta", "firecrawl") == "firecrawl":
            continue
        if so and so.lower() not in fonte["fonte"].lower():
            continue
        item = {"fonte": fonte["fonte"], "coleta": fonte.get("coleta")}
        try:
            coleta = coleta_direta.coletar(cliente, fonte, inicio, fim)
            publicacoes = coleta["publicacoes"]
            item.update(listadas=coleta["listadas"], requisicoes=coleta["requisicoes"],
                        com_data=sum(1 for p in publicacoes if p["data"]),
                        com_descricao=sum(1 for p in publicacoes if p["descricao"]),
                        na_janela=sum(1 for p in publicacoes if p["na_janela"]),
                        aviso=coleta.get("aviso", ""), datas=sorted({p["data"] for p in publicacoes}),
                        enviar=[{k: p[k][:110] for k in ("data", "hora", "titulo", "url", "descricao")} for p in publicacoes if p["enviar"]][:80])
        except coleta_direta.FalhaColeta as erro:
            item["falha"] = str(erro)
        resultado.append(item)
        print(f"{item['fonte'][:40]:<40} {item['coleta']:<9} " + (f"FALHA {item['falha']}" if "falha" in item else
              f"listadas={item['listadas']} data={item['com_data']} desc={item['com_descricao']} janela={item['na_janela']} enviar={len(item['enviar'])} req={item['requisicoes']}"))
        for p in item.get("enviar", [])[:4]:
            print(f"      {p['data'] or '—':<10} {p['hora']:<6} {p['titulo'][:80]}")
    Path(destino).write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")


def executar_sondagem_final(cliente, inicio, fim, destino):
    resultado = {"volto": {}, "anp_por_ano": {}, "receita": None, "ons": None, "volto_config": None}
    for nome, (site, caminho) in VOLTO.items():
        resultado["volto"][nome] = sondar_volto(cliente, site, caminho, inicio, fim)
        for t in resultado["volto"][nome]:
            print(f"{nome[:22]:<22} {t['tentativa']:<15} {(t['http'] or {}).get('status')} {t.get('json', {}).get('tipo', '')} "
                  f"itens={t.get('json', {}).get('itens', '')} janela={t.get('na_janela', '')} {t.get('erro_leitura', '')}")
    # Configuracao do Volto embutida na pagina: onde o frontend busca a API.
    registro = cliente.baixar("https://www.gov.br/anatel/pt-br/assuntos/noticias")
    config = re.findall(r'"(?:apiPath|internalApiPath|apiExpanders|publicURL|devProxyToApiPath)":"?[^,}]{0,160}', registro["texto"] or "")
    resultado["volto_config"] = config[:12]
    print("config volto:", config[:6])
    for nome, modelo in ANOS_ANP.items():
        resultado["anp_por_ano"][nome] = []
        for ano in (fim.year, fim.year + 1):
            url = modelo.format(ano=ano)
            registro = cliente.baixar(url)
            item = {"url": url, "http": enxuto(registro)}
            if registro["status"] == 200:
                html_texto = registro["texto"]
                posicao = html_texto.find('id="content-core"')
                trecho = html_texto[posicao:posicao + 400_000] if posicao != -1 else html_texto
                leitor = ler_html(trecho, registro["url_final"])
                texto = leitor.texto()
                item.update(resumo(publicacoes_da_listagem(texto, registro["url_final"], inicio, fim)))
                item["texto_principal"] = texto[:6000]
            resultado["anp_por_ano"][nome].append(item)
            print(f"{nome[:30]:<30} {ano} {(item['http'] or {}).get('status')} pub={item.get('publicacoes', '')} data={item.get('com_data', '')} janela={item.get('na_janela', '')}")
    resultado["receita"] = sondar_receita(
        cliente, "https://normas.receita.fazenda.gov.br/sijut2consulta/consulta.action?ordemColuna=Publicacao&ordemDirecao=DESC&tipoData=2&p=1",
        inicio, fim)
    print("receita:", resultado["receita"]["http"].get("status"), "linhas", resultado["receita"]["linhas"], "na janela", resultado["receita"]["com_data_na_janela"])
    resultado["ons"] = sondar_ons(cliente)
    print("ons:", [(a["script"], a["status"], a["marca"]) for a in resultado["ons"]])
    if destino:
        Path(destino).write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Detalhe em {destino}")


def executar_sondagem(cliente, inicio, destino):
    resultado = {}
    for nome, url in SONDAR:
        url = url.format(inicio=inicio.isoformat())
        try:
            resultado[nome] = sondar(cliente, url)
        except Exception as erro:
            resultado[nome] = {"url": url, "erro": " ".join(str(erro).split())[:300]}
        r = resultado[nome]
        print(f"\n### {nome}: {(r.get('http') or {}).get('status')} regiao={r.get('regiao_principal')} "
              f"scripts={len(r.get('scripts', []))} data={len(r.get('atributos_data', []))} "
              f"trechos={len(r.get('trechos_de_script', []))}+{len(r.get('trechos_em_scripts_do_site', []))} marcadores={r.get('marcadores')}")
    if destino:
        Path(destino).parent.mkdir(parents=True, exist_ok=True)
        Path(destino).write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Detalhe em {destino}")


# ---------------------------------------------------------------------------
# Autoteste offline
# ---------------------------------------------------------------------------


def autoteste():
    inicio, fim = datetime.date(2026, 9, 29), datetime.date(2026, 9, 30)
    base = "https://www.gov.br/aneel/pt-br/assuntos/noticias"
    html_plone = """<html><head><meta name="generator" content="Plone - http://plone.com">
    <link rel="alternate" type="application/rss+xml" title="RSS" href="https://www.gov.br/aneel/pt-br/assuntos/noticias/RSS">
    <title>Noticias</title></head><body>
    <nav><a href="https://www.gov.br/aneel/pt-br/composicao/diretoria">Diretoria colegiada da agencia</a></nav>
    <div id="content"><article class="tileItem">
      <h2 class="tileHeadline"><a href="https://www.gov.br/aneel/pt-br/assuntos/noticias/2026/aneel-aprova-reajuste">ANEEL aprova reajuste tarifario da distribuidora</a></h2>
      <p class="tileBody"><span class="description">A diretoria aprovou nesta terca o reajuste anual com efeito medio de 3,2% para os consumidores.</span></p>
      <span class="documentByLine"><span class="summary-view-icon">29/09/2026</span><span>16h40</span></span>
    </article><article class="tileItem">
      <h2 class="tileHeadline"><a href="https://www.gov.br/aneel/pt-br/assuntos/noticias/2026/consulta-publica-sobre-geracao">Consulta publica sobre geracao distribuida</a></h2>
      <span class="documentByLine"><span class="summary-view-icon">27/09/2026</span></span>
    </article></div>
    <footer><a href="https://www.gov.br/aneel/pt-br/acesso-a-informacao/institucional">Institucional da agencia reguladora</a></footer>
    </body></html>"""
    leitor = ler_html(html_plone, base)
    pubs = publicacoes_da_listagem(leitor.texto(), base, inicio, fim)
    assert [p["data"] for p in pubs] == ["2026-09-29", "2026-09-27"], pubs
    assert pubs[0]["na_janela"] and not pubs[1]["na_janela"], pubs
    assert pubs[0]["descricao"].startswith("A diretoria aprovou"), pubs[0]
    assert pubs[1]["descricao"] == "", pubs[1]
    assert leitor.feeds and leitor.feeds[0]["url"].endswith("/RSS")
    assert plataforma(html_plone, leitor, base) == "plone"

    # Data antes do titulo: o lado certo e escolhido pela pagina.
    antes = ("[Outro link de navegacao geral](https://www.gov.br/x/pt-br/a)\n"
             "29/09/2026\n[Primeira publicacao da lista de hoje](https://www.gov.br/x/pt-br/noticias/p1)\n"
             "28/09/2026\n[Segunda publicacao da lista de ontem](https://www.gov.br/x/pt-br/noticias/p2)\n")
    pubs = publicacoes_da_listagem(antes, "https://www.gov.br/x/pt-br/noticias", inicio, fim)
    assert [p["data"] for p in pubs] == ["2026-09-29", "2026-09-28"], pubs

    rss1 = b"""<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
      xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
      <item rdf:about="https://www.gov.br/x/pt-br/n1"><title>Titulo um</title><link>https://www.gov.br/x/pt-br/n1</link>
      <description>Descricao longa o bastante do item um</description><dc:date>2026-09-29T19:40:00Z</dc:date></item>
    </rdf:RDF>"""
    pubs = ler_feed(rss1, inicio, fim)
    assert pubs[0]["data"] == "2026-09-29" and pubs[0]["na_janela"] and pubs[0]["descricao"], pubs
    rss2 = b"""<rss version="2.0"><channel><item><title>T</title><link>https://a.b/c</link>
      <pubDate>Tue, 29 Sep 2026 22:10:00 GMT</pubDate><description>&lt;p&gt;Resumo com html dentro do feed&lt;/p&gt;</description></item></channel></rss>"""
    pubs = ler_feed(rss2, inicio, fim)
    assert pubs[0]["data"] == "2026-09-29" and "Resumo com html" in pubs[0]["descricao"], pubs
    atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>A</title>
      <link rel="alternate" href="https://a.b/e"/><updated>2026-09-30T01:00:00Z</updated><summary>Resumo do item em Atom aqui</summary></entry></feed>"""
    pubs = ler_feed(atom, inicio, fim)
    assert pubs[0]["url"] == "https://a.b/e" and pubs[0]["data"] == "2026-09-29", pubs  # 01h UTC = 22h de 29/09 em Brasilia

    plone = {"items": [
        {"@id": "https://www.gov.br/x/pt-br/n1", "@type": "News Item", "title": "N1", "description": "D1", "effective": "2026-09-29T16:40:00-03:00"},
        {"@id": "https://www.gov.br/x/pt-br/img", "@type": "Image", "title": "img", "effective": "2026-09-29T16:40:00-03:00"},
        {"@id": "https://www.gov.br/x/pt-br/n0", "@type": "News Item", "title": "N0", "description": "", "effective": "2026-09-20T10:00:00-03:00"},
    ], "items_total": 3}
    pubs = itens_plone(plone, inicio, fim)
    assert [p["na_janela"] for p in pubs] == [True, False], pubs

    assert datas_em("Portaria de 29 de setembro de 2026") == [datetime.date(2026, 9, 29)]
    assert data_de_campo("1969-12-31T00:00:00+00:00") is None
    assert not parece_publicacao("https://www.gov.br/aneel/pt-br/assuntos", base)
    assert not parece_publicacao("https://www.gov.br/aneel/pt-br/assuntos/noticias/foto.jpg", base)
    assert parece_publicacao("https://www.gov.br/anp/pt-br/composicao/diretoria-colegiada/pauta.pdf",
                             "https://www.gov.br/anp/pt-br/composicao/diretoria-colegiada/pautas")
    assert _ordenada(["2026-09-30", "2026-09-29", "2026-09-29", "2026-09-20"]) is True
    assert _ordenada(["2026-09-01", "2026-09-10", "2026-09-20", "2026-09-30"]) is False
    busca = '<div id="portal-header">[menu]</div><div id="search-results"><ol class="searchResults"><li>x</li></ol></div><footer>r</footer>'
    assert regiao_de_resultados(busca).startswith('id="search-results"') and "<footer" not in regiao_de_resultados(busca)
    assert _bloqueio(403, "") == "HTTP 403"
    assert _bloqueio(200, "<html><title>Just a moment...</title></html>") == "just a moment"
    assert _bloqueio(200, "<html>" + "texto " * 2000 + "captcha</html>") == ""
    print("autoteste: ok")


# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fonte", nargs="*", default=[])
    parser.add_argument("--json", default="")
    parser.add_argument("--autoteste", action="store_true")
    parser.add_argument("--sondar", action="store_true", help="examina de onde vem o conteudo das paginas montadas por JavaScript")
    parser.add_argument("--sondar-final", action="store_true", help="testa a API do Volto, as paginas de ano da ANP, as linhas da Receita e o script do ONS")
    parser.add_argument("--sondar-alvo", default="", help="final, receita ou dou")
    args = parser.parse_args()

    if args.autoteste:
        autoteste()
        return

    agente = USER_AGENT
    if os.getenv("COLETA_CONTATO"):
        agente = agente[:-1] + f"; contato: {os.environ['COLETA_CONTATO']})"
    cliente = Cliente(agente)

    hoje = datetime.datetime.now(FUSO).date()
    fontes, inicio = fontes_da_execucao(hoje)
    if args.sondar_alvo == "receita_paginas":
        sondar_paginacao_receita(cliente, inicio, hoje, args.json)
        return
    if args.sondar_alvo == "coleta":
        ensaiar_coleta(cliente, inicio, hoje, args.json)
        print(f"{cliente.requisicoes} requisicoes, nenhuma ao Firecrawl.")
        return
    if args.sondar_alvo in ("receita", "dou"):
        (sondar_receita_html if args.sondar_alvo == "receita" else sondar_dou)(cliente, inicio, hoje, args.json)
        print(f"{cliente.requisicoes} requisicoes, nenhuma ao Firecrawl.")
        return
    if args.sondar_final or args.sondar_alvo == "final":
        executar_sondagem_final(cliente, inicio, hoje, args.json)
        print(f"{cliente.requisicoes} requisicoes, nenhuma ao Firecrawl.")
        return
    if args.sondar:
        executar_sondagem(cliente, inicio, args.json)
        print(f"{cliente.requisicoes} requisicoes, nenhuma ao Firecrawl.")
        return
    if args.fonte:
        alvos = [sem_acento(a).lower() for a in args.fonte]
        fontes = [f for f in fontes if any(a in sem_acento(f["fonte"]).lower() for a in alvos)]
    fontes = [f for f in fontes if f["_estado"] != "inativa"]

    print(f"Janela: {inicio.isoformat()} a {hoje.isoformat()} | {len(fontes)} fonte(s) | User-Agent: {agente}")
    limite = time.monotonic() + TETO_MINUTOS * 60
    resultados, escopos = [], {}
    for fonte in fontes:
        if time.monotonic() > limite:
            print(f"Teto de {TETO_MINUTOS} minutos atingido; parando com {len(resultados)} fonte(s).")
            break
        try:
            resultado = investigar_fonte(cliente, fonte, inicio, hoje, escopos)
        except Exception as erro:  # uma fonte nunca derruba a investigacao
            resultado = {"fonte": fonte["fonte"], "url": fonte["url"], "estado": fonte.get("_estado"),
                         "plataforma": "?", "robots": {}, "metodos": [],
                         "erro": " ".join(str(erro).split())[:300]}
        resultados.append(resultado)
        imprimir(resultado)

    print(f"\n{cliente.requisicoes} requisicoes, nenhuma ao Firecrawl.")
    if args.json:
        destino = Path(args.json)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps({
            "executado_em": datetime.datetime.now(FUSO).isoformat(),
            "janela": {"inicio": inicio.isoformat(), "fim": hoje.isoformat()},
            "user_agent": agente,
            "requisicoes": cliente.requisicoes,
            "robots": {h: info for h, (_, info) in cliente.robots.items()},
            "fontes": resultados,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Detalhe em {destino}")


if __name__ == "__main__":
    main()
