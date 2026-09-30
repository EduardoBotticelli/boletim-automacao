"""Coleta, complementa, classifica e audita as fontes dos Radares.

Uso:
    python scripts/gerar_boletim.py                 # coleta e classifica
    python scripts/gerar_boletim.py --reprocessar   # classifica de novo o
                                                    # dossier guardado, sem
                                                    # chamar o Firecrawl
"""
import argparse
import datetime
import json
import math
import os
import re
import time
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from firecrawl import Firecrawl
from google import genai
from google.genai import types

import coleta_direta

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "output"
FONTES = BASE / "fontes.json"
PROMPT = BASE / "prompt.md"
BOLETIM = OUT / "boletim.json"
LOG = OUT / "log_execucao.json"

MODELOS = ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"]
SLUGS = ["trabalhista-empresarial", "direito-tributario", "societario-ma", "mercado-capitais-fundos", "regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg", "propriedade-intelectual", "contencioso-civel"]
NOMES = {
    "trabalhista-empresarial": "Radar Trabalhista Empresarial",
    "direito-tributario": "Radar Tributário",
    "societario-ma": "Radar Societário, Fusões e Aquisições",
    "mercado-capitais-fundos": "Radar Mercado de Capitais e Fundos de Investimento",
    "regulatorio-oleo-gas": "Radar Regulatório e Óleo e Gás",
    "imobiliario-infraestrutura": "Radar Negócios Imobiliários e Infraestrutura",
    "ambiental-esg": "Radar Ambiental e ESG",
    "propriedade-intelectual": "Radar Propriedade Intelectual, Tecnologia e Privacidade",
    "contencioso-civel": "Radar Solução de Conflitos",
}
CLUSTERS = {
    "trabalhista-empresarial": ["Amber", "Pink"], "direito-tributario": ["Tributário Consultivo", "Tributário Contencioso"],
    "societario-ma": ["White", "Purple", "Due Diligence"], "mercado-capitais-fundos": ["Financeiro Green", "Fundos"],
    "regulatorio-oleo-gas": ["Regulatório", "Óleo & Gás Blue"], "imobiliario-infraestrutura": ["Imobiliário", "Infraestrutura"],
    "ambiental-esg": ["Ambiental"], "propriedade-intelectual": ["Propriedade Intelectual"],
    "contencioso-civel": ["Contencioso Carbon", "Contencioso Gold"],
}
EMAIL = {
    "trabalhista-empresarial": [], "direito-tributario": ["Tributário.com"], "societario-ma": ["Latin Lawyer"],
    "mercado-capitais-fundos": ["Latin Lawyer"], "regulatorio-oleo-gas": ["Agência iNFRA", "iNFRA Energia", "Agência Eixos"],
    "imobiliario-infraestrutura": ["Agência iNFRA", "iNFRA Energia", "IRIB", "Latin Lawyer"], "ambiental-esg": ["RC Ambiental"],
    "propriedade-intelectual": [], "contencioso-civel": [],
}
MAPA = {
    "Planalto | Resenha Diaria": SLUGS, "Destaques do D.O.U.": ["trabalhista-empresarial", "direito-tributario", "regulatorio-oleo-gas", "contencioso-civel"],
    "Ministerio da Fazenda | Noticias": SLUGS, "CGU | Noticias": ["trabalhista-empresarial", "regulatorio-oleo-gas"],
    "Receita Federal | Normas": ["direito-tributario"], "Banco Central | Normas": ["direito-tributario", "societario-ma", "mercado-capitais-fundos"],
    "COAF | Noticias": ["direito-tributario", "mercado-capitais-fundos"], "CVM | Noticias": ["mercado-capitais-fundos", "regulatorio-oleo-gas", "imobiliario-infraestrutura"],
    "B3 | Oficios e Comunicados": ["mercado-capitais-fundos"], "ANP | Noticias": ["regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"],
    "ANP | Consultas e Audiencias Publicas": ["regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"],
    "ANP | Consultas Previas": ["regulatorio-oleo-gas"], "ANP | Pautas e Atas da Diretoria Colegiada": ["regulatorio-oleo-gas"],
    "ANEEL | Ultimas Noticias": ["societario-ma", "regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"],
    "ANM | Noticias": ["regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"], "ANVISA | Noticias": ["regulatorio-oleo-gas"],
    "SENACON | Noticias": ["regulatorio-oleo-gas", "propriedade-intelectual", "contencioso-civel"], "Secretaria de Premios e Apostas | Noticias": [],
    "ONS | Noticias": ["imobiliario-infraestrutura", "ambiental-esg"], "CCEE | Noticias": ["imobiliario-infraestrutura", "ambiental-esg"],
    "EPE | Noticias": ["regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"], "MME | Noticias": ["regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"],
    "MME | Consultas Publicas": ["regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"], "Ministerio do Meio Ambiente | Noticias": ["ambiental-esg"],
    "Ministerio da Agricultura | Noticias": ["imobiliario-infraestrutura", "ambiental-esg"], "INPI | Noticias": ["propriedade-intelectual"],
    "ANPD | Noticias": ["propriedade-intelectual"], "ANTAQ | Noticias": ["regulatorio-oleo-gas", "imobiliario-infraestrutura"],
    "CNPE | Comunicacoes": ["regulatorio-oleo-gas"], "Kollemata | Decretos": ["imobiliario-infraestrutura"],
    "ANATEL | Noticias": ["regulatorio-oleo-gas", "imobiliario-infraestrutura"],
    "SUSEP | Noticias": ["mercado-capitais-fundos", "regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"],
    "ANTT | Noticias - Defeso Eleitoral": ["regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"],
}
MAX_CHARS = 30000
MIN_CHARS = 500
# Resultados por busca complementar. O Firecrawl cobra 2 creditos a cada 10;
# com 30 cada busca custava 6.
BUSCA_LIMITE = 10
# Teto do bloco da busca complementar dentro de MAX_CHARS. Garante que a
# pagina continue tendo espaco mesmo quando a busca traz muitos resultados.
LIMITE_BUSCA_CHARS = MAX_CHARS * 2 // 5
# Fontes por chamada ao Gemini. O prompt unico com as trinta passava de 200
# mil tokens e levava a 429 nos modelos melhores.
LOTE_FONTES = 6
# Intervalo entre lotes. Com 4 segundos, a primeira execucao em lotes ainda
# viu 429 RESOURCE_EXHAUSTED em quatro dos cinco lotes: a cota do Gemini e por
# minuto, e cinco chamadas grandes em um minuto continuam estourando. Dar
# espaco entre elas custa tempo de execucao e nada mais.
INTERVALO_LOTES = 20
# Piso de publicacoes por Radar para o resgate por escassez.
PISO_RESGATE = 5
# Pausa entre chamadas ao Firecrawl, coleta ou busca.
PAUSA_FIRECRAWL = 6.5
# O Firecrawl cobra 2 creditos a cada 10 resultados de busca pedidos.
CREDITOS_POR_BUSCA = 2 * math.ceil(BUSCA_LIMITE / 10)
# O 503 UNAVAILABLE e sobrecarga do lado do Google, temporaria por definicao.
# Na execucao de 29/09 foram 27 erros 503 e nenhum 429, e a cascata antiga
# (duas tentativas por modelo, 10 s entre elas) se esgotava em uns 100
# segundos e entregava quatro dos cinco lotes ao modelo mais fraco. Agora o
# primeiro modelo espera e repete nestes intervalos antes de ceder a vez.
ESPERAS_SOBRECARGA = (30, 60, 120)
# Teto da espera por sobrecarga, somada em todos os lotes da execucao. Passado
# o teto, a cascata volta a descer sem esperar, para caber no workflow.
TETO_ESPERA_SOBRECARGA = 15 * 60
CODIGO_HTTP = re.compile(r"^\s*(\d{3})\b")
# O dossier guardado: uma pagina por arquivo e um indice.json com o resto.
DOSSIER = OUT / "dossier"
# Quanto de cada pagina fica guardado. O Gemini so ve MAX_CHARS; o dobro
# permite medir depois o que o corte deixou de fora.
LIMITE_PAGINA_GUARDADA = MAX_CHARS * 2


