"""
Diario Oficial da Uniao pela leitura do jornal, via Firecrawl.

O in.gov.br derruba a conexao que vem do runner do GitHub e o INLABS esta
fora do ar; o Firecrawl le o in.gov.br normalmente. A leitura do jornal
(in.gov.br/leiturajornal?secao=dou1&data=DD-MM-AAAA), baixada em HTML bruto,
traz embutido um JSON com todos os atos da edicao: titulo, tipo, orgao,
pagina e endereco de cada um. Em 02/10/2026 foram 415 atos na Secao 1 e
2.334 na Secao 3, os mesmos totais da busca do in.gov.br.

O caminho, por execucao:

1. uma leitura por secao (1 credito cada), com max_age=0 para nao receber a
   edicao em cache de antes de ela sair inteira;
2. o filtro por orgao do dou.json decide os Radares de cada ato; quem nao
   casa com nenhuma regra fica so na contagem do log;
3. abre so os atos que passaram (1 credito cada), para tirar a ementa e o
   trecho do texto. Atos da mesma serie abrem um so, e ha um teto por
   execucao; o ato que nao abre entra do mesmo jeito, com o comeco do texto
   que a leitura do jornal ja traz, e o motivo fica registrado.

Nenhuma IA: os Radares vem do filtro, e o resumo e o trecho, do proprio ato.
"""

import datetime
import html
import json
import re
import time
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CONFIG = BASE / "dou.json"
LEITURA = "https://www.in.gov.br/leiturajornal?secao={secao}&data={data}"
ATO = "https://www.in.gov.br/web/dou/-/{endereco}"
TAMANHO_RESUMO = 320
# Ordem para abrir quando o teto aperta: o que e norma vem antes do que e
# expediente. Tipo fora da lista vai para o fim, na ordem da edicao.
PRIORIDADE_TIPOS = (
    "Lei", "Lei Complementar", "Medida Provisória", "Decreto", "Resolução", "Instrução Normativa", "Convênio",
    "Ajuste", "Ato Normativo", "Portaria Normativa", "Circular", "Deliberação", "Súmula", "Provimento",
    "Portaria", "Portaria Conjunta", "Despacho Decisório", "Decisão", "Acórdão", "Ato Declaratório",
    "Despacho", "Ato", "Edital", "Aviso",
)
GABINETES = ("gabinete", "secretaria-executiva", "secretaria executiva")


class FalhaDou(Exception):
    """A leitura do jornal ou a pagina do ato nao veio como esperado."""


def carregar_config(caminho=CONFIG):
    return json.loads(Path(caminho).read_text(encoding="utf-8"))


def normalizar(valor):
    sem = unicodedata.normalize("NFKD", str(valor or "")).encode("ascii", "ignore").decode()
    return " ".join(sem.lower().split())


def _limpo(fragmento):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", str(fragmento or ""))).split())


