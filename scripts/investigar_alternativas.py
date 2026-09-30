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

FUSO = ZoneInfo("America/Sao_Paulo")
AGENTE = "BoletimRadarBot"
USER_AGENT = (
    f"{AGENTE}/1.0 (coleta automatizada de publicacoes oficiais para boletim "
    "juridico; uma visita por pagina ao dia)"
)
INTERVALO_HOST = 3.0
TIMEOUT = 30
LIMITE_BYTES = 6_000_000
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

# ---------------------------------------------------------------------------
# Datas
# ---------------------------------------------------------------------------

MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5,
    "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12,
}
DATA_BR = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")
DATA_PONTO = re.compile(r"(?<!\d)(\d{2})\.(\d{2})\.(\d{4})(?!\d)")
DATA_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
DATA_EXTENSO = re.compile(
    r"(?<!\d)(\d{1,2})(?:º|o)?\s+de\s+(janeiro|fevereiro|marco|abril|maio|junho|"
    r"julho|agosto|setembro|outubro|novembro|dezembro)\s+de\s+(\d{4})",
    re.I,
)


def sem_acento(texto):
    return "".join(
        c for c in unicodedata.normalize("NFD", str(texto))
        if unicodedata.category(c) != "Mn"
    )


def datas_em(texto):
    """Todas as datas reconheciveis num trecho, em ordem de aparicao."""
    achadas = []
    alvo = sem_acento(texto or "")
    for padrao, ordem in ((DATA_BR, "dma"), (DATA_PONTO, "dma"), (DATA_ISO, "amd")):
        for m in padrao.finditer(alvo):
            a, b, c = (int(x) for x in m.groups())
            dia, mes, ano = (a, b, c) if ordem == "dma" else (c, b, a)
            try:
                achadas.append((m.start(), datetime.date(ano, mes, dia)))
            except ValueError:
                pass
    for m in DATA_EXTENSO.finditer(alvo):
        try:
            achadas.append(
                (m.start(), datetime.date(int(m.group(3)), MESES[m.group(2).lower()], int(m.group(1))))
            )
        except ValueError:
            pass
    return [d for _, d in sorted(achadas)]


def data_de_campo(valor):
    """Data de um campo de feed ou API: ISO, RFC 822 ou dd/mm/aaaa."""
    texto = str(valor or "").strip()
    if not texto or texto.startswith(("1969", "1000", "2499", "None")):
        return None
    try:
        return email.utils.parsedate_to_datetime(texto).astimezone(FUSO).date()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        instante = datetime.datetime.fromisoformat(texto.replace("Z", "+00:00"))
        if instante.tzinfo:
            instante = instante.astimezone(FUSO)
        return instante.date()
    except ValueError:
        pass
    datas = datas_em(texto)
    return datas[0] if datas else None


# ---------------------------------------------------------------------------
# HTML -> texto com links, no formato que o Firecrawl entrega
# ---------------------------------------------------------------------------

BLOCO = {
    "p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr",
    "td", "th", "table", "tbody", "article", "section", "header", "main", "dd",
    "dt", "dl", "figure", "figcaption", "blockquote", "hr",
}
IGNORAR = {"script", "style", "noscript", "template", "svg"}
NAVEGACAO = {"nav", "footer", "aside"}
MARCAS_SPA = ('id="root"', "id='root'", "<app-root", "ng-version", "__next_data__", 'id="app"', "data-reactroot")


