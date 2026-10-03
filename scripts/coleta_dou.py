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
2. o filtro do dou.json decide os Radares de cada ato. A Secao 1 e fonte
   generica dos nove Radares: entra o ato com palavras-chave do Radar no
   prompt.md (dois termos ou um composto; um termo basta se o orgao for de
   'reforco'). No Regulatorio, CADE, MEC e MDIC entram sempre, como no
   documento "Distribuicao de Clusters e Fontes";
3. atos repetidos viram uma noticia so: lote do mesmo orgao e tipo na
   edicao, ou serie com o mesmo texto-base (agrupar);
4. abre um ato por noticia (1 credito cada), com teto por execucao, para
   tirar a ementa e o trecho do texto. O que nao abre entra com o comeco do
   texto que a leitura do jornal ja traz, e o motivo fica registrado.

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
# Onde comeca o preambulo de competencia ("O DIRETOR-GERAL DA ANTT, no uso
# das atribuicoes..."). As palavras-chave so valem no titulo e na ementa,
# antes dele: no preambulo, toda resolucao citada e toda sigla de agencia
# viravam "dois termos" e punham no Radar ato que nao trata do tema.
PREAMBULO = re.compile(
    r"\b(?:O|A|OS|AS)\s+(?:[A-ZÁÉÍÓÚÂÊÔÃÕÇ-]+\s+){0,2}(?:DIRETOR|DIRETORA|SECRET[AÁ]RI[OA]|MINISTR[OA]|PRESIDENTE|"
    r"SUPERINTENDENTE|COORDENADOR|COORDENADORA|CHEFE|REITOR|REITORA|DELEGAD[OA]|PROCURADOR|PROCURADORA|DIRETORIA|"
    r"CONSELHO|COLEGIADO|PLEN[AÁ]RIO|GERENTE|INSPETOR|INSPETORA|COMANDANTE|AUDITOR|SUBSECRET[AÁ]RI[OA]|INTERVENTOR|"
    r"CORREGEDOR|OUVIDOR|PREFEIT[OA]|GOVERNADOR)\b|no uso d[ae]s? (?:suas )?(?:atribui|compet)"
)


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


def ementa_da_leitura(texto):
    """O comeco do texto ate o preambulo de competencia: a ementa, quando o ato tem."""
    achado = PREAMBULO.search(texto or "")
    return (texto[: achado.start()] if achado else texto or "").strip()


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
        atos[-1]["ementa_da_leitura"] = ementa_da_leitura(atos[-1]["inicio_do_texto"])
    return atos


# ---------------------------------------------------------------------------
# Filtro
# ---------------------------------------------------------------------------


def casa(ato, regra):
    """O ato casa com a regra de orgao do dou.json ('orgao', 'unidade', 'termos', 'excluir')."""
    niveis = [normalizar(n) for n in ato["niveis"]]
    if normalizar(regra["orgao"]) not in niveis:
        return False
    if regra.get("unidade") and normalizar(regra["unidade"]) not in niveis:
        return False
    for trecho in regra.get("excluir") or []:
        alvo = normalizar(trecho)
        if any(alvo in nivel for nivel in niveis):
            return False
    if regra.get("termos"):
        texto = normalizar(ato["titulo"] + " " + ato["inicio_do_texto"])
        if not any(normalizar(t) in texto for t in regra["termos"]):
            return False
    return True


def termos_dos_radares():
    """Os termos de cada Radar no prompt.md, como o sugestor sem IA os le."""
    import sugestao_sem_ia

    return sugestao_sem_ia.termos_do_prompt((BASE / "prompt.md").read_text(encoding="utf-8"))