def sem_acento(valor):
    return "".join(c for c in unicodedata.normalize("NFD", str(valor)) if unicodedata.category(c) != "Mn")


def chave_fonte(nome):
    alvo = sem_acento(nome).lower()
    return next((k for k in MAPA if sem_acento(k).lower() == alvo), nome)


def salvar(path, dados):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def erro_resumo(erro, limite=400):
    return " ".join(str(erro).split())[:limite]


def scrape_retry(fc, url, so_conteudo_principal=True):
    """
    Coleta a pagina.

    'so_conteudo_principal' e o only_main_content do Firecrawl. Ele limpa
    menu, rodape e banners, mas em algumas listagens leva junto os links das
    publicacoes: a conferencia de cobertura mostrou as quatro fontes da ANP e
    o CNPE entregando 20 a 35 mil caracteres de texto com ZERO links de
    publicacao no conteudo principal, contra 261 na pagina inteira. Essas
    fontes marcam "pagina_inteira": true no fontes.json.
    """
    for tentativa in range(3):
        try:
            return fc.scrape(url, formats=["markdown"], only_main_content=so_conteudo_principal)
        except Exception as erro:
            if tentativa == 2 or not any(x in str(erro).lower() for x in ["429", "rate limit", "too many"]):
                raise
            time.sleep(65)


def escopo(url):
    p = urlparse(url)
    partes = [x for x in p.path.split("/") if x]
    return p.netloc + ("/" + "/".join(partes[:2]) if p.netloc.endswith("gov.br") and len(partes) >= 2 else "")


def busca_complementar(fc, escopo_busca, inicio, fim, excluir=()):
    """
    Publicacoes do escopo dentro da janela, pela busca do Firecrawl.

    Recebe o escopo, e nao a fonte: a busca e feita uma vez por escopo e
    repartida entre as fontes que o dividem (ver coletar). 'excluir' sao as
    URLs das proprias listagens, que a busca tambem devolve.
    """
    consulta = f"site:{escopo_busca} after:{inicio.isoformat()} before:{(fim + datetime.timedelta(days=1)).isoformat()}"
    resultado = fc.search(consulta, limit=BUSCA_LIMITE)
    ignorar = {str(u).rstrip("/") for u in excluir}
    registros, vistos = [], set()
    for item in getattr(resultado, "web", None) or []:
        url = str(getattr(item, "url", "") or "").strip()
        titulo = str(getattr(item, "title", "") or "").strip()
        descricao = str(getattr(item, "description", "") or getattr(item, "snippet", "") or "").strip()
        if not url or url in vistos or url.rstrip("/") in ignorar:
            continue
        vistos.add(url)
        registros.append({"titulo": titulo, "url": url, "descricao": descricao})
    return registros


def texto_busca(registros):
    linhas = ["## Publicações individuais descobertas por busca complementar"]
    for x in registros:
        linhas.append(f"- Título: {x['titulo']}\n  URL: {x['url']}\n  Descrição: {x['descricao']}")
    return "\n".join(linhas)


def montar_conteudo(bruto, descobertas):
    """
    Junta a pagina coletada e o que a busca complementar achou, dentro de
    MAX_CHARS.

    O bloco da busca entra primeiro e a pagina ocupa o que sobra. Antes era o
    contrario: concatenava e cortava no fim. Como a busca so dispara quando a
    pagina e grande, e a pagina grande ja preenchia MAX_CHARS sozinha, o bloco
    inteiro caia fora justamente nas fontes que mais dependiam dele.

    Devolve (conteudo, caracteres ocupados pela busca, pagina foi cortada).
    """
    if not descobertas:
        return bruto[:MAX_CHARS], 0, len(bruto) > MAX_CHARS

    bloco = texto_busca(descobertas)[:LIMITE_BUSCA_CHARS]
    espaco = MAX_CHARS - len(bloco) - 2
    if espaco <= 0:
        return bloco[:MAX_CHARS], min(len(bloco), MAX_CHARS), True

    return bruto[:espaco] + "\n\n" + bloco, len(bloco), len(bruto) > espaco


def pagina_erro(conteudo):
    t = conteudo.lower()
    return next((m for m in ["estamos em manutenção", "estamos em manutencao", "conteúdo restrito", "conteudo restrito", "access denied", "internal server error"] if m in t), "")


def exclusao_institucional(item):
    t = sem_acento(item.get("titulo", "")).lower()
    marcadores = ["aviso de pauta", "cumpre agenda", "inscricoes para o curso", "premio anp de inovacao", "programa de formacao", "masterclass", "na midia", "campanha nacional para apresentar", "debate competitividade", "recebe novos tecnicos", "novos servidores"]
    return next((m for m in marcadores if m in t), "")


def estado(fonte, hoje):
    if not fonte.get("ativo", True):
        return "inativa"
    if fonte.get("suspenso"):
        try:
            if hoje < datetime.date.fromisoformat(fonte.get("reativar_em", "9999-12-31")):
                return "suspensa"
        except ValueError:
            return "suspensa"
    return "ativa"


def fontes_execucao(inicio, agora, hoje):
    fontes = json.loads(FONTES.read_text(encoding="utf-8"))
    di = inicio.strftime("%d/%m/%Y").replace("/", "%2F")
    df = agora.strftime("%d/%m/%Y").replace("/", "%2F")
    meses = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
    dinamicas = [
        # O servidor do Planalto derruba a conexao de coleta direta: fica no Firecrawl.
        {"fonte": "Planalto | Resenha Diaria", "categoria": "Legislação Federal", "url": f"http://www4.planalto.gov.br/legislacao/portal-legis/resenha-diaria/{meses[hoje.month-1]}-resenha-diaria", "ativo": True, "coleta": "firecrawl"},
        {"fonte": "Banco Central | Normas", "categoria": "Financeiro e Mercado de Capitais", "url": f"https://www.bcb.gov.br/estabilidadefinanceira/buscanormas?dataInicioBusca={di}&dataFimBusca={df}&tipoDocumento=Todos", "ativo": True, "coleta": "api_bcb"},
        # A propria busca da CCEE ja filtra a janela; os resultados sao os links "/-/".
        {"fonte": "CCEE | Noticias", "categoria": "Energia e Recursos", "url": f"https://www.ccee.org.br/busca-ccee?q=&dtIni={di}&dtFim={df}&structure=ccee-noticias&ordenacao=Mais%20recentes", "ativo": True, "coleta": "html", "padrao_link": "/-/"},
    ]
    return dinamicas + fontes


