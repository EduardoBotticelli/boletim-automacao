"""
Coleta sem Firecrawl: download direto, APIs publicas e leitura das listagens.

O plano gratuito do Firecrawl da 1.000 creditos por mes, e a coleta de antes
gastava 156 por execucao. A investigacao de 30/09 (docs/coleta-sem-firecrawl.md)
mostrou que a maior parte das fontes entrega titulo, data, link e descricao sem
ele. Este modulo faz essa coleta e devolve as publicacoes ja separadas.

Cada fonte declara no fontes.json como e coletada ("coleta"):

  html       listagem do proprio site, lida no HTML (gov.br classico, EPE, CCEE)
  volto      API do Volto, o frontend do Plone 6 (ANATEL, ANVISA, ANPD, SUSEP)
  api_bcb    busca de normativos do Banco Central
  receita    tabela de resultados do SIJUT da Receita Federal
  b3         ofícios e comunicados da B3
  anp_ano    pagina do ano corrente das consultas e pautas da ANP
  wordpress  listagem mais a API do WordPress (Sinoreg-ES / Kollemata)
  firecrawl  a coleta de antes, para quem nao tem alternativa gratuita

Qualquer falha levanta FalhaColeta, e quem chama cai para o Firecrawl naquela
fonte, registrando o motivo. Nunca se tenta contornar bloqueio: 401, 403, 429,
pagina de desafio ou robots.txt que proibe viram FalhaColeta, e so.

Respeito ao site: identificacao no User-Agent, robots.txt lido em cada host e
INTERVALO_HOST segundos entre requisicoes ao mesmo host.
"""

import datetime
import email.utils
import gzip
import http.cookiejar
import html
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
import zlib
from collections import Counter
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Sao_Paulo")
AGENTE = "BoletimRadarBot"
USER_AGENT = (
    f"{AGENTE}/1.0 (coleta automatizada de publicacoes oficiais para boletim "
    "juridico; uma visita por pagina ao dia)"
)
INTERVALO_HOST = 3.0
TIMEOUT = 30
LIMITE_BYTES = 6_000_000


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
        # Cookies entre requisicoes, como um navegador: a paginacao da Receita
        # depende da sessao aberta na primeira pagina.
        self.abridor = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
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

    def baixar(self, url, aceitar=None, extras=None):
        return self._baixar(url, aceitar=aceitar, respeitar_robots=True, extras=extras)

    def _baixar(self, url, aceitar=None, respeitar_robots=True, extras=None):
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
            **(extras or {}),
        })
        comeco = time.monotonic()
        corpo, cabecalhos = b"", None
        try:
            with self.abridor.open(pedido, timeout=TIMEOUT) as resposta:
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
            registro["tamanho_declarado"] = cabecalhos.get("Content-Range") or cabecalhos.get("Content-Length") or ""
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
# Coleta de producao
# ---------------------------------------------------------------------------

LIMITE_TEXTO = 60_000
MARCAS_CONTEUDO = ('id="content-core"', 'id="content"')
BCB_BUSCA = (
    "https://www.bcb.gov.br/api/search/app/normativos/buscanormativos?"
    "querytext=ContentType:normativo%20AND%20contentSource:normativos"
    "&rowlimit={linhas}&startrow=0&sortlist=Data1OWSDATE:descending{filtro}"
)
TITULO_B3 = re.compile(r"\[(\d{2})/(\d{2})/(\d{2}) ([^\]]+)\]\((https?://[^\s)]+)\)")
PDF_B3 = re.compile(r"\[Download do Documento\]\((https?://[^\s)]+)\)")
LINHA_RECEITA = re.compile(r"<tr[^>]*class=['\"]linhaResultados['\"][^>]*>", re.I)


class FalhaColeta(Exception):
    """O metodo gratuito nao funcionou; a fonte cai para o Firecrawl."""