class Filtro:
    """
    Os Radares de um ato numa secao.

    - 'orgaos': regra de orgao que, sozinha, poe o ato no Radar (o
      Regulatorio do documento);
    - 'palavras_chave_nos_radares': Radares em que o ato entra pelas
      palavras-chave do titulo e da ementa, com a regra das fontes
      genericas: dois termos do Radar ou um termo composto;
    - 'reforco': orgaos que baixam para um termo o minimo do Radar. Sem
      palavra-chave, o orgao nao basta.
    """

    def __init__(self, config, secao, termos):
        definicao = config["secoes"].get(secao) or {}
        regra = config.get("palavras_chave") or {}
        self.orgaos = definicao.get("orgaos") or {}
        self.reforco = definicao.get("reforco") or {}
        self.radares_por_palavra = definicao.get("palavras_chave_nos_radares") or []
        self.minimo = regra.get("minimo_termos", 2)
        self.minimo_reforco = regra.get("minimo_termos_com_reforco", 1)
        self.termos = termos or {}

    def radares(self, ato):
        """{slug: motivo}, na ordem dos Radares do dou.json."""
        import sugestao_sem_ia

        # Titulo e ementa, como titulo e descricao nas outras fontes genericas.
        texto = sugestao_sem_ia.sem_acento(ato["titulo"] + " " + ato.get("ementa_da_leitura", ato["inicio_do_texto"]))
        motivos, palavras = {}, {}
        for slug in list(self.radares_por_palavra) + [s for s in self.orgaos if s not in self.radares_por_palavra]:
            regra = next((r for r in self.orgaos.get(slug, []) if casa(ato, r)), None)
            if regra:
                motivos[slug] = f"órgão {regra['orgao']}" + (f" com '{regra['termos'][0]}'" if regra.get("termos") else "")
            if slug not in self.radares_por_palavra:
                continue
            casados = sorted({t.original for t in self.termos.get(slug, []) if t.casa(texto)})
            if not casados:
                continue
            reforco = next((r for r in self.reforco.get(slug, []) if casa(ato, r)), None)
            composto = any(" " in t.strip() for t in casados)
            if len(casados) >= self.minimo or composto or (reforco and len(casados) >= self.minimo_reforco):
                palavras[slug] = casados
                texto_motivo = "palavras-chave " + ", ".join(f"'{t}'" for t in casados[:4])
                if reforco and len(casados) < self.minimo and not composto:
                    texto_motivo += f" (reforço: {reforco['orgao']})"
                motivos[slug] = f"{motivos[slug]}; {texto_motivo}" if slug in motivos else texto_motivo
        ato["palavras_chave"] = sorted({t for v in palavras.values() for t in v})
        return motivos


# ---------------------------------------------------------------------------
# Agrupamento e quais atos abrir
# ---------------------------------------------------------------------------


def prioridade(tipo):
    alvo = normalizar(tipo)
    for posicao, nome in enumerate(PRIORIDADE_TIPOS):
        if alvo == normalizar(nome):
            return posicao
    return len(PRIORIDADE_TIPOS)


def chave_de_serie(ato):
    """Mesma secao, mesmo orgao, mesmo tipo e o mesmo comeco de texto, sem os numeros."""
    return (ato["secao"], ato["orgao"], normalizar(ato["tipo"]), re.sub(r"\d+", "#", normalizar(ato["inicio_do_texto"]))[:200])


def _ordem(ato):
    return (prioridade(ato["tipo"]), ato["secao"], ato["posicao"])