def _caminho(url):
    p = urlparse(url)
    host = p.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return host + p.path.rstrip("/").lower()


def repartir_busca(achados, fontes):
    """
    Reparte o resultado de uma busca entre as fontes que dividem o escopo.

    Cada publicacao vai para a fonte cujo endereco e o prefixo mais longo do
    endereco dela: uma consulta publica da ANP cai em "ANP | Consultas e
    Audiencias Publicas", e nao nas quatro fontes da ANP ao mesmo tempo. O
    que nao casa com nenhuma fica com a primeira, na ordem do fontes.json.

    Devolve uma lista por fonte, na ordem de 'fontes'.
    """
    caminhos = [_caminho(f["url"]) for f in fontes]
    partes = [[] for _ in fontes]
    for achado in achados:
        alvo = _caminho(achado["url"])
        destino, maior = 0, -1
        for posicao, caminho in enumerate(caminhos):
            if (alvo == caminho or alvo.startswith(caminho + "/")) and len(caminho) > maior:
                destino, maior = posicao, len(caminho)
        partes[destino].append(achado)
    return partes


def coletar(fc, ativas, inicio, hoje, pausa=PAUSA_FIRECRAWL, cliente=None, historico=None, coletor=None):
    """
    Coleta as fontes, cada uma pelo metodo que o fontes.json declara.

    Fonte com coleta gratuita (download direto ou API, ver coleta_direta.py)
    traz as publicacoes ja separadas, com titulo, data, link e descricao. Se o
    metodo falhar, a fonte cai para o Firecrawl naquele dia e o motivo fica
    registrado. Conta como falha tambem a fonte que listou zero publicacoes
    quando na execucao anterior listava alguma ('historico'): leitor quebrado
    costuma aparecer assim, com HTTP 200 e nada dentro.

    A busca complementar so roda nas fontes com "busca": true, e uma vez por
    escopo, repartida entre as fontes que o dividem. O que a busca acha nunca
    vai para fonte com pagina de erro; se nenhuma do escopo veio de pe, a
    busca nem e feita, e o motivo fica em 'buscas'.

    Devolve (material, buscas). 'material' e uma entrada por fonte: e o que
    montar_dossier transforma no dossier do Gemini e o que salvar_dossier
    guarda em disco.
    """
    cliente = cliente or coleta_direta.novo_cliente()
    historico = historico or {}
    coletor = coletor or coleta_direta.coletar
    ultimo_firecrawl = [None]

    def esperar_firecrawl():
        if ultimo_firecrawl[0] is not None:
            falta = pausa - (time.monotonic() - ultimo_firecrawl[0])
            if falta > 0:
                time.sleep(falta)
        ultimo_firecrawl[0] = time.monotonic()

    material = []
    for indice, fonte in enumerate(ativas, 1):
        nome = fonte["fonte"]
        metodo = fonte.get("coleta", "firecrawl")
        print(f"[{indice}/{len(ativas)}] {nome} ({metodo})")
        registro = {
            "fonte": nome, "categoria": fonte["categoria"], "url": fonte["url"],
            "tipo_coleta": fonte.get("tipo_coleta", "pagina"),
            "pagina_inteira": bool(fonte.get("pagina_inteira")),
            "metodo": metodo, "metodo_usado": "", "queda_firecrawl": False, "motivo_queda": "",
            "creditos_firecrawl": 0, "requisicoes_diretas": 0, "estruturado": False,
            "publicacoes": [], "publicacoes_listadas": None,
            "status": "ok", "erro": "", "pagina": "", "chars_pagina": 0,
            "busca_pedida": bool(fonte.get("busca")), "busca_executada": False, "descobertas": [],
        }
        if metodo != "firecrawl":
            try:
                resultado = coletor(cliente, fonte, inicio, hoje)
                registro["requisicoes_diretas"] = resultado.get("requisicoes", 0)
                anterior = historico.get(nome)
                if resultado["listadas"] == 0 and anterior != 0:
                    raise coleta_direta.FalhaColeta(
                        "zero publicações listadas" + (f" (na execução anterior: {anterior})" if anterior else " e sem histórico da fonte")
                    )
                if resultado.get("aviso"):
                    print(f"::warning title=Coleta de {nome}::{resultado['aviso']}")
                registro.update(
                    aviso_coleta=resultado.get("aviso", ""), estruturado=True, metodo_usado=metodo, publicacoes=resultado["publicacoes"],
                    publicacoes_listadas=resultado["listadas"], pagina=resultado["texto"],
                    chars_pagina=len(resultado["texto"]),
                )
            except Exception as erro:
                motivo = erro_resumo(erro, 240)
                registro.update(queda_firecrawl=True, motivo_queda=motivo)
                print(f"::warning title=Queda para o Firecrawl::{nome}: {motivo}")
        if not registro["estruturado"]:
            registro["metodo_usado"] = "firecrawl"
            registro["creditos_firecrawl"] = 1
            esperar_firecrawl()
            try:
                resultado = scrape_retry(fc, fonte["url"], not fonte.get("pagina_inteira"))
                bruto = resultado.markdown or ""
                registro.update(pagina=bruto, chars_pagina=len(bruto))
                marcador = pagina_erro(bruto[:MAX_CHARS])
                if marcador:
                    registro.update(status="erro_conteudo_origem", erro=f"A origem retornou página de erro/manutenção ({marcador}).")
            except Exception as erro:
                registro.update(status="erro", erro=erro_resumo(erro, 300))
        material.append(registro)

    grupos = {}
    for registro in material:
        if registro["busca_pedida"]:
            grupos.setdefault(escopo(registro["url"]), []).append(registro)

    buscas = []
    for alvo, grupo in grupos.items():
        nomes = [r["fonte"] for r in grupo]
        de_pe = [r for r in grupo if r["status"] == "ok"]
        busca = {"escopo": alvo, "fontes": nomes, "executada": False, "resultados": 0, "erro": ""}
        buscas.append(busca)
        for registro in grupo:
            registro["escopo_busca"] = alvo
            registro["busca_compartilhada_com"] = [n for n in nomes if n != registro["fonte"]]
        if not de_pe:
            busca["erro"] = "Busca não executada: a página de todas as fontes deste escopo falhou."
            continue
        esperar_firecrawl()
        de_pe[0]["creditos_firecrawl"] += CREDITOS_POR_BUSCA
        try:
            achados = busca_complementar(fc, alvo, inicio, hoje, excluir=[r["url"] for r in grupo])
        except Exception as erro:
            busca["erro"] = "Busca complementar falhou: " + erro_resumo(erro, 180)
            print(busca["erro"])
            continue
        busca.update(executada=True, resultados=len(achados))
        for registro, parte in zip(de_pe, repartir_busca(achados, de_pe)):
            registro.update(descobertas=parte, busca_executada=True)
        if len(grupo) > 1:
            print(f"Busca em {alvo}: {len(achados)} resultado(s) repartido(s) entre {len(grupo)} fontes.")
    return material, buscas