def novo_cliente():
    agente = USER_AGENT
    if os.getenv("COLETA_CONTATO"):
        agente = agente[:-1] + f"; contato: {os.environ['COLETA_CONTATO']})"
    return Cliente(agente)


def _exigir(registro, contexto):
    if registro["status"] == "robots":
        raise FalhaColeta(f"{contexto}: o robots.txt não permite")
    if registro["bloqueio"]:
        raise FalhaColeta(f"{contexto}: bloqueio ({registro['bloqueio']})")
    if registro["status"] != 200:
        raise FalhaColeta(f"{contexto}: {registro['erro'] or 'HTTP ' + str(registro['status'])}")
    return registro


def _json(registro, contexto):
    try:
        return json.loads(registro["texto"])
    except ValueError:
        raise FalhaColeta(f"{contexto}: a resposta não é JSON ({registro['tipo'] or 'sem tipo'})") from None


def _regiao_de_conteudo(html_texto):
    """A regiao de conteudo do Plone, sem o menu do gov.br, quando existe."""
    for marca in MARCAS_CONTEUDO:
        posicao = html_texto.find(marca)
        if posicao != -1:
            return html_texto[posicao:]
    return ""


def _sem_navegacao(publicacoes):
    """
    Em listagem que mostra data, link sem data e menu: sai. Em listagem que
    nao mostra data, nada sai, porque sem data nao da para distinguir.
    """
    datadas = [p for p in publicacoes if p.get("data")]
    if len(datadas) >= 3 and len(datadas) >= len(publicacoes) / 2:
        return datadas
    return publicacoes


def listagem_html(cliente, fonte, inicio, fim):
    registro = _exigir(cliente.baixar(fonte["url"]), "listagem")
    base = registro["url_final"]
    regiao = _regiao_de_conteudo(registro["texto"])
    publicacoes, texto = [], ""
    for trecho in ([regiao] if regiao else []) + [registro["texto"]]:
        texto = ler_html(trecho, base).texto()
        publicacoes = publicacoes_da_listagem(texto, base, inicio, fim)
        if fonte.get("padrao_link"):
            publicacoes = [p for p in publicacoes if fonte["padrao_link"] in p["url"]]
        if publicacoes:
            break
    publicacoes = _sem_navegacao(publicacoes)
    return {"publicacoes": publicacoes, "listadas": len(publicacoes), "texto": texto}


def api_volto(cliente, fonte, inicio, fim):
    p = urlparse(fonte["url"])
    partes = [x for x in p.path.split("/") if x]
    site, caminho = partes[0], "/".join(partes[1:])
    url = (f"{p.scheme}://{p.netloc}/{site}/++api++/{caminho}/@search?portal_type=News%20Item"
           "&sort_on=effective&sort_order=descending&b_size=30"
           "&metadata_fields=effective&metadata_fields=created&metadata_fields=Description")
    dados = _json(_exigir(cliente.baixar(url, aceitar="application/json"), "API do Volto"), "API do Volto")
    publicacoes = itens_plone(dados, inicio, fim)
    for publicacao in publicacoes:
        publicacao["url"] = publicacao["url"].replace("/++api++", "")
    texto = "\n".join(f"{p['data']} | {p['titulo']} | {p['url']} | {p['descricao']}" for p in publicacoes)
    return {"publicacoes": publicacoes, "listadas": len(publicacoes), "texto": texto}


def _url_bcb(item):
    tipo = _campo(item, "tipodonormativo", "tipo")
    numero = _campo(item, "numeroowsnmbr", "numero")
    if tipo and numero:
        return f"https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo?tipo={tipo}&numero={numero.split('.')[0]}"
    return _campo(item, "link", "url", "path")