def agrupar(atos, config):
    """
    Junta os atos repetidos de uma edicao. Devolve a lista de grupos, cada um
    {"tipo": "lote" | "serie" | "avulso", "atos": [...]}, e marca em cada ato
    o grupo dele ('grupo') e quem o representa.

    Primeiro o lote: a partir de 'lote_a_partir_de' atos do mesmo orgao, do
    mesmo tipo e para os mesmos Radares na mesma secao (as pautas do CARF, os
    despachos sancionadores da SENACON). Depois a serie: a partir de
    'serie_a_partir_de' atos com o mesmo texto-base (as portarias conjuntas
    iguais do MEC). Os orgaos de 'nunca_agrupar' (CADE, STF) saem ato por
    ato: cada ato deles e um caso proprio.
    """
    regra = config.get("agrupamento") or {}
    lote_min = regra.get("lote_a_partir_de", 4)
    serie_min = regra.get("serie_a_partir_de", 2)
    nunca = {normalizar(n) for n in regra.get("nunca_agrupar") or []}
    elegiveis = [a for a in atos if not nunca & {normalizar(n) for n in a["niveis"]}]

    grupos, usados = [], set()
    lotes = {}
    for ato in elegiveis:
        lotes.setdefault((ato["secao"], orgao_curto(ato), normalizar(ato["tipo"]), tuple(ato["radares"])), []).append(ato)
    for membros in lotes.values():
        if len(membros) >= lote_min:
            grupos.append({"tipo": "lote", "atos": membros})
            usados.update(id(a) for a in membros)
    series = {}
    for ato in elegiveis:
        if id(ato) not in usados:
            series.setdefault(chave_de_serie(ato) + (tuple(ato["radares"]),), []).append(ato)
    for membros in series.values():
        if len(membros) >= serie_min:
            grupos.append({"tipo": "serie", "atos": membros})
            usados.update(id(a) for a in membros)
    grupos += [{"tipo": "avulso", "atos": [a]} for a in atos if id(a) not in usados]

    grupos.sort(key=lambda g: min((a["secao"], a["posicao"]) for a in g["atos"]))
    for numero, grupo in enumerate(grupos, 1):
        grupo["atos"].sort(key=lambda a: a["posicao"])
        grupo["representante"] = min(grupo["atos"], key=_ordem)
        grupo["id"] = f"{grupo['atos'][0]['secao']}-{numero}"
        for ato in grupo["atos"]:
            ato["grupo"] = {"id": grupo["id"], "tipo": grupo["tipo"], "tamanho": len(grupo["atos"]),
                            "representante": ato is grupo["representante"]}
    return grupos


def escolher_para_abrir(grupos, limite):
    """
    Abre o representante de cada grupo (o ato de maior prioridade do tipo),
    ate o teto. Marca o motivo em quem nao abre e devolve quem abre, na ordem.
    """
    abrir = []
    for grupo in sorted(grupos, key=lambda g: _ordem(g["representante"])):
        representante = grupo["representante"]
        for ato in grupo["atos"]:
            if ato is not representante:
                ato["nao_aberto"] = f"agrupado: o grupo abre um ato só ({representante['titulo'][:80]})"
        if len(abrir) >= limite:
            representante["nao_aberto"] = f"teto de {limite} atos abertos por execução"
            continue
        abrir.append(representante)
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


def coletar(fc, secoes, data, config=None, esperar=None, termos=None):
    """
    Coleta as secoes pedidas da edicao de 'data' (datetime.date).

    'secoes' e uma lista de codigos ('dou1', 'dou3'); 'esperar' e chamada
    antes de cada pedido ao Firecrawl (o intervalo entre pedidos do
    gerar_boletim); 'termos' sao as palavras-chave de cada Radar (do
    prompt.md, se nao vierem). Devolve um registro por secao e o total:

        {"secoes": {secao: {"listados", "selecionados", "abertos", "creditos",
                            "atos", "erro", "aviso"}},
         "grupos": [...], "creditos": n, "limite_atos_abertos": n}
    """
    config = config or carregar_config()
    esperar = esperar or (lambda: None)
    termos = termos if termos is not None else termos_dos_radares()
    resultado = {"edicao": data.isoformat(), "secoes": {}, "grupos": [], "creditos": 0, "limite_atos_abertos": config.get("limite_atos_abertos", 20)}
    todos = []
    for secao in secoes:
        filtro = Filtro(config, secao, termos)
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
        registro["atos"] = selecionar(atos, filtro)
        registro["selecionados"] = len(registro["atos"])
        todos.extend(registro["atos"])

    resultado["grupos"] = agrupar(todos, config)
    tamanho = config.get("tamanho_trecho", 900)
    for ato in escolher_para_abrir(resultado["grupos"], resultado["limite_atos_abertos"]):
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