class Leitor(HTMLParser):
    def __init__(self, base, filtrar_navegacao=True):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.filtrar_navegacao = filtrar_navegacao
        self.partes = []
        self.ignorando = 0
        self.navegacao = 0
        self.link = None
        self.titulo = ""
        self.em_titulo = False
        self.meta = {}
        self.feeds = []
        self.scripts = 0
        self.json_embutido = []
        self._json = None
        self.chars_texto = 0
        self.chars_navegacao = 0
        self.links = 0

    def _emitir(self, texto):
        self.partes.append(texto)

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "script":
            self.scripts += 1
            tipo = a.get("type", "").lower()
            if "json" in tipo or a.get("id") in ("params", "__NEXT_DATA__"):
                self._json = {"id": a.get("id", ""), "tipo": tipo, "partes": []}
        if tag == "meta":
            nome = (a.get("name") or a.get("property") or "").lower()
            if nome:
                self.meta[nome] = a.get("content", "")
        if tag == "link":
            rel, tipo = a.get("rel", "").lower(), a.get("type", "").lower()
            if "alternate" in rel and ("rss" in tipo or "atom" in tipo) and a.get("href"):
                self.feeds.append({"url": urljoin(self.base, a["href"]), "tipo": tipo, "titulo": a.get("title", "")})
        if tag == "title":
            self.em_titulo = True
        if tag in IGNORAR:
            self.ignorando += 1
        if tag in NAVEGACAO:
            self.navegacao += 1
        if self.ignorando:
            return
        if tag == "time" and a.get("datetime"):
            self._emitir(" " + a["datetime"][:10] + " ")
        if tag == "a":
            href = a.get("href", "").strip()
            self.link = [urljoin(self.base, href) if href else "", []]
        if tag in BLOCO or tag == "br":
            self._emitir("\n")
        elif self.link is not None:
            self.link[1].append(" ")
        else:
            # Elementos em linha colados ("29/09/2026" + "16h40") viravam um
            # numero so e escondiam a data.
            self._emitir(" ")

    def handle_endtag(self, tag):
        if tag == "title":
            self.em_titulo = False
        if tag == "script" and self._json is not None:
            self.json_embutido.append({"id": self._json["id"], "tipo": self._json["tipo"], "texto": "".join(self._json["partes"])})
            self._json = None
        if tag in IGNORAR and self.ignorando:
            self.ignorando -= 1
            return
        if tag in NAVEGACAO and self.navegacao:
            self.navegacao -= 1
        if self.ignorando:
            return
        if tag == "a" and self.link is not None:
            href, textos = self.link
            self.link = None
            texto = " ".join(" ".join(textos).split()).replace("[", "(").replace("]", ")")
            if texto and href.startswith("http") and not (self.filtrar_navegacao and self.navegacao):
                self._emitir(f"[{texto}]({href.replace(' ', '%20').replace(')', '%29')})")
                self.links += 1
            elif texto and not (self.filtrar_navegacao and self.navegacao):
                self._emitir(texto)
        if tag in BLOCO:
            self._emitir("\n")
        elif tag != "a":
            self._emitir(" ")

    def handle_data(self, data):
        if self.em_titulo:
            self.titulo += data
            return
        if self._json is not None:
            self._json["partes"].append(data)
            return
        if self.ignorando:
            return
        limpo = data.strip()
        if self.navegacao:
            self.chars_navegacao += len(limpo)
            if self.filtrar_navegacao:
                return
        self.chars_texto += len(limpo)
        if self.link is not None:
            self.link[1].append(data)
        else:
            self._emitir(data)

    def texto(self):
        bruto = "".join(self.partes)
        linhas = [" ".join(linha.split()) for linha in bruto.split("\n")]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(linhas)).strip()


MARCAS_RESULTADOS = ('id="search-results"', 'class="searchResults', "class='searchResults", 'id="searchResults"', 'class="search-results')


def regiao_de_resultados(html_texto):
    """So a lista de resultados de uma pagina de busca, sem menu e rodape."""
    posicoes = [html_texto.find(m) for m in MARCAS_RESULTADOS if m in html_texto]
    if not posicoes:
        return ""
    inicio = min(posicoes)
    fim = min([x for x in (html_texto.find('id="portal-footer', inicio), html_texto.find("<footer", inicio)) if x != -1] or [inicio + 250_000])
    return html_texto[inicio:fim]


def ler_html(html_texto, base):
    """Le o HTML duas vezes se preciso: sem navegacao e, se sobrar pouco, com."""
    leitor = Leitor(base, filtrar_navegacao=True)
    try:
        leitor.feed(html_texto)
        leitor.close()
    except Exception:
        pass
    total = leitor.chars_texto + leitor.chars_navegacao
    if total and leitor.chars_navegacao > 0.7 * total:
        # Um <nav> ou <aside> sem fechamento engoliria a pagina inteira.
        completo = Leitor(base, filtrar_navegacao=False)
        try:
            completo.feed(html_texto)
            completo.close()
        except Exception:
            pass
        completo.feeds, completo.meta = leitor.feeds, leitor.meta
        return completo
    return leitor