def texto_estruturado(publicacoes):
    """As publicacoes de uma fonte coletada sem Firecrawl, no formato do dossier."""
    linhas = ["## Publicações coletadas direto da fonte (título, data, link e descrição informados por ela)"]
    for p in publicacoes:
        data = f"{p['data']} {p.get('hora', '')}".strip() if p.get("data") else "não informada na listagem"
        linhas.append(f"- Título: {p['titulo']}\n  Data: {data}\n  URL: {p['url']}\n  Descrição: {p.get('descricao', '')}")
    return "\n".join(linhas)


def montar_dossier(material):
    """
    O dossier que vai ao Gemini, a partir do que a coleta trouxe.

    Serve a coleta e o reprocessamento: o dossier de uma execucao pode ser
    refeito do que ficou guardado em disco, sem chamar o Firecrawl.

    Devolve (dossier, processadas).
    """
    dossier, processadas = [], []
    for registro in material:
        nome = registro["fonte"]
        base = {"fonte": nome, "categoria": registro["categoria"], "url": registro["url"]}
        descobertas = registro.get("descobertas") or []
        origem = {k: registro.get(k) for k in ("metodo", "metodo_usado", "queda_firecrawl", "motivo_queda", "creditos_firecrawl", "requisicoes_diretas") if k in registro}
        if registro["status"] == "erro":
            dossier.append(dict(base, conteudo="", erro_tecnico=registro["erro"]))
            processadas.append(dict({"fonte": nome, "status": "erro", "erro": registro["erro"]}, **origem))
            continue
        if registro["status"] == "erro_conteudo_origem":
            dossier.append(dict(base, conteudo="", erro_tecnico=registro["erro"]))
            processadas.append(dict({"fonte": nome, "status": "erro_conteudo_origem", "tamanho_chars": registro.get("chars_pagina", 0), "erro": registro["erro"]}, **origem))
            continue
        if registro.get("estruturado"):
            publicacoes = registro.get("publicacoes") or []
            enviar = [p for p in publicacoes if p.get("enviar")]
            contagem = {"publicacoes_listadas": registro.get("publicacoes_listadas"), "publicacoes_na_janela": sum(1 for p in publicacoes if p.get("na_janela")), "publicacoes_enviadas": len(enviar)}
            if registro.get("aviso_coleta"):
                contagem["aviso_coleta"] = registro["aviso_coleta"]
            if not enviar and not descobertas:
                # Nada na janela: a fonte nao vai ao Gemini, e o registro diz por que.
                processadas.append(dict({"fonte": nome, "status": "ok", "sem_publicacao_na_janela": True, "tamanho_chars": 0, "publicacoes_localizadas": 0, "busca_complementar_executada": registro.get("busca_executada", False)}, **origem, **contagem))
                continue
            conteudo, chars_busca, truncado = montar_conteudo(texto_estruturado(enviar), descobertas)
            dossier.append(dict(base, tipo_coleta=registro.get("tipo_coleta", "pagina"), publicacoes_localizadas=len(enviar) + len(descobertas), conteudo=conteudo))
            processada = dict({"fonte": nome, "status": "ok", "tamanho_chars": len(conteudo), "publicacoes_localizadas": len(enviar) + len(descobertas), "busca_complementar_executada": registro.get("busca_executada", False), "chars_busca_complementar": chars_busca, "conteudo_truncado": truncado}, **origem, **contagem)
            if registro.get("escopo_busca"):
                processada["escopo_busca"] = registro["escopo_busca"]
            processadas.append(processada)
            continue
        conteudo, chars_busca, truncado = montar_conteudo(registro.get("pagina", ""), descobertas)
        if len(conteudo) < MIN_CHARS and not descobertas:
            motivo = f"Conteúdo insuficiente ({len(conteudo)} caracteres)."
            dossier.append(dict(base, conteudo="", erro_tecnico=motivo))
            processadas.append(dict({"fonte": nome, "status": "erro_tecnico", "tamanho_chars": len(conteudo), "erro": motivo}, **origem))
            continue
        dossier.append(dict(base, tipo_coleta=registro.get("tipo_coleta", "pagina"), publicacoes_localizadas=len(descobertas), conteudo=conteudo))
        processada = {**origem, "fonte": nome, "status": "ok", "tamanho_chars": len(conteudo), "publicacoes_localizadas": len(descobertas), "busca_complementar_executada": registro.get("busca_executada", False), "chars_busca_complementar": chars_busca, "conteudo_truncado": truncado, "pagina_inteira": registro.get("pagina_inteira", False)}
        if registro.get("escopo_busca"):
            processada["escopo_busca"] = registro["escopo_busca"]
        if registro.get("busca_compartilhada_com"):
            processada["busca_compartilhada_com"] = registro["busca_compartilhada_com"]
        processadas.append(processada)
    return dossier, processadas


def creditos_estimados(material, buscas):
    """Estimativa conservadora: toda coleta e toda busca tentadas contam."""
    tentadas = sum(1 for b in buscas if b["executada"] or b["erro"].startswith("Busca complementar falhou"))
    coletas = sum(1 for m in material if m.get("metodo_usado", "firecrawl") == "firecrawl")
    return {
        "coletas": coletas,
        "coletas_sem_firecrawl": len(material) - coletas,
        "buscas": tentadas,
        "creditos_por_busca": CREDITOS_POR_BUSCA,
        "total": coletas + tentadas * CREDITOS_POR_BUSCA,
        "quedas_para_firecrawl": sum(1 for m in material if m.get("queda_firecrawl")),
    }