def data_iso(valor):
    """'02/10/2026' -> '2026-10-02'; vazio se nao der para ler."""
    try:
        return datetime.datetime.strptime(str(valor).strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return ""


def cortar(texto, tamanho):
    """Corta no fim de frase (ou de palavra) antes de 'tamanho', com reticencias."""
    texto = " ".join(str(texto or "").split())
    if len(texto) <= tamanho:
        return texto
    corte = texto.rfind(". ", 0, tamanho)
    if corte > tamanho // 2:
        return texto[: corte + 1] + " [...]"
    corte = texto.rfind(" ", 0, tamanho)
    return texto[: corte if corte > 0 else tamanho].rstrip(" ,;:") + " [...]"


# ---------------------------------------------------------------------------
# Leitura do jornal
# ---------------------------------------------------------------------------


def ler_leitura(html_bruto, secao):
    """Os atos que a leitura do jornal traz no JSON embutido (<script id="params">)."""
    achado = re.search(r'<script[^>]*id="params"[^>]*>(.*?)</script>', html_bruto or "", re.S)
    if not achado:
        raise FalhaDou("a leitura do jornal não trouxe o JSON dos atos")
    try:
        dados = json.loads(achado.group(1))
    except json.JSONDecodeError:
        dados = json.loads(html.unescape(achado.group(1)))
    atos = []
    for posicao, item in enumerate(dados.get("jsonArray") or []):
        titulo = _limpo(item.get("title") or item.get("titulo"))
        conteudo = _limpo(item.get("content"))
        if titulo and conteudo.startswith(titulo):
            conteudo = conteudo[len(titulo):].strip()
        niveis = item.get("hierarchyList") or [n for n in str(item.get("hierarchyStr") or "").split("/") if n]
        endereco = str(item.get("urlTitle") or "").strip()
        atos.append({
            "secao": secao,
            "posicao": posicao,
            "titulo": titulo,
            "tipo": _limpo(item.get("artType")),
            "orgao": _limpo(item.get("hierarchyStr")),
            "niveis": [_limpo(n) for n in niveis],
            "url": ATO.format(endereco=endereco) if endereco else "",
            "pagina": int(re.sub(r"\D", "", str(item.get("numberPage") or "")) or 0),
            "edicao": str(item.get("editionNumber") or ""),
            "data": data_iso(item.get("pubDate")),
            # O comeco do texto, como a leitura do jornal mostra (cerca de 400
            # caracteres, terminando em "...").
            "inicio_do_texto": re.sub(r"\.\.\.$", "", conteudo).strip(),
        })
    return atos


# ---------------------------------------------------------------------------
# Filtro por orgao
# ---------------------------------------------------------------------------


def casa(ato, regra, excluidas=()):
    niveis = [normalizar(n) for n in ato["niveis"]]
    if normalizar(regra["orgao"]) not in niveis:
        return False
    if regra.get("unidade") and normalizar(regra["unidade"]) not in niveis:
        return False
    # Na regra com termos (Mais Medicos), o termo decide: a exclusao geral de
    # unidades regionais e administrativas nao se aplica a ela.
    gerais = [] if regra.get("termos") else list(excluidas)
    for trecho in gerais + list(regra.get("excluir") or []):
        alvo = normalizar(trecho)
        if any(alvo in nivel for nivel in niveis):
            return False
    if regra.get("tipos") and normalizar(ato["tipo"]) not in {normalizar(t) for t in regra["tipos"]}:
        return False
    if regra.get("termos"):
        texto = normalizar(ato["titulo"] + " " + ato["inicio_do_texto"])
        if not any(normalizar(t) in texto for t in regra["termos"]):
            return False
    return True


def radares_do_ato(ato, radares, excluidas=()):
    """Os Radares cujas regras o ato satisfaz, na ordem do dou.json, e a regra que valeu em cada um."""
    achados = {}
    for slug, regras in radares.items():
        regra = next((r for r in regras if casa(ato, r, excluidas)), None)
        if regra:
            achados[slug] = regra["orgao"] + (f" / {regra['unidade']}" if regra.get("unidade") else "")
    return achados


# ---------------------------------------------------------------------------
# Quais atos abrir
# ---------------------------------------------------------------------------


def prioridade(tipo):
    alvo = normalizar(tipo)
    for posicao, nome in enumerate(PRIORIDADE_TIPOS):
        if alvo == normalizar(nome):
            return posicao
    return len(PRIORIDADE_TIPOS)


def chave_de_serie(ato):
    """Mesmo orgao, mesmo tipo e o mesmo comeco de texto, sem os numeros."""
    return (ato["orgao"], normalizar(ato["tipo"]), re.sub(r"\d+", "#", normalizar(ato["inicio_do_texto"]))[:200])


def escolher_para_abrir(atos, limite):
    """
    Marca em cada ato se ele abre. Devolve os que abrem, ja na ordem.

    A ordem e a prioridade do tipo e, dentro do tipo, a ordem da edicao. O
    primeiro de cada serie abre (se couber no teto); os outros da serie nao,
    porque o texto deles repete o do primeiro ate os nomes.
    """
    abrir, series = [], {}
    for ato in sorted(atos, key=lambda a: (prioridade(a["tipo"]), a["secao"], a["posicao"])):
        chave = chave_de_serie(ato)
        if chave in series:
            ato["nao_aberto"] = "série: mesmo órgão, tipo e começo de texto de outro ato"
            ato["serie_de"] = series[chave]["url"]
            continue
        series[chave] = ato
        if len(abrir) >= limite:
            ato["nao_aberto"] = f"teto de {limite} atos abertos por execução"
            continue
        abrir.append(ato)
    return abrir


# ---------------------------------------------------------------------------
# Pagina do ato
# ---------------------------------------------------------------------------


class _LeitorAto(HTMLParser):
    """Os blocos de texto dentro de <div class="texto-dou">, com a classe de cada um."""

    BLOCOS = {"p", "td", "th", "li", "h1", "h2", "h3", "h4"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.profundidade = 0  # dentro do texto-dou, quantos div abertos
        self.blocos = []
        self.atual = None
        self.achou = False

    def handle_starttag(self, tag, attrs):
        classes = (dict(attrs).get("class") or "").split()
        if tag == "div":
            if self.profundidade:
                self.profundidade += 1
            elif "texto-dou" in classes:
                self.profundidade, self.achou = 1, True
            return
        if self.profundidade and tag in self.BLOCOS:
            self._fechar()
            self.atual = [" ".join(classes), []]
        elif self.profundidade and tag == "br" and self.atual:
            self.atual[1].append(" ")

    def handle_endtag(self, tag):
        if tag == "div" and self.profundidade:
            self.profundidade -= 1
            if not self.profundidade:
                self._fechar()
        elif self.profundidade and tag in self.BLOCOS:
            self._fechar()

    def handle_data(self, dados):
        if self.profundidade and self.atual is not None:
            self.atual[1].append(dados)

    def _fechar(self):
        if self.atual:
            texto = " ".join("".join(self.atual[1]).split())
            if texto:
                self.blocos.append((self.atual[0], texto))
        self.atual = None


def ler_ato(html_bruto):
    """Identificacao, ementa, paragrafos e assinatura do ato."""
    leitor = _LeitorAto()
    leitor.feed(html_bruto or "")
    leitor.close()
    if not leitor.achou:
        raise FalhaDou("a página do ato não trouxe o bloco de texto (texto-dou)")
    lido = {"identifica": "", "ementa": "", "paragrafos": [], "assinatura": []}
    for classe, texto in leitor.blocos:
        if "identifica" in classe and not lido["identifica"]:
            lido["identifica"] = texto
        elif "ementa" in classe and not lido["ementa"]:
            lido["ementa"] = texto
        elif "assina" in classe or "cargo" in classe:
            lido["assinatura"].append(texto)
        else:
            lido["paragrafos"].append(texto)
    if not (lido["identifica"] or lido["ementa"] or lido["paragrafos"]):
        raise FalhaDou("o bloco de texto do ato veio vazio")
    return lido


def resumo_e_trecho(lido, tamanho_trecho):
    """
    O resumo e a ementa; sem ementa, o comeco do primeiro paragrafo. O trecho
    vem dos paragrafos seguintes, sem repetir o que ja esta no resumo.
    """
    paragrafos = list(lido["paragrafos"])
    if lido["ementa"]:
        return lido["ementa"], cortar(" ".join(paragrafos), tamanho_trecho)
    # Sem ementa, o primeiro paragrafo as vezes e so "Processo nº ...": junta
    # os seguintes ate o tamanho do resumo.
    usados = []
    while paragrafos and (not usados or len(" ".join(usados)) < TAMANHO_RESUMO // 2):
        usados.append(paragrafos.pop(0))
    return cortar(" ".join(usados), TAMANHO_RESUMO), cortar(" ".join(paragrafos), tamanho_trecho)


# ---------------------------------------------------------------------------
# Coleta
# ---------------------------------------------------------------------------


def _baixar(fc, url, max_age=None):
    opcoes = {"formats": ["rawHtml"], "only_main_content": False}
    if max_age is not None:
        opcoes["max_age"] = max_age
    doc = fc.scrape(url, **opcoes)
    meta = getattr(doc, "metadata", None)
    creditos = getattr(meta, "credits_used", None)
    status = getattr(meta, "status_code", None)
    if isinstance(status, int) and status >= 400:
        raise FalhaDou(f"HTTP {status}")
    return getattr(doc, "raw_html", "") or "", creditos if isinstance(creditos, int) else 1


def orgao_curto(ato):
    """O nivel do orgao que identifica o ato para quem le: a autarquia ou secretaria, e nao o gabinete."""
    niveis = ato["niveis"] or [ato["orgao"]]
    if len(niveis) > 1 and not normalizar(niveis[1]).startswith(GABINETES):
        return niveis[1]
    return niveis[0]


def coletar(fc, secoes, data, config=None, esperar=None):
    """
    Coleta as secoes pedidas da edicao de 'data' (datetime.date).

    'secoes' e uma lista de codigos ('dou1', 'dou3'); 'esperar' e chamada
    antes de cada pedido ao Firecrawl (o intervalo entre pedidos do
    gerar_boletim). Devolve um registro por secao e o total de creditos:

        {"secoes": {secao: {"listados", "selecionados", "abertos", "creditos",
                            "atos", "erro"}},
         "creditos": n, "limite_atos_abertos": n}
    """
    config = config or carregar_config()
    esperar = esperar or (lambda: None)
    excluidas = config.get("unidades_excluidas") or []
    resultado = {"edicao": data.isoformat(), "secoes": {}, "creditos": 0, "limite_atos_abertos": config.get("limite_atos_abertos", 20)}
    todos = []
    for secao in secoes:
        regras = (config["secoes"].get(secao) or {}).get("radares") or {}
        registro = {"listados": 0, "selecionados": 0, "abertos": 0, "creditos": 0, "atos": [], "erro": "", "aviso": ""}
        resultado["secoes"][secao] = registro
        esperar()
        try:
            bruto, creditos = _baixar(fc, LEITURA.format(secao=secao, data=data.strftime("%d-%m-%Y")), max_age=0)
            registro["creditos"] += creditos
            atos = ler_leitura(bruto, secao)
        except Exception as erro:  # a secao fica com erro registrado e a coleta segue
            registro["creditos"] += 1
            registro["erro"] = f"{type(erro).__name__}: {erro}"[:300]
            continue
        registro["listados"] = len(atos)
        if not atos:
            registro["aviso"] = (f"A leitura do jornal de {data:%d/%m/%Y} veio sem atos: feriado, "
                                 "ou a edição ainda não tinha saído na hora da coleta.")
        for ato in atos:
            radares = radares_do_ato(ato, regras, excluidas)
            if radares:
                ato["radares"] = list(radares)
                ato["regras"] = radares
                registro["atos"].append(ato)
        registro["selecionados"] = len(registro["atos"])
        todos.extend(registro["atos"])

    tamanho = config.get("tamanho_trecho", 900)
    for ato in escolher_para_abrir(todos, resultado["limite_atos_abertos"]):
        registro = resultado["secoes"][ato["secao"]]
        esperar()
        try:
            bruto, creditos = _baixar(fc, ato["url"])
            registro["creditos"] += creditos
            lido = ler_ato(bruto)
        except Exception as erro:  # o ato entra com o comeco do texto da leitura
            registro["creditos"] += 1
            ato["nao_aberto"] = f"falha ao abrir: {type(erro).__name__}: {erro}"[:240]
            continue
        resumo, trecho = resumo_e_trecho(lido, tamanho)
        ato.update(aberto=True, resumo=resumo, trecho=trecho, identificacao=lido["identifica"])
        registro["abertos"] += 1

    for ato in todos:
        if not ato.get("aberto"):
            ato.update(aberto=False, resumo=cortar(ato["inicio_do_texto"], TAMANHO_RESUMO), trecho="")
    resultado["creditos"] = sum(r["creditos"] for r in resultado["secoes"].values())
    return resultado


def item_do_ato(ato, fonte):
    """O item do boletim.json para um ato que passou no filtro."""
    secao = re.sub(r"\D", "", ato["secao"]) or ato["secao"]
    return {
        "fonte": fonte,
        "categoria": "Diário Oficial da União",
        "titulo": f"{ato['titulo']} ({orgao_curto(ato)})",
        "url": ato["url"],
        "data_publicacao": ato["data"],
        "resumo": ato.get("resumo", ""),
        "trecho_do_ato": {"texto": ato.get("trecho", ""), "secao": secao, "pagina": ato["pagina"]} if ato.get("trecho") else None,
        "boletins_confirmados": list(ato["radares"]),
        "boletins_rejeitados": [],
        "palavras_chave_detectadas": [],
        "motivo_filtragem": "Filtro por órgão do DOU: " + "; ".join(f"{slug}: {regra}" for slug, regra in ato["regras"].items()),
        "dou": {"orgao": ato["orgao"], "tipo": ato["tipo"], "pagina": ato["pagina"], "edicao": ato["edicao"],
                "aberto": ato.get("aberto", False), "nao_aberto": ato.get("nao_aberto", "")},
    }


def resumo_para_o_log(atos):
    """Contagens por Radar, por tipo e pelo motivo de nao abrir."""
    por_radar, por_motivo = {}, {}
    for ato in atos:
        for slug in ato["radares"]:
            por_radar[slug] = por_radar.get(slug, 0) + 1
        if not ato.get("aberto"):
            motivo = (ato.get("nao_aberto") or "").split(":")[0]
            por_motivo[motivo] = por_motivo.get(motivo, 0) + 1
    return {"por_radar": por_radar, "nao_abertos_por_motivo": por_motivo}


def esperar_entre(pausa):
    """Uma funcao 'esperar' que garante 'pausa' segundos entre pedidos."""
    ultimo = [None]

    def esperar():
        if ultimo[0] is not None:
            falta = pausa - (time.monotonic() - ultimo[0])
            if falta > 0:
                time.sleep(falta)
        ultimo[0] = time.monotonic()

    return esperar


def main():
    """
    Ensaio: coleta as Secoes 1 e 3 de uma edicao e grava o resultado, sem
    passar pelo pipeline. Gasta os mesmos creditos da coleta diaria.

        python scripts/coleta_dou.py --data 02-10-2026 --saida output/ensaio_dou
    """
    import argparse
    import os
    import sys

    parser = argparse.ArgumentParser(description=main.__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", required=True, help="DD-MM-AAAA")
    parser.add_argument("--saida", default=str(BASE / "output" / "ensaio_dou"))
    parser.add_argument("--secoes", nargs="+", default=["dou1", "dou3"])
    args = parser.parse_args()
    if not os.getenv("FIRECRAWL_API_KEY"):
        raise SystemExit("FIRECRAWL_API_KEY é obrigatória.")
    from firecrawl import Firecrawl

    data = datetime.datetime.strptime(args.data, "%d-%m-%Y").date()
    config = carregar_config()
    resultado = coletar(Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"]), args.secoes, data, config, esperar_entre(6.5))
    itens = [item_do_ato(ato, config["secoes"][secao]["fonte"]) for secao, parte in resultado["secoes"].items() for ato in parte["atos"]]
    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)
    atos = [a for parte in resultado["secoes"].values() for a in parte["atos"]]
    resumo = {"edicao": resultado["edicao"], "creditos_firecrawl": resultado["creditos"], "limite_atos_abertos": resultado["limite_atos_abertos"],
              "por_secao": {s: {k: v for k, v in p.items() if k != "atos"} for s, p in resultado["secoes"].items()}, **resumo_para_o_log(atos)}
    (saida / "resultado.json").write_text(json.dumps({"resumo": resumo, "itens": itens}, ensure_ascii=False, indent=1), encoding="utf-8")
    for secao, parte in resultado["secoes"].items():
        print(f"{secao}: {parte['listados']} na edição, {parte['selecionados']} no filtro, {parte['abertos']} aberto(s), "
              f"{parte['creditos']} crédito(s){' | erro: ' + parte['erro'] if parte['erro'] else ''}")
    print(f"Por Radar: {resumo['por_radar']}")
    print(f"Não abertos: {resumo['nao_abertos_por_motivo']}")
    print(f"Créditos do Firecrawl: {resultado['creditos']}")
    return 0 if not any(p["erro"] for p in resultado["secoes"].values()) else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