def plataforma(html_texto, leitor, url):
    gerador = (leitor.meta.get("generator") or "").lower()
    amostra = html_texto[:200_000].lower()
    if "plone" in gerador or "portaltype-" in amostra or "plone-" in amostra:
        return "plone"
    if "wordpress" in gerador or "/wp-content/" in amostra or "/wp-json/" in amostra:
        return "wordpress"
    if "_layouts/15" in amostra or "microsoft sharepoint" in gerador or "sharepoint" in amostra[:20000]:
        return "sharepoint"
    if "liferay" in amostra:
        return "liferay"
    if urlparse(url).netloc.endswith("gov.br") and "/pt-br/" in url:
        return "plone"
    return "desconhecida"


def parece_spa(html_texto, leitor):
    amostra = html_texto[:200_000].lower()
    marca = any(m in amostra for m in MARCAS_SPA)
    return (leitor.chars_texto < 1500 and leitor.scripts >= 3) or (marca and leitor.chars_texto < 4000)


# ---------------------------------------------------------------------------
# Publicacoes numa listagem
# ---------------------------------------------------------------------------

LINK_MD = re.compile(r"\[([^\]]{1,400})\]\((https?://[^\s)]+)\)")
IMAGEM = re.compile(r"\.(?:jpe?g|png|gif|webp|svg|ico)$", re.I)
SEGMENTOS_RUIDO = (
    "/acesso-a-informacao", "/composicao", "/canais_atendimento", "/agenda",
    "/acessibilidade", "/mapa-do-site", "/fale-conosco", "/ouvidoria",
    "/login", "/search", "/@@search", "/busca", "/rss", "/feed", "/contato",
    "/redes-sociais", "/perguntas-frequentes", "/servicos",
)
DOMINIOS_RUIDO = (
    "facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com",
    "linkedin.com", "whatsapp.com", "flickr.com", "tiktok.com", "spotify.com",
    "soundcloud.com", "t.me",
)
PAGINACAO = ("b_start", "page", "pagina", "paged", "start", "offset")
HORA = re.compile(r"(?<!\d)(\d{1,2})h(\d{2})(?!\d)|(?<!\d)(\d{1,2}):(\d{2})(?!\d)")
LIXO_DESCRICAO = re.compile(
    r"(publicado em|atualizado em|compartilhe|leia mais|saiba mais|copiar para|"
    r"link para|\d{1,2}h\d{2}|\d{1,2}:\d{2})",
    re.I,
)


def _host(url):
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def parece_publicacao(url, base):
    p, b = urlparse(url), urlparse(base)
    if p.scheme not in ("http", "https") or not p.netloc:
        return False
    if any(d in p.netloc.lower() for d in DOMINIOS_RUIDO):
        return False
    if _host(url) != _host(base):
        return False
    caminho, caminho_base = p.path.rstrip("/").lower(), b.path.rstrip("/").lower()
    if caminho == caminho_base and p.query == b.query:
        return False
    if caminho and caminho_base.startswith(caminho) and not p.query:
        return False  # trilha de navegacao: um ancestral da listagem
    if IMAGEM.search(caminho) or "/@@images" in caminho:
        return False
    for segmento in SEGMENTOS_RUIDO:
        if segmento in caminho and segmento not in caminho_base:
            return False
    consulta = parse_qs(p.query)
    if any(k.split(":")[0] in PAGINACAO for k in consulta) and caminho == caminho_base:
        return False
    return True


def _limpar_descricao(trecho):
    sem_links = LINK_MD.sub(" ", trecho)
    for padrao in (DATA_BR, DATA_PONTO, DATA_ISO, DATA_EXTENSO):
        sem_links = padrao.sub(" ", sem_acento(sem_links) if padrao is DATA_EXTENSO else sem_links)
    sem_lixo = LIXO_DESCRICAO.sub(" ", sem_links)
    texto = " ".join(sem_lixo.split())
    return texto if len(texto) >= 40 else ""