def selecionar(atos, filtro):
    """Os atos que entram em algum Radar, com os Radares e o motivo de cada um."""
    selecionados = []
    for ato in atos:
        motivos = filtro.radares(ato)
        if motivos:
            ato["radares"] = list(motivos)
            ato["regras"] = motivos
            selecionados.append(ato)
    return selecionados


def numero_do_ato(ato):
    achado = re.search(r"N[ºo°]\s*([\d\.]+(?:/\d{4})?)", ato["titulo"], re.I)
    return achado.group(1) if achado else ""


def plural(tipo):
    """'Portaria Conjunta' -> 'portarias conjuntas'; 'Despacho' -> 'despachos'."""
    saida = []
    for palavra in tipo.lower().split():
        if palavra in ("de", "da", "do", "e"):
            saida.append(palavra)
        elif palavra.endswith("ão"):
            saida.append(palavra[:-2] + "ões")
        elif palavra.endswith("l"):
            saida.append(palavra[:-1] + "is")
        elif palavra.endswith(("r", "z")):
            saida.append(palavra + "es")
        elif palavra.endswith("s"):
            saida.append(palavra)
        else:
            saida.append(palavra + "s")
    return " ".join(saida)


def distintivos(atos):
    """O que distingue cada ato do grupo: as primeiras palavras que nao se repetem em quase todos."""
    def palavras(texto):
        return re.findall(r"[\wÀ-ÿ/ºª.\-]+", texto)

    conjuntos = [{normalizar(p) for p in palavras(a["titulo"] + " " + a["inicio_do_texto"])} for a in atos]
    contagem = {}
    for conjunto in conjuntos:
        for p in conjunto:
            contagem[p] = contagem.get(p, 0) + 1
    comuns = {p for p, n in contagem.items() if n >= 0.8 * len(atos)}
    return [" ".join([p for p in palavras(a["inicio_do_texto"]) if normalizar(p) not in comuns][:12]).strip(" .:;,") for a in atos]


def _base_do_item(ato, fonte):
    secao = re.sub(r"\D", "", ato["secao"]) or ato["secao"]
    return {
        "fonte": fonte,
        "categoria": "Diário Oficial da União",
        "url": ato["url"],
        "data_publicacao": ato["data"],
        "trecho_do_ato": {"texto": ato.get("trecho", ""), "secao": secao, "pagina": ato["pagina"]} if ato.get("trecho") else None,
        "boletins_confirmados": list(ato["radares"]),
        "boletins_rejeitados": [],
        "palavras_chave_detectadas": list(ato.get("palavras_chave") or []),
        "motivo_filtragem": "DOU: " + "; ".join(f"{slug}: {motivo}" for slug, motivo in ato["regras"].items()),
    }


def item_do_ato(ato, fonte):
    """O item do boletim.json para um ato que passou no filtro."""
    return dict(
        _base_do_item(ato, fonte),
        titulo=f"{ato['titulo']} ({orgao_curto(ato)})",
        resumo=ato.get("resumo", ""),
        dou={"orgao": ato["orgao"], "tipo": ato["tipo"], "pagina": ato["pagina"], "edicao": ato["edicao"],
             "aberto": ato.get("aberto", False), "nao_aberto": ato.get("nao_aberto", "")},
    )