def historico_de_listagem(pasta=None):
    """Quantas publicacoes cada fonte listou na execucao anterior."""
    indice_path = (pasta or DOSSIER) / "indice.json"
    try:
        indice = json.loads(indice_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {f["fonte"]: f.get("publicacoes_listadas") for f in indice.get("fontes") or [] if f.get("fonte")}


def nome_de_arquivo(fonte):
    return re.sub(r"[^a-z0-9]+", "-", sem_acento(fonte).lower()).strip("-")[:80] or "fonte"


def salvar_dossier(material, meta, pasta=None):
    """
    Guarda o que a coleta trouxe, para reprocessar sem o Firecrawl.

    Uma pagina por arquivo .md, como o Firecrawl entregou (ate
    LIMITE_PAGINA_GUARDADA caracteres), e um indice.json com o resto: o
    estado de cada fonte, o que a busca complementar achou para ela e a
    janela da execucao. Um arquivo por fonte deixa o historico do git
    comparar cada pagina com a do dia anterior.
    """
    pasta = pasta or DOSSIER
    pasta.mkdir(parents=True, exist_ok=True)
    fontes, usados = [], set()
    for registro in material:
        arquivo = nome_de_arquivo(registro["fonte"])
        sufixo = 2
        while arquivo + ".md" in usados:
            arquivo = f"{nome_de_arquivo(registro['fonte'])}-{sufixo}"
            sufixo += 1
        arquivo += ".md"
        usados.add(arquivo)
        (pasta / arquivo).write_text(registro.get("pagina", "")[:LIMITE_PAGINA_GUARDADA], encoding="utf-8")
        fontes.append(dict({k: v for k, v in registro.items() if k != "pagina"}, arquivo=arquivo))
    for antigo in pasta.glob("*.md"):
        if antigo.name not in usados:
            antigo.unlink()
    salvar(pasta / "indice.json", dict(meta, fontes=fontes))


def carregar_dossier(pasta=None):
    """O inverso de salvar_dossier: devolve (indice, material)."""
    pasta = pasta or DOSSIER
    indice_path = pasta / "indice.json"
    if not indice_path.exists():
        raise SystemExit(f"Nao ha dossier guardado em {indice_path}.")
    indice = json.loads(indice_path.read_text(encoding="utf-8"))
    material = []
    for registro in indice.get("fontes") or []:
        arquivo = pasta / registro.get("arquivo", "")
        pagina = arquivo.read_text(encoding="utf-8") if registro.get("arquivo") and arquivo.exists() else ""
        material.append(dict(registro, pagina=pagina))
    return indice, material


def tipo_de_erro(erro):
    """
    'cota' para 429 (acabou a cota: insistir no mesmo modelo nao adianta),
    'sobrecarga' para 5xx (o modelo esta cheio agora; costuma passar) e
    'outro' para o resto (JSON invalido, resposta sem itens).
    """
    codigo = getattr(erro, "code", None)
    if not isinstance(codigo, int):
        achado = CODIGO_HTTP.match(str(erro))
        codigo = int(achado.group(1)) if achado else None
    texto = str(erro).upper()
    if codigo == 429 or "RESOURCE_EXHAUSTED" in texto:
        return "cota"
    if codigo in (500, 502, 503, 504) or "UNAVAILABLE" in texto or "OVERLOADED" in texto:
        return "sobrecarga"
    return "outro"


def gemini(cliente, prompt, orcamento=None):
    """
    Passa um lote pela cascata de modelos. Cada erro tem sua resposta:

    - sobrecarga (503 e outros 5xx): o primeiro modelo espera e repete nos
      intervalos de ESPERAS_SOBRECARGA, enquanto 'orcamento' deixar; os
      outros repetem uma vez depois de 10 s, como sempre;
    - cota (429): desce na hora. A mensagem vai inteira para o log, porque e
      ela que diz se a cota estourada e por minuto ou por dia;
    - outro: repete uma vez depois de 10 s, como sempre.

    'orcamento' e compartilhado pelos lotes de uma execucao e soma quanto ja
    se esperou por sobrecarga, contra TETO_ESPERA_SOBRECARGA.
    """
    if orcamento is None:
        orcamento = {"espera": 0}
    logs = []
    for posicao, modelo in enumerate(MODELOS):
        esperas_sobrecarga = list(ESPERAS_SOBRECARGA) if posicao == 0 else [10]
        repeticoes = 1
        tentativa = 0
        while True:
            tentativa += 1
            try:
                resposta = cliente.models.generate_content(model=modelo, contents=prompt, config=types.GenerateContentConfig(temperature=0.15, response_mime_type="application/json"))
                dados = json.loads(resposta.text or "")
                if not isinstance(dados, dict) or not isinstance(dados.get("itens"), list):
                    raise ValueError("JSON sem itens")
                logs.append({"modelo": modelo, "tentativa": tentativa, "status": "sucesso"})
                return dados, modelo, logs
            except Exception as erro:
                tipo = tipo_de_erro(erro)
                registro = {"modelo": modelo, "tentativa": tentativa, "status": "erro", "tipo_erro": tipo, "erro": erro_resumo(erro, 4000 if tipo == "cota" else 400)}
                logs.append(registro)
                espera = 0
                if tipo == "sobrecarga" and esperas_sobrecarga:
                    if posicao > 0 or orcamento["espera"] + esperas_sobrecarga[0] <= TETO_ESPERA_SOBRECARGA:
                        espera = esperas_sobrecarga.pop(0)
                        if posicao == 0:
                            orcamento["espera"] += espera
                elif tipo == "outro" and repeticoes:
                    repeticoes -= 1
                    espera = 10
                if not espera:
                    break
                registro["espera_antes_da_proxima_s"] = espera
                time.sleep(espera)
    return None, "", logs


def lotes_de(dossier, tamanho):
    for inicio in range(0, len(dossier), tamanho):
        yield dossier[inicio : inicio + tamanho]


def classificar(cliente, base, contexto, dossier):
    """
    Classifica o dossier em lotes de fontes, um lote por chamada.

    O prompt unico com as trinta fontes chegava a 200 mil tokens e provocava
    429 RESOURCE_EXHAUSTED nos modelos melhores; a cascata entregava entao o
    trabalho ao mais fraco, que extrai menos. Em lotes, cada chamada cabe no
    orcamento e o primeiro modelo volta a ser usado.

    A cascata continua valendo dentro de cada lote. Um lote que falha por
    inteiro nao derruba os outros: as fontes dele voltam em 'falharam' e sao
    registradas como erro tecnico, para nao sumirem em silencio.

    Devolve (boletim unido, modelos usados, registro por lote, fontes falhas).
    """
    itens, sem_publicacao, sem_resultado, com_erro = [], [], [], []
    modelos, registro, falharam = [], [], []
    total = len(list(lotes_de(dossier, LOTE_FONTES)))
    orcamento = {"espera": 0}

    for numero, lote in enumerate(lotes_de(dossier, LOTE_FONTES), 1):
        nomes = [d.get("fonte", "") for d in lote]
        print(f"Gemini lote {numero}/{total}: {len(lote)} fonte(s)")
        prompt = base + contexto + json.dumps(lote, ensure_ascii=False)
        antes = orcamento["espera"]
        dados, modelo, tentativas = gemini(cliente, prompt, orcamento)
        registro.append({"lote": numero, "fontes": nomes, "modelo": modelo, "tentativas": tentativas, "espera_por_sobrecarga_s": orcamento["espera"] - antes})
        if modelo and modelo != MODELOS[0]:
            print(f"  lote {numero} atendido por {modelo}, nao por {MODELOS[0]}")

        if dados is None:
            print(f"  lote {numero} falhou em todos os modelos")
            falharam.extend(nomes)
        else:
            modelos.append(modelo)
            itens.extend(x for x in dados.get("itens", []) if isinstance(x, dict))
            sem_publicacao.extend(dados.get("fontes_sem_publicacao_hoje") or [])
            sem_resultado.extend(dados.get("fontes_sem_resultado") or [])
            com_erro.extend(dados.get("fontes_com_erro_tecnico") or [])

        if numero < total:
            time.sleep(INTERVALO_LOTES)

    if not modelos:
        return None, [], registro, falharam

    unido = {
        "itens": itens,
        "fontes_sem_publicacao_hoje": sem_publicacao,
        "fontes_sem_resultado": sem_resultado,
        "fontes_com_erro_tecnico": com_erro,
    }
    return unido, modelos, registro, falharam


def resumo_cascata(lotes):
    """Qual modelo atendeu cada lote, para a queda nunca passar despercebida."""
    preferido = MODELOS[0]
    fora = [r for r in lotes if r.get("modelo") != preferido]
    return {
        "modelo_preferido": preferido,
        "lotes": [
            {"lote": r["lote"], "modelo": r.get("modelo") or "falhou", "fontes": r.get("fontes", []), "espera_por_sobrecarga_s": r.get("espera_por_sobrecarga_s", 0)}
            for r in lotes
        ],
        "lotes_fora_do_preferido": len(fora),
        "espera_por_sobrecarga_s": sum(r.get("espera_por_sobrecarga_s", 0) for r in lotes),
        "aviso": (
            f"{len(fora)} de {len(lotes)} lote(s) não usaram {preferido}: "
            + "; ".join(f"lote {r['lote']} em {r.get('modelo') or 'nenhum modelo'}" for r in fora)
        ) if fora else "",
    }


def resgatar_por_escassez(itens, piso):
    """
    Promove, nos Radares que ficaram abaixo do piso, as publicacoes que a IA
    considerou tematicamente possiveis mas insuficientes.

    O Filtro 1 continua valendo: so entra o que a matriz permite para aquela
    fonte. Publicacao excluida por conteudo institucional nao e resgatada.

    O item chega ao portal identificado como resgatado dentro do
    'motivo_filtragem', que e o campo de motivo que a curadoria ja exibe, e
    guarda o detalhe em 'resgates' para a auditoria. Quem decide continua
    sendo a pessoa: o resgate so coloca o item na mesa.

    Devolve a lista de resgates feitos.
    """
    if piso <= 0:
        return []

    total = Counter()
    for item in itens:
        for slug in item.get("boletins") or []:
            total[slug] += 1

    resgates = []
    for slug in SLUGS:
        for item in itens:
            if total[slug] >= piso:
                break
            if slug in (item.get("boletins") or []):
                continue
            if item.get("exclusao_editorial_automatica"):
                continue
            if slug not in set(MAPA.get(chave_fonte(item.get("fonte", "")), [])):
                continue

            recusa = next(
                (
                    r
                    for r in item.get("boletins_rejeitados") or []
                    if isinstance(r, dict)
                    and r.get("boletim") == slug
                    and not str(r.get("motivo", "")).startswith("Filtro 1:")
                ),
                None,
            )
            if recusa is None:
                continue

            item["boletins"] = [s for s in SLUGS if s in set(item.get("boletins") or []) | {slug}]
            item["boletins_rejeitados"] = [r for r in item.get("boletins_rejeitados") or [] if r is not recusa]
            item.setdefault("resgates", []).append({"boletim": slug, "motivo_da_recusa": recusa.get("motivo", "")})
            total[slug] += 1
            resgates.append({"boletim": slug, "fonte": item.get("fonte", ""), "titulo": item.get("titulo", ""), "motivo_da_recusa": recusa.get("motivo", "")})

    for item in itens:
        if not item.get("resgates"):
            continue
        nomes = ", ".join(NOMES[r["boletim"]] for r in item["resgates"] if r["boletim"] in NOMES)
        item["motivo_filtragem"] = f"[Resgatado por escassez: {nomes}] {item.get('motivo_filtragem', '')}".strip()

    return resgates


def _chave_url(url):
    return str(url or "").strip().lower().rstrip("/")


def _chave_titulo(titulo):
    return " ".join(sem_acento(titulo).lower().split())[:80]


def publicacoes_nao_devolvidas(material, itens, modelo):
    """
    Publicacoes que a coleta separou e mandou ao Gemini, mas que nao voltaram.

    O modelo mais fraco da cascata devolve poucas publicacoes: em 30/09, com os
    outros em 503, ele devolveu 1 de 24 atos da Receita e 1 de 12 normativos
    do Banco Central. Como a coleta ja traz titulo, data, link e descricao,
    nada disso precisa sumir: a publicacao vai ao portal sem Radar, com o
    motivo escrito, e a pessoa decide. Vale tambem para lote que falhou
    inteiro.

    So entra o que esta na janela ou nao tem data. A publicacao com data
    futura (as consultas da ANP mostram a data da audiencia) fica so no
    registro, para nao reaparecer todo dia.

    Devolve (itens novos, registro por fonte).
    """
    urls = {_chave_url(i.get("url")) for i in itens}
    titulos = {_chave_titulo(i.get("titulo")) for i in itens}
    novos, registro = [], {}
    for fonte in material:
        if not fonte.get("estruturado"):
            continue
        for publicacao in fonte.get("publicacoes") or []:
            if not publicacao.get("enviar"):
                continue
            if _chave_url(publicacao.get("url")) in urls or _chave_titulo(publicacao.get("titulo")) in titulos:
                continue
            anotacao = registro.setdefault(fonte["fonte"], {"ao_portal": 0, "so_registradas": 0, "titulos": []})
            anotacao["titulos"].append(publicacao.get("titulo", ""))
            if publicacao.get("data") and not publicacao.get("na_janela"):
                anotacao["so_registradas"] += 1
                continue
            anotacao["ao_portal"] += 1
            novos.append({
                "fonte": fonte["fonte"], "titulo": publicacao.get("titulo", ""), "url": publicacao.get("url", ""),
                "data_publicacao": publicacao.get("data", ""), "resumo": publicacao.get("descricao", ""),
                "boletins_confirmados": [], "boletins_rejeitados": [], "palavras_chave_detectadas": [],
                "motivo_filtragem": (
                    f"[Não classificada pela IA] A publicação foi coletada da fonte, mas o modelo "
                    f"({modelo or 'nenhum'}) não a devolveu. Escolha o Radar ou rejeite."
                ),
                "nao_classificada_pela_ia": True,
            })
    return novos, registro


def fontes_reativadas_com_erro(ativas, processadas, hoje):
    """
    Fonte que estava suspensa com data de retomada, ja voltou e continua com
    erro. E o caso do COAF, suspenso no defeso eleitoral: se depois de
    26/10 a pagina continuar restrita, o log precisa dizer.
    """
    por_nome = {x["fonte"]: x for x in processadas}
    avisos = []
    for fonte in ativas:
        if not (fonte.get("suspenso") and fonte.get("reativar_em")):
            continue
        processada = por_nome.get(fonte["fonte"]) or {}
        if processada.get("status", "ok") != "ok":
            avisos.append({"fonte": fonte["fonte"], "reativada_em": fonte["reativar_em"], "motivo_da_suspensao": fonte.get("motivo_suspensao", ""), "erro": processada.get("erro", "")})
    return avisos


def argumentos():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reprocessar", action="store_true", help="classifica de novo o dossier guardado em output/dossier, sem chamar o Firecrawl")
    return parser.parse_args()


def main():
    args = argumentos()
    if not os.getenv("GEMINI_API_KEY") or (not args.reprocessar and not os.getenv("FIRECRAWL_API_KEY")):
        raise SystemExit("GEMINI_API_KEY é obrigatória, e FIRECRAWL_API_KEY também, exceto com --reprocessar.")
    OUT.mkdir(exist_ok=True)
    if args.reprocessar:
        indice, material = carregar_dossier()
        agora = datetime.datetime.fromisoformat(indice["executado_em"])
        hoje = datetime.date.fromisoformat(indice["data_execucao"])
        inicio = datetime.date.fromisoformat(indice["janela"]["inicio"][:10])
        buscas = indice.get("buscas_complementares") or []
        creditos = {"coletas": 0, "buscas": 0, "creditos_por_busca": CREDITOS_POR_BUSCA, "total": 0}
        print(f"Reprocessando o dossier de {hoje.isoformat()}: {len(material)} fonte(s), sem Firecrawl.")
    else:
        agora = datetime.datetime.now(ZoneInfo("America/Sao_Paulo"))
        hoje = agora.date()
        inicio = hoje - datetime.timedelta(days=3 if hoje.weekday() == 0 else 1)
    fontes = fontes_execucao(datetime.datetime.combine(inicio, datetime.time(), tzinfo=agora.tzinfo), agora, hoje)
    ativas = [f for f in fontes if estado(f, hoje) == "ativa"]
    suspensas = [f for f in fontes if estado(f, hoje) == "suspensa"]
    inativas = [f for f in fontes if estado(f, hoje) == "inativa"]
    if not args.reprocessar:
        fc = Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"])
        # Lido antes de coletar: a coleta de hoje sobrescreve o dossier.
        historico = historico_de_listagem()
        material, buscas = coletar(fc, ativas, inicio, hoje, historico=historico)
        creditos = creditos_estimados(material, buscas)
        salvar_dossier(material, {"data_execucao": hoje.isoformat(), "executado_em": agora.isoformat(), "janela": {"inicio": f"{inicio.isoformat()}T00:00", "fim": agora.strftime("%Y-%m-%dT%H:%M")}, "buscas_complementares": buscas, "creditos_firecrawl_estimados": creditos})
        print(f"Firecrawl: {creditos['coletas']} coleta(s) e {creditos['buscas']} busca(s), cerca de {creditos['total']} créditos.")
    dossier, processadas = montar_dossier(material)
    inicio_iso = f"{inicio.isoformat()}T00:00"
    fim_iso = agora.strftime("%Y-%m-%dT%H:%M")
    contexto = f"\n\n## Contexto\ndata_execucao: {hoje.isoformat()}\njanela_inicio: {inicio_iso}\njanela_fim: {fim_iso}\n\n## Dossier\n"
    if dossier:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        try:
            boletim, modelos, lotes_gemini, lotes_falhos = classificar(client, PROMPT.read_text(encoding="utf-8"), contexto, dossier)
        finally:
            client.close()
    else:
        # Nenhuma fonte com publicacao na janela: nao ha o que mandar ao Gemini.
        boletim, modelos, lotes_gemini, lotes_falhos = {"itens": [], "fontes_sem_publicacao_hoje": [], "fontes_sem_resultado": [], "fontes_com_erro_tecnico": []}, [], [], []
    modelo = ", ".join(dict.fromkeys(modelos))
    tentativas = [dict(t, lote=r["lote"]) for r in lotes_gemini for t in r["tentativas"]]
    cascata = resumo_cascata(lotes_gemini)
    if cascata["aviso"]:
        print("::warning title=Cascata do Gemini::" + cascata["aviso"])
    quedas = [{"fonte": x["fonte"], "metodo": x.get("metodo"), "motivo": x.get("motivo_queda")} for x in processadas if x.get("queda_firecrawl")]
    reativadas_com_erro = fontes_reativadas_com_erro(ativas, processadas, hoje)
    for aviso in reativadas_com_erro:
        print(f"::warning title=Fonte reativada com erro::{aviso['fonte']} voltou em {aviso['reativada_em']} e continua com erro: {aviso['erro']}")
    log = {"data_execucao": hoje.isoformat(), "executado_em": agora.isoformat(), "janela": {"inicio": inicio_iso, "fim": fim_iso}, "creditos_firecrawl_estimados": creditos, "fontes_com_queda_para_firecrawl": quedas, "fontes_reativadas_com_erro": reativadas_com_erro, "buscas_complementares": buscas, "cascata_gemini": cascata, "fontes_processadas": processadas, "fontes_suspensas": [{"fonte": f["fonte"], "motivo": f.get("motivo_suspensao", "Suspensão temporária"), "reativar_em": f.get("reativar_em", "")} for f in suspensas], "fontes_inativas": [{"fonte": f["fonte"]} for f in inativas], "tentativas_gemini": tentativas, "lotes_gemini": lotes_gemini}
    if args.reprocessar:
        log["reprocessado_em"] = datetime.datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat()
        log["origem_da_coleta"] = "dossier guardado em output/dossier"
    if boletim is None:
        log["resultado"] = {"status": "falha_gemini", "boletim_anterior_preservado": BOLETIM.exists(), "dossier_guardado": (DOSSIER / "indice.json").exists()}
        salvar(LOG, log)
        raise SystemExit("Cascata Gemini falhou em todos os lotes; boletim anterior preservado.")
    # Fonte coletada sem Firecrawl e sem nada na janela nao foi ao Gemini; o
    # registro de "sem publicacao" sai daqui, e nao da resposta dele.
    boletim.setdefault("fontes_sem_publicacao_hoje", [])
    for x in processadas:
        if x.get("sem_publicacao_na_janela"):
            boletim["fontes_sem_publicacao_hoje"].append({"fonte": x["fonte"], "motivo": f"A fonte listou {x.get('publicacoes_listadas')} publicação(ões), nenhuma dentro da janela."})
    itens = []
    for item in boletim.get("itens", []):
        if not isinstance(item, dict):
            continue
        ds = str(item.get("data_publicacao", ""))[:10]
        try:
            if ds and not inicio <= datetime.date.fromisoformat(ds) <= hoje:
                continue
        except ValueError:
            item["data_publicacao"] = ""
        itens.append(item)
    nao_devolvidas, registro_nao_devolvidas = publicacoes_nao_devolvidas(material, itens, modelo)
    if nao_devolvidas:
        print(f"::warning title=Publicações não devolvidas pela IA::{len(nao_devolvidas)} publicação(ões) coletada(s) voltaram ao portal sem Radar, para decisão humana.")
        itens.extend(nao_devolvidas)
    log["publicacoes_nao_devolvidas_pela_ia"] = {
        "ao_portal_sem_radar": len(nao_devolvidas),
        "so_registradas_data_futura": sum(r["so_registradas"] for r in registro_nao_devolvidas.values()),
        "por_fonte": registro_nao_devolvidas,
    }
    bloqueios, rejeicoes, palavras = {}, Counter(), Counter()
    for item in itens:
        fonte = item.get("fonte", "")
        permitidos = set(MAPA.get(chave_fonte(fonte), []))
        sugeridos = {s for s in item.get("boletins_confirmados", []) if s in SLUGS}
        finais = [s for s in SLUGS if s in permitidos & sugeridos]
        impedidos = sugeridos - permitidos
        if exclusao_institucional(item):
            item["exclusao_editorial_automatica"] = "Comunicação institucional sem impacto jurídico externo concreto."
            finais = []
        rejs = [x for x in item.get("boletins_rejeitados", []) if isinstance(x, dict)]
        for slug in impedidos:
            bloqueios.setdefault(slug, []).append(item.get("titulo", ""))
            if slug not in {x.get("boletim") for x in rejs}:
                rejs.append({"boletim": slug, "motivo": f"Filtro 1: fonte '{fonte}' não está mapeada para este Radar"})
        item["boletins_rejeitados"] = rejs
        item["boletins"] = finais
        for p in item.get("palavras_chave_detectadas", []):
            if isinstance(p, str) and p.strip():
                palavras[p.lower().strip()] += 1
        for r in rejs:
            if r.get("boletim"):
                rejeicoes[r["boletim"]] += 1
    resgates = resgatar_por_escassez(itens, PISO_RESGATE)
    if resgates:
        print(f"Resgate por escassez: {len(resgates)} publicação(ões) promovida(s).")
        rejeicoes = Counter()
        for item in itens:
            for r in item.get("boletins_rejeitados") or []:
                if isinstance(r, dict) and r.get("boletim"):
                    rejeicoes[r["boletim"]] += 1

    erros = [{"fonte": x.get("fonte"), "motivo": x.get("erro", "Erro técnico") } for x in processadas if x.get("status") != "ok"]
    ja_com_erro = {e["fonte"] for e in erros}
    for nome in lotes_falhos:
        if nome not in ja_com_erro:
            erros.append({"fonte": nome, "motivo": "A classificação deste lote falhou em todos os modelos da cascata."})
            ja_com_erro.add(nome)
    nomes_erro = {x["fonte"] for x in erros}
    def lista(chave, padrao):
        resultado = []
        for x in boletim.get(chave, []):
            fonte = x.get("fonte", "") if isinstance(x, dict) else str(x)
            motivo = x.get("motivo", padrao) if isinstance(x, dict) else padrao
            if fonte and fonte not in nomes_erro:
                resultado.append({"fonte": fonte, "motivo": motivo})
        return resultado
    sem_resultado = lista("fontes_sem_resultado", "A página foi coletada, mas nenhuma publicação individual utilizável foi extraída.")
    sem_publicacao = lista("fontes_sem_publicacao_hoje", "Nenhuma publicação foi identificada dentro da janela.")
    por_fonte = Counter(i.get("fonte", "") for i in itens)
    sr, sp = {x["fonte"] for x in sem_resultado}, {x["fonte"] for x in sem_publicacao}
    validacao = []
    for x in processadas:
        fonte = x.get("fonte"); aprovadas = por_fonte.get(fonte, 0)
        situacao = "erro_tecnico" if x.get("status") != "ok" else "itens_incluidos" if aprovadas else "sem_publicacao_individual_extraida" if fonte in sr else "sem_publicacao_na_janela" if fonte in sp else "publicacoes_sem_aderencia_editorial"
        validacao.append({"fonte": fonte, "status_coleta": x.get("status"), "publicacoes_localizadas": x.get("publicacoes_localizadas", 0), "publicacoes_aprovadas": aprovadas, "status_editorial": situacao, "busca_complementar_executada": x.get("busca_complementar_executada", False), "conteudo_truncado": x.get("conteudo_truncado", False)})
    stats = {s: {"nome": NOMES[s], "clusters": CLUSTERS[s], "total": sum(s in i.get("boletins", []) for i in itens)} for s in SLUGS}
    boletim.update({"data_execucao": hoje.isoformat(), "janela_aplicada": {"inicio": inicio_iso, "fim": fim_iso}, "modelo_gemini_utilizado": modelo, "itens": itens, "fontes_sem_resultado": sem_resultado, "fontes_sem_publicacao_hoje": sem_publicacao, "fontes_com_erro_tecnico": erros, "validacao_fontes": validacao, "estatisticas_por_boletim": stats})
    boletim["boletins_config"] = {"descricao": "Informativo com atualizações legislativas, regulamentações, consultas públicas e publicações de órgãos reguladores.", "boletins_disponiveis": SLUGS, "nomes_radares": NOMES, "clusters_por_boletim": CLUSTERS, "fontes_email_pendentes": EMAIL, "fontes_pendentes_integracao": {"regulatorio-oleo-gas": ["CADE - DOU", "MEC - DOU", "MDIC - DOU", "Câmara dos Deputados", "Senado Federal", "Agência Eixos"]}, "mapeamento_fonte_boletim": MAPA, "fontes_em_defeso": log["fontes_suspensas"]}
    boletim["auditoria"] = {"total_itens": len(itens), "itens_com_alguma_rejeicao": sum(bool(i.get("boletins_rejeitados")) for i in itens), "itens_com_bloqueio_f1": len(
        {
            titulo
            for titulos in bloqueios.values()
            for titulo in titulos
            if titulo
        }
    ), "rejeicoes_por_boletim": dict(rejeicoes), "resgates_por_escassez": resgates, "cascata_gemini": cascata, "nao_classificadas_pela_ia": len(nao_devolvidas), "top_palavras_chave_detectadas": [{"palavra": p, "ocorrencias": c} for p, c in palavras.most_common(20)]}
    log["resultado"] = {"status": "sucesso", "modelo_gemini_utilizado": modelo, "itens_aceitos": len(itens), "fontes_ativas": len(material), "fontes_suspensas": len(suspensas), "fontes_inativas": len(inativas), "fontes_sem_resultado": len(sem_resultado), "fontes_sem_publicacao_hoje": len(sem_publicacao), "fontes_com_erro_tecnico": len(erros), "itens_por_boletim": stats, "filtro1_bloqueios": {s: len(v) for s, v in bloqueios.items()}, "auditoria": boletim["auditoria"]}
    if bloqueios:
        log["filtro1_bloqueios_detalhe"] = bloqueios
    salvar(BOLETIM, boletim)
    salvar(LOG, log)
    print(f"Concluído: {len(itens)} itens; modelo {modelo}.")

if __name__ == "__main__":
    main()