def publicacoes_da_listagem(texto, base, inicio, fim, minimo_titulo=15):
    """
    Publicacoes de uma listagem, com a data que as acompanha.

    A data de cada publicacao fica no trecho entre o link dela e o link da
    proxima. Em algumas listagens a data vem antes do titulo; o lado usado
    e o que deixa mais publicacoes com data, decidido pagina a pagina.
    """
    candidatos = []
    for m in LINK_MD.finditer(texto):
        titulo, url = " ".join(m.group(1).split()), m.group(2)
        if len(titulo) < minimo_titulo or not parece_publicacao(url, base):
            continue
        chave = url.split("#")[0].rstrip("/").lower()
        if candidatos and candidatos[-1]["chave"] == chave:
            if len(titulo) > len(candidatos[-1]["titulo"]):
                candidatos[-1]["titulo"] = titulo
            candidatos[-1]["fim"] = m.end()
            continue
        candidatos.append({"chave": chave, "titulo": titulo, "url": url, "inicio": m.start(), "fim": m.end()})

    # Quando a listagem guarda as publicacoes abaixo do proprio caminho, como
    # o Plone faz, os links de fora dela sao navegacao e so atrapalham.
    caminho_base = urlparse(base).path.rstrip("/").lower() + "/"
    filhos = [c for c in candidatos if urlparse(c["url"]).path.lower().startswith(caminho_base)]
    if len(filhos) >= 2:
        candidatos = filhos

    for i, c in enumerate(candidatos):
        proximo = candidatos[i + 1]["inicio"] if i + 1 < len(candidatos) else min(len(texto), c["fim"] + 600)
        anterior = candidatos[i - 1]["fim"] if i else max(0, c["inicio"] - 300)
        c["depois"] = texto[c["fim"]:proximo]
        c["antes"] = texto[anterior:c["inicio"]]

    depois = sum(1 for c in candidatos if datas_em(c["depois"]))
    antes = sum(1 for c in candidatos if datas_em(c["antes"]))
    lado = "depois" if depois >= antes else "antes"

    vistos, publicacoes = set(), []
    for c in candidatos:
        if c["chave"] in vistos:
            continue
        vistos.add(c["chave"])
        datas = datas_em(c[lado]) or datas_em(c["titulo"])
        data = datas[0] if datas else None
        hora = HORA.search(c[lado]) if data else None
        publicacoes.append({
            "titulo": c["titulo"][:200],
            "url": c["url"],
            "data": data.isoformat() if data else "",
            "hora": (hora.group(0) if hora else ""),
            "descricao": _limpar_descricao(c["depois"])[:300],
            "na_janela": bool(data and inicio <= data <= fim),
        })
    return publicacoes


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


# ---------------------------------------------------------------------------
# Feeds e JSON
# ---------------------------------------------------------------------------


def _local(tag):
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def ler_feed(corpo, inicio, fim):
    """Itens de RSS 2.0, RSS 1.0 (RDF, o do Plone) ou Atom."""
    raiz = ET.fromstring(corpo)
    if _local(raiz.tag) not in ("rss", "rdf", "feed"):
        raise ValueError(f"nao e feed: <{_local(raiz.tag)}>")
    publicacoes = []
    for no in raiz.iter():
        if _local(no.tag) not in ("item", "entry"):
            continue
        campos = {}
        for filho in no:
            nome = _local(filho.tag)
            valor = (filho.text or "").strip()
            if nome == "link" and not valor:
                if filho.get("rel", "alternate") == "alternate":
                    valor = filho.get("href", "")
            if valor and nome not in campos:
                campos[nome] = valor
        data = None
        for nome in ("pubdate", "date", "published", "issued", "updated", "modified"):
            data = data_de_campo(campos.get(nome))
            if data:
                break
        descricao = campos.get("description") or campos.get("summary") or campos.get("encoded") or campos.get("content") or ""
        descricao = " ".join(re.sub(r"<[^>]+>", " ", descricao).split())
        publicacoes.append({
            "titulo": " ".join((campos.get("title") or "").split())[:200],
            "url": campos.get("link") or no.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about", ""),
            "data": data.isoformat() if data else "",
            "descricao": descricao[:300] if len(descricao) >= 20 else "",
            "na_janela": bool(data and inicio <= data <= fim),
        })
    return publicacoes