def api_bcb(cliente, fonte, inicio, fim):
    filtro = f"&refinementfilters=Data:range(datetime({inicio.isoformat()}),datetime({(fim + datetime.timedelta(days=1)).isoformat()}))"
    dados = _json(_exigir(cliente.baixar(BCB_BUSCA.format(linhas=100, filtro=filtro), aceitar="application/json"), "API do BC"), "API do BC")
    publicacoes = itens_json_generico(primeira_lista_de_objetos(dados), inicio, fim, montar_url=_url_bcb)
    listadas = len(publicacoes)
    if not publicacoes:
        # Janela sem normativo acontece; confere se a API continua respondendo.
        ultimos = _json(_exigir(cliente.baixar(BCB_BUSCA.format(linhas=5, filtro=""), aceitar="application/json"), "API do BC"), "API do BC")
        listadas = len(primeira_lista_de_objetos(ultimos))
    texto = "\n".join(f"{p['data']} | {p['titulo']} | {p['url']} | {p['descricao']}" for p in publicacoes)
    return {"publicacoes": publicacoes, "listadas": listadas, "texto": texto}


def ler_linhas_receita(html_texto):
    """Uma publicacao por linha da tabela de resultados do SIJUT."""
    publicacoes = []
    for pedaco in LINHA_RECEITA.split(html_texto)[1:]:
        linha = re.sub(r"<!--.*?-->", "", pedaco.split("</tr>")[0], flags=re.S)
        celulas = [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", c)).split())
                   for c in re.findall(r"<td[^>]*>(.*?)</td>", linha, re.S | re.I)]
        ato = re.search(r"consulta/externa/(\d+)", linha) or re.search(r"idAto=(\d+)", pedaco)
        if len(celulas) < 4 or not ato:
            continue
        tipo, numero, orgao = celulas[0], celulas[1], celulas[2]
        datas = datas_em(celulas[3])
        publicacoes.append({
            "titulo": " ".join(f"{tipo} {orgao} nº {numero}".split()),
            "url": f"https://normasinternet2.receita.fazenda.gov.br/#/consulta/externa/{ato.group(1)}",
            "data": datas[0].isoformat() if datas else "",
            "descricao": (celulas[4] if len(celulas) > 4 else "")[:400],
            "orgao": orgao,
        })
    return publicacoes


def filtrar_por_orgao(publicacoes, orgaos):
    """
    So os atos dos orgaos da lista vao ao Gemini. Na Receita, a lista traz os
    orgaos centrais (Cosit, Corat, Sutri...); os atos de alfandegas,
    delegacias, inspetorias e superintendencias regionais (ALF/BSB, DRF/SOR,
    IRF/SLS, SRRF08) ficam de fora. Em 30/09 eram 39 dos 52 atos da janela.

    O orgao vale pela parte antes da barra: 'ALF/BSB' e a alfandega de
    Brasilia, 'RFB/PGFN' e ato conjunto da RFB. Ato sem orgao informado
    continua indo, porque nao da para saber de onde e.

    Nada some: o ato excluido fica na coleta com 'enviar' falso e o motivo,
    e vai assim para o dossier guardado. Devolve a contagem por orgao.
    """
    aceitos = {sem_acento(o).strip().lower() for o in orgaos if str(o).strip()}
    excluidos = Counter()
    for publicacao in publicacoes:
        orgao = (publicacao.get("orgao") or "").strip()
        raiz = orgao.split("/")[0].strip()
        if not publicacao.get("enviar") or not raiz or sem_acento(raiz).lower() in aceitos:
            continue
        publicacao["enviar"] = False
        publicacao["excluida_pelo_filtro"] = f"Órgão {orgao} fora da lista de órgãos da fonte."
        excluidos[raiz] += 1
    return dict(excluidos.most_common())