def item_do_grupo(atos, tipo, fonte):
    """
    A noticia de um grupo: o titulo diz quantos atos sao, o resumo e o trecho
    sao os do ato aberto (o representante), e 'atos_do_grupo' lista todos,
    com link e o que distingue cada um.
    """
    representante = next(a for a in atos if a["grupo"]["representante"])
    numeros = [numero_do_ato(a) for a in atos]
    faixa = ""
    if all(numeros):
        ordem = sorted(numeros, key=lambda n: int(re.sub(r"\D", "", n.split("/")[0]) or 0))
        faixa = f", nº {ordem[0]} a {ordem[-1]}" if len(ordem) > 3 else ", nº " + ", ".join(ordem)
    qual = "de mesmo teor" if tipo == "serie" else "na mesma edição"
    exemplo = numero_do_ato(representante)
    abertura = (f"{len(atos)} atos com o mesmo texto-base" if tipo == "serie" else f"{len(atos)} atos do mesmo órgão e tipo nesta edição")
    resumo = f"{abertura}. Exemplo{f' (nº {exemplo})' if exemplo else ''}: {representante.get('resumo', '')}".strip()
    return dict(
        _base_do_item(representante, fonte),
        titulo=f"{orgao_curto(representante)}: {len(atos)} {plural(representante['tipo'])} {qual}{faixa}",
        resumo=resumo,
        atos_do_grupo=[{"titulo": a["titulo"], "numero": numero_do_ato(a), "url": a["url"], "distintivo": d}
                       for a, d in zip(atos, distintivos(atos))],
        palavras_chave_detectadas=sorted({t for a in atos for t in a.get("palavras_chave") or []}),
        dou={"orgao": representante["orgao"], "tipo": representante["tipo"], "pagina": representante["pagina"],
             "edicao": representante["edicao"], "grupo": tipo, "atos": len(atos), "aberto": representante.get("aberto", False),
             "nao_aberto": representante.get("nao_aberto", "")},
    )


def itens(atos, fonte):
    """Os itens do boletim.json para os atos de uma secao: uma noticia por grupo."""
    por_grupo = {}
    for ato in atos:
        chave = (ato.get("grupo") or {}).get("id") or id(ato)
        por_grupo.setdefault(chave, []).append(ato)
    saida = []
    for membros in por_grupo.values():
        grupo = membros[0].get("grupo") or {}
        if grupo.get("tipo") in ("lote", "serie") and len(membros) > 1:
            saida.append(item_do_grupo(membros, grupo["tipo"], fonte))
        else:
            saida.extend(item_do_ato(a, fonte) for a in membros)
    return saida


def resumo_para_o_log(atos):
    """Contagens por Radar (atos e noticias), dos grupos e do motivo de nao abrir."""
    por_radar, noticias, por_motivo, grupos = {}, {}, {}, {}
    vistos = set()
    for ato in atos:
        grupo = ato.get("grupo") or {}
        for slug in ato["radares"]:
            por_radar[slug] = por_radar.get(slug, 0) + 1
        chave = grupo.get("id") or id(ato)
        if chave not in vistos:
            vistos.add(chave)
            for slug in ato["radares"]:
                noticias[slug] = noticias.get(slug, 0) + 1
            if grupo.get("tipo") in ("lote", "serie"):
                grupos[grupo["tipo"]] = grupos.get(grupo["tipo"], 0) + 1
        if not ato.get("aberto"):
            motivo = (ato.get("nao_aberto") or "").split(":")[0]
            por_motivo[motivo] = por_motivo.get(motivo, 0) + 1
    return {"por_radar": por_radar, "noticias_por_radar": noticias, "grupos": grupos, "nao_abertos_por_motivo": por_motivo}


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
    noticias = [i for secao, parte in resultado["secoes"].items() for i in itens(parte["atos"], config["secoes"][secao]["fonte"])]
    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)
    atos = [a for parte in resultado["secoes"].values() for a in parte["atos"]]
    resumo = {"edicao": resultado["edicao"], "creditos_firecrawl": resultado["creditos"], "limite_atos_abertos": resultado["limite_atos_abertos"],
              "por_secao": {s: {k: v for k, v in p.items() if k != "atos"} for s, p in resultado["secoes"].items()}, **resumo_para_o_log(atos)}
    (saida / "resultado.json").write_text(json.dumps({"resumo": resumo, "itens": noticias}, ensure_ascii=False, indent=1), encoding="utf-8")
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