def itens_plone(dados, inicio, fim):
    publicacoes = []
    for x in dados.get("items") or []:
        if not isinstance(x, dict) or x.get("@type") in ("Image",):
            continue
        data = data_de_campo(x.get("effective")) or data_de_campo(x.get("created"))
        publicacoes.append({
            "titulo": " ".join(str(x.get("title") or "").split())[:200],
            "url": x.get("@id", ""),
            "data": data.isoformat() if data else "",
            "descricao": " ".join(str(x.get("description") or "").split())[:300],
            "na_janela": bool(data and inicio <= data <= fim),
            "tipo": x.get("@type", ""),
        })
    return publicacoes


def primeira_lista_de_objetos(dados, profundidade=0):
    """A primeira lista de dicionarios dentro de um JSON qualquer."""
    if profundidade > 4:
        return []
    if isinstance(dados, list) and dados and all(isinstance(x, dict) for x in dados[:5]):
        return dados
    if isinstance(dados, dict):
        for valor in dados.values():
            achado = primeira_lista_de_objetos(valor, profundidade + 1)
            if achado:
                return achado
    return []


def _campo(obj, *pistas):
    for chave, valor in obj.items():
        if isinstance(valor, dict) and "rendered" in valor:
            valor = valor["rendered"]
        if any(p in chave.lower() for p in pistas) and isinstance(valor, (str, int, float)) and str(valor).strip():
            return str(valor)
    return ""


def itens_json_generico(lista, inicio, fim, montar_url=None):
    publicacoes = []
    for x in lista:
        titulo = _campo(x, "title", "titulo")
        data = data_de_campo(_campo(x, "pubdate", "data", "date", "effective", "created"))
        descricao = re.sub(r"<[^>]+>", " ", _campo(x, "assunto", "description", "descricao", "ementa", "excerpt", "content", "resumo"))
        url = montar_url(x) if montar_url else _campo(x, "link", "url", "@id")
        publicacoes.append({
            "titulo": " ".join(re.sub(r"<[^>]+>", " ", titulo).split())[:200],
            "url": url,
            "data": data.isoformat() if data else "",
            "descricao": " ".join(descricao.split())[:300],
            "na_janela": bool(data and inicio <= data <= fim),
        })
    return publicacoes


def pistas_de_api(html_texto):
    """Enderecos de API citados no HTML de uma pagina montada por JavaScript."""
    achados = re.findall(r"""["'](https?://[^"'\s]+?/api/[^"'\s]{3,120}|/api/[^"'\s]{3,120})["']""", html_texto[:500_000])
    return sorted(set(achados))[:12]


# ---------------------------------------------------------------------------
# Cliente HTTP educado
# ---------------------------------------------------------------------------

DESAFIOS = (
    "just a moment", "attention required", "cf-browser-verification", "cf-chl",
    "are you a robot", "robot check", "incapsula", "request unsuccessful",
    "perfdrive", "access denied", "acesso negado", "captcha",
)