def tabela_receita(cliente, fonte, inicio, fim, paginas=6):
    """
    A consulta do SIJUT ja filtrada pela data de publicacao da janela
    (tipoData=2, dt_inicio, dt_fim), em ordem de publicacao, seguindo a
    paginacao ate acabar. Sem o filtro, a pagina 1 traz os 24 atos mais
    recentes e a paginacao volta vazia.
    """
    publicacoes, textos, aviso = [], [], ""
    filtro = f"&dt_inicio={inicio.strftime('%d/%m/%Y')}&dt_fim={fim.strftime('%d/%m/%Y')}".replace("/", "%2F")
    base = fonte["url"] if "dt_inicio=" in fonte["url"] else fonte["url"] + filtro
    for pagina in range(1, paginas + 1):
        url = re.sub(r"([?&])p=\d+", rf"\g<1>p={pagina}", base)
        registro = _exigir(cliente.baixar(url), "tabela da Receita")
        linhas = ler_linhas_receita(registro["texto"])
        if pagina == 2 and not linhas and len(publicacoes) >= 100:
            # Com o filtro da janela, pagina 2 vazia quer dizer que acabou. So
            # desconfia quando a primeira veio grande a ponto de parecer corte.
            aviso = f"A página 1 trouxe {len(publicacoes)} atos e a página 2 veio vazia: pode haver atos da janela fora da coleta."
        publicacoes.extend(linhas)
        textos.extend(f"{p['data']} | {p['titulo']} | {p['url']} | {p['descricao']}" for p in linhas)
        datas = [p["data"] for p in linhas if p["data"]]
        if not linhas or not datas or min(datas) < inicio.isoformat() or url == fonte["url"] and "p=" not in url:
            break
    return {"publicacoes": publicacoes, "listadas": len(publicacoes), "texto": "\n".join(textos), "aviso": aviso}


def ler_oficios_b3(texto):
    """Cada oficio e um titulo 'dd/mm/aa codigo titulo', uma chamada e o PDF."""
    achados = list(TITULO_B3.finditer(texto))
    publicacoes = []
    for posicao, achado in enumerate(achados):
        dia, mes, ano, titulo, ancora = achado.groups()
        fim_trecho = achados[posicao + 1].start() if posicao + 1 < len(achados) else len(texto)
        trecho = texto[achado.end():fim_trecho]
        pdf = PDF_B3.search(trecho)
        try:
            data = datetime.date(2000 + int(ano), int(mes), int(dia)).isoformat()
        except ValueError:
            data = ""
        publicacoes.append({
            "titulo": " ".join(titulo.split()),
            "url": pdf.group(1) if pdf else ancora,
            "data": data,
            "descricao": " ".join(LINK_MD.sub(" ", trecho).split())[:400],
        })
    return publicacoes


def listagem_b3(cliente, fonte, inicio, fim):
    registro = _exigir(cliente.baixar(fonte["url"]), "listagem da B3")
    texto = ler_html(registro["texto"], registro["url_final"]).texto()
    publicacoes = ler_oficios_b3(texto)
    return {"publicacoes": publicacoes, "listadas": len(publicacoes), "texto": texto}


def pagina_do_ano(cliente, fonte, inicio, fim):
    """
    As consultas e as pautas da ANP ficam em abas por ano, cada uma carregada
    de uma pagina propria (.../2026). Le a do ano da janela.
    """
    publicacoes, textos, achou_pagina = [], [], False
    for ano in sorted({inicio.year, fim.year}):
        url = f"{fonte['url'].rstrip('/')}/{ano}"
        registro = cliente.baixar(url)
        if registro["status"] == 404:
            continue
        _exigir(registro, f"página de {ano}")
        achou_pagina = True
        base = registro["url_final"].rstrip("/")
        texto = ler_html(_regiao_de_conteudo(registro["texto"]) or registro["texto"], base).texto()
        textos.append(texto)
        publicacoes.extend(
            p for p in publicacoes_da_listagem(texto, base, inicio, fim)
            if urlparse(p["url"]).path.rstrip("/").lower().startswith(urlparse(base).path.lower() + "/")
        )
    if not achou_pagina:
        raise FalhaColeta("nenhuma página de ano encontrada")
    return {"publicacoes": publicacoes, "listadas": len(publicacoes), "texto": "\n\n".join(textos)}