class Cliente:
    def __init__(self, agente=USER_AGENT):
        self.agente = agente
        self.ultimo = {}
        self.robots = {}
        self.requisicoes = 0

    def _esperar(self, host, atraso):
        anterior = self.ultimo.get(host)
        if anterior is not None:
            falta = atraso - (time.monotonic() - anterior)
            if falta > 0:
                time.sleep(falta)
        self.ultimo[host] = time.monotonic()

    def regras(self, url):
        p = urlparse(url)
        host = p.netloc.lower()
        if host not in self.robots:
            endereco = f"{p.scheme}://{p.netloc}/robots.txt"
            leitor = urllib.robotparser.RobotFileParser(endereco)
            resposta = self._baixar(endereco, respeitar_robots=False)
            if resposta["status"] is None:
                # Falha de rede, nao resposta do site: uma segunda tentativa.
                time.sleep(5)
                resposta = self._baixar(endereco, respeitar_robots=False)
            info = {"url": endereco, "status": resposta["status"], "crawl_delay": None,
                    "erro": resposta["erro"]}
            if resposta["status"] == 200 and "<html" not in resposta["texto"][:500].lower():
                leitor.parse(resposta["texto"].splitlines())
                try:
                    info["crawl_delay"] = leitor.crawl_delay(AGENTE)
                except Exception:
                    pass
            elif resposta["status"] in (401, 403):
                leitor.disallow_all = True
            elif isinstance(resposta["status"], int) and 400 <= resposta["status"] < 500:
                leitor.allow_all = True
            elif resposta["status"] == 200:
                leitor.allow_all = True  # robots.txt respondido com pagina HTML: sem regras
            else:
                leitor.disallow_all = True  # 5xx ou rede: RFC 9309 manda assumir proibido
            if resposta["status"] is None:
                info["regras"] = "inacessivel, tratado como proibido"
            else:
                info["regras"] = "proibe tudo" if leitor.disallow_all else "sem regras" if leitor.allow_all else "lidas"
            self.robots[host] = (leitor, info)
        return self.robots[host]

    def baixar(self, url, aceitar=None):
        return self._baixar(url, aceitar=aceitar, respeitar_robots=True)

    def _baixar(self, url, aceitar=None, respeitar_robots=True):
        host = urlparse(url).netloc.lower()
        registro = {"url": url, "status": None, "erro": "", "tipo": "", "bytes": 0, "ms": 0,
                    "url_final": url, "texto": "", "corpo": b"", "bloqueio": ""}
        atraso = INTERVALO_HOST
        if respeitar_robots:
            leitor, info = self.regras(url)
            if not leitor.can_fetch(AGENTE, url):
                registro["status"] = "robots"
                registro["erro"] = "robots.txt nao permite"
                return registro
            atraso = max(INTERVALO_HOST, float(info.get("crawl_delay") or 0))
        self._esperar(host, atraso)
        pedido = urllib.request.Request(url, headers={
            "User-Agent": self.agente,
            "Accept": aceitar or "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9",
            "Accept-Encoding": "gzip, deflate",
        })
        comeco = time.monotonic()
        corpo, cabecalhos = b"", None
        try:
            with urllib.request.urlopen(pedido, timeout=TIMEOUT) as resposta:
                corpo = resposta.read(LIMITE_BYTES + 1)
                registro["status"] = resposta.status
                registro["url_final"] = resposta.geturl()
                cabecalhos = resposta.headers
        except urllib.error.HTTPError as erro:
            registro["status"] = erro.code
            registro["erro"] = f"HTTP {erro.code}"
            cabecalhos = erro.headers
            try:
                corpo = erro.read(300_000)
            except Exception:
                corpo = b""
        except Exception as erro:
            registro["erro"] = " ".join(str(erro).split())[:200]
        registro["ms"] = int((time.monotonic() - comeco) * 1000)
        self.requisicoes += 1
        if cabecalhos is not None:
            registro["tipo"] = cabecalhos.get("Content-Type", "")
            codificacao = (cabecalhos.get("Content-Encoding") or "").lower()
            try:
                if "gzip" in codificacao:
                    corpo = gzip.decompress(corpo)
                elif "deflate" in codificacao:
                    corpo = zlib.decompress(corpo)
            except Exception:
                pass
            charset = cabecalhos.get_content_charset()
        else:
            charset = None
        registro["bytes"] = len(corpo)
        registro["corpo"] = corpo
        registro["texto"] = _decodificar(corpo, charset)
        registro["bloqueio"] = _bloqueio(registro["status"], registro["texto"])
        return registro


def _decodificar(corpo, charset):
    if not corpo:
        return ""
    candidatos = [charset] if charset else []
    declarado = re.search(rb"""charset=["']?([\w-]+)""", corpo[:3000], re.I)
    if declarado:
        candidatos.append(declarado.group(1).decode("ascii", "ignore"))
    for nome in candidatos + ["utf-8"]:
        try:
            return corpo.decode(nome)
        except (LookupError, UnicodeDecodeError):
            continue
    return corpo.decode("latin-1", "replace")


def _bloqueio(status, texto):
    if status in (401, 403, 429):
        return f"HTTP {status}"
    visivel = re.sub(r"<[^>]+>", " ", texto[:60_000])
    if len(" ".join(visivel.split())) < 3000:
        amostra = texto[:60_000].lower()
        for marca in DESAFIOS:
            if marca in amostra:
                return marca
    return ""


def enxuto(registro):
    """O registro de uma requisicao, sem o corpo."""
    return {k: v for k, v in registro.items() if k not in ("texto", "corpo")}


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