def wordpress(cliente, fonte, inicio, fim):
    """A listagem da fonte mais as postagens do site na janela, pela API."""
    listagem = listagem_html(cliente, fonte, inicio, fim)
    p = urlparse(fonte["url"])
    api = (f"{p.scheme}://{p.netloc}/wp-json/wp/v2/posts?per_page=20&_fields=date,link,title,excerpt"
           f"&after={inicio.isoformat()}T00:00:00")
    dados = _json(_exigir(cliente.baixar(api, aceitar="application/json"), "API do WordPress"), "API do WordPress")
    postagens = itens_json_generico(dados if isinstance(dados, list) else [], inicio, fim)
    return {
        "publicacoes": listagem["publicacoes"] + postagens,
        "listadas": listagem["listadas"] + len(postagens),
        "texto": listagem["texto"],
    }


METODOS = {
    "html": listagem_html,
    "volto": api_volto,
    "api_bcb": api_bcb,
    "receita": tabela_receita,
    "b3": listagem_b3,
    "anp_ano": pagina_do_ano,
    "wordpress": wordpress,
}


TITULO_UTILITARIO = re.compile(r"^(link para )?(copiar|compartilh|imprimir|ir para|voltar|acessibilidade)", re.I)


def _normalizar(publicacao):
    limpo = {k: " ".join(html.unescape(str(publicacao.get(k) or "")).split())
             for k in ("titulo", "url", "data", "hora", "descricao")}
    limpo["url"] = limpo["url"].replace(" ", "%20")
    if publicacao.get("orgao"):
        limpo["orgao"] = " ".join(str(publicacao["orgao"]).split())
    return limpo


def marcar_envio(publicacoes, inicio, fim, futuras=False):
    """
    O que vai ao Gemini: o que cai na janela e o que nao tem data. Sem data
    nunca e descartado, porque nao da para saber se e da janela. Nas paginas
    de consulta da ANP, a data mostrada pode ser a da audiencia, entao data
    futura tambem vai.
    """
    for publicacao in publicacoes:
        data = publicacao.get("data") or ""
        publicacao["na_janela"] = bool(data) and inicio.isoformat() <= data[:10] <= fim.isoformat()
        publicacao["enviar"] = publicacao["na_janela"] or not data or (futuras and data[:10] > fim.isoformat())
    return publicacoes


def coletar(cliente, fonte, inicio, fim):
    """
    Coleta uma fonte pelo metodo gratuito dela.

    Devolve {"publicacoes", "listadas", "texto", "requisicoes"}. 'listadas' e
    quanto a fonte expoe, dentro ou fora da janela: e o que diz se o leitor
    funcionou. Levanta FalhaColeta quando nao da.
    """
    metodo = fonte.get("coleta", "firecrawl")
    if metodo not in METODOS:
        raise FalhaColeta(f"método sem coleta gratuita: {metodo}")
    antes = cliente.requisicoes
    try:
        resultado = METODOS[metodo](cliente, fonte, inicio, fim)
    except FalhaColeta:
        raise
    except (ValueError, KeyError, TypeError, AttributeError, IndexError) as erro:
        raise FalhaColeta(f"resposta inesperada: {' '.join(str(erro).split())[:160]}") from None
    publicacoes = [_normalizar(p) for p in resultado["publicacoes"]]
    publicacoes = [p for p in publicacoes if p["titulo"] and not TITULO_UTILITARIO.match(p["titulo"])]
    publicacoes = marcar_envio(publicacoes, inicio, fim, futuras=metodo == "anp_ano")
    excluidas = filtrar_por_orgao(publicacoes, fonte["orgaos"]) if fonte.get("orgaos") else {}
    return {
        "publicacoes": publicacoes,
        "listadas": resultado["listadas"],
        "texto": resultado["texto"][:LIMITE_TEXTO],
        "requisicoes": cliente.requisicoes - antes,
        "aviso": resultado.get("aviso", ""),
        "excluidas_por_orgao": excluidas,
    }
