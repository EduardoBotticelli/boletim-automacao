"""Coleta, complementa, classifica e audita as fontes dos Radares."""
import datetime
import json
import os
import time
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from firecrawl import Firecrawl
from google import genai
from google.genai import types

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
LIMIAR_DINAMICO = 5000
BUSCA_LIMITE = 30
# Teto do bloco da busca complementar dentro de MAX_CHARS. Garante que a
# pagina continue tendo espaco mesmo quando a busca traz muitos resultados.
LIMITE_BUSCA_CHARS = MAX_CHARS * 2 // 5
# Fontes por chamada ao Gemini. O prompt unico com as trinta passava de 200
# mil tokens e levava a 429 nos modelos melhores.
LOTE_FONTES = 6
INTERVALO_LOTES = 4
# Piso de publicacoes por Radar para o resgate por escassez.
PISO_RESGATE = 5


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


def busca_complementar(fc, fonte, inicio, fim):
    consulta = f"site:{escopo(fonte['url'])} after:{inicio.isoformat()} before:{(fim + datetime.timedelta(days=1)).isoformat()}"
    resultado = fc.search(consulta, limit=BUSCA_LIMITE)
    registros, vistos = [], set()
    for item in getattr(resultado, "web", None) or []:
        url = str(getattr(item, "url", "") or "").strip()
        titulo = str(getattr(item, "title", "") or "").strip()
        descricao = str(getattr(item, "description", "") or getattr(item, "snippet", "") or "").strip()
        if not url or url in vistos or url.rstrip("/") == fonte["url"].rstrip("/"):
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
        {"fonte": "Planalto | Resenha Diaria", "categoria": "Legislação Federal", "url": f"http://www4.planalto.gov.br/legislacao/portal-legis/resenha-diaria/{meses[hoje.month-1]}-resenha-diaria", "ativo": True},
        {"fonte": "Banco Central | Normas", "categoria": "Financeiro e Mercado de Capitais", "url": f"https://www.bcb.gov.br/estabilidadefinanceira/buscanormas?dataInicioBusca={di}&dataFimBusca={df}&tipoDocumento=Todos", "ativo": True},
        {"fonte": "CCEE | Noticias", "categoria": "Energia e Recursos", "url": f"https://www.ccee.org.br/busca-ccee?q=&dtIni={di}&dtFim={df}&structure=ccee-noticias&ordenacao=Mais%20recentes", "ativo": True},
    ]
    return dinamicas + fontes


def gemini(cliente, prompt):
    logs = []
    for modelo in MODELOS:
        for tentativa in (1, 2):
            try:
                resposta = cliente.models.generate_content(model=modelo, contents=prompt, config=types.GenerateContentConfig(temperature=0.15, response_mime_type="application/json"))
                dados = json.loads(resposta.text or "")
                if not isinstance(dados, dict) or not isinstance(dados.get("itens"), list):
                    raise ValueError("JSON sem itens")
                logs.append({"modelo": modelo, "tentativa": tentativa, "status": "sucesso"})
                return dados, modelo, logs
            except Exception as erro:
                logs.append({"modelo": modelo, "tentativa": tentativa, "status": "erro", "erro": erro_resumo(erro)})
                if tentativa == 1:
                    time.sleep(10)
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

    for numero, lote in enumerate(lotes_de(dossier, LOTE_FONTES), 1):
        nomes = [d.get("fonte", "") for d in lote]
        print(f"Gemini lote {numero}/{total}: {len(lote)} fonte(s)")
        prompt = base + contexto + json.dumps(lote, ensure_ascii=False)
        dados, modelo, tentativas = gemini(cliente, prompt)
        registro.append({"lote": numero, "fontes": nomes, "modelo": modelo, "tentativas": tentativas})

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


def main():
    if not os.getenv("FIRECRAWL_API_KEY") or not os.getenv("GEMINI_API_KEY"):
        raise SystemExit("FIRECRAWL_API_KEY e GEMINI_API_KEY são obrigatórias.")
    OUT.mkdir(exist_ok=True)
    agora = datetime.datetime.now(ZoneInfo("America/Sao_Paulo"))
    hoje = agora.date()
    inicio = hoje - datetime.timedelta(days=3 if hoje.weekday() == 0 else 1)
    fontes = fontes_execucao(datetime.datetime.combine(inicio, datetime.time(), tzinfo=agora.tzinfo), agora, hoje)
    ativas = [f for f in fontes if estado(f, hoje) == "ativa"]
    suspensas = [f for f in fontes if estado(f, hoje) == "suspensa"]
    inativas = [f for f in fontes if estado(f, hoje) == "inativa"]
    fc = Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"])
    dossier, processadas = [], []
    for indice, fonte in enumerate(ativas, 1):
        nome = fonte["fonte"]
        print(f"[{indice}/{len(ativas)}] {nome}")
        try:
            resultado = scrape_retry(fc, fonte["url"], not fonte.get("pagina_inteira"))
            bruto = resultado.markdown or ""
            complementar = len(bruto) < LIMIAR_DINAMICO or len(bruto) > MAX_CHARS or fonte.get("tipo_coleta") in {"lista_estruturada", "indice_documentos"}
            descobertas = []
            if complementar:
                try:
                    descobertas = busca_complementar(fc, fonte, inicio, hoje)
                except Exception as erro:
                    print("Busca complementar falhou: " + erro_resumo(erro, 180))
            conteudo, chars_busca, truncado = montar_conteudo(bruto, descobertas)
            marcador = pagina_erro(conteudo)
            if marcador:
                motivo = f"A origem retornou página de erro/manutenção ({marcador})."
                dossier.append({"fonte": nome, "categoria": fonte["categoria"], "url": fonte["url"], "conteudo": "", "erro_tecnico": motivo})
                processadas.append({"fonte": nome, "status": "erro_conteudo_origem", "tamanho_chars": len(conteudo), "erro": motivo})
            elif len(conteudo) < MIN_CHARS:
                motivo = f"Conteúdo insuficiente ({len(conteudo)} caracteres)."
                dossier.append({"fonte": nome, "categoria": fonte["categoria"], "url": fonte["url"], "conteudo": "", "erro_tecnico": motivo})
                processadas.append({"fonte": nome, "status": "erro_tecnico", "tamanho_chars": len(conteudo), "erro": motivo})
            else:
                dossier.append({"fonte": nome, "categoria": fonte["categoria"], "url": fonte["url"], "tipo_coleta": fonte.get("tipo_coleta", "pagina"), "publicacoes_localizadas": len(descobertas), "conteudo": conteudo})
                processadas.append({"fonte": nome, "status": "ok", "tamanho_chars": len(conteudo), "publicacoes_localizadas": len(descobertas), "busca_complementar_executada": complementar, "chars_busca_complementar": chars_busca, "conteudo_truncado": truncado, "pagina_inteira": bool(fonte.get("pagina_inteira"))})
        except Exception as erro:
            motivo = erro_resumo(erro, 300)
            dossier.append({"fonte": nome, "categoria": fonte["categoria"], "url": fonte["url"], "conteudo": "", "erro_tecnico": motivo})
            processadas.append({"fonte": nome, "status": "erro", "erro": motivo})
        if indice < len(ativas):
            time.sleep(6.5)
    inicio_iso = f"{inicio.isoformat()}T00:00"
    fim_iso = agora.strftime("%Y-%m-%dT%H:%M")
    contexto = f"\n\n## Contexto\ndata_execucao: {hoje.isoformat()}\njanela_inicio: {inicio_iso}\njanela_fim: {fim_iso}\n\n## Dossier\n"
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    try:
        boletim, modelos, lotes_gemini, lotes_falhos = classificar(client, PROMPT.read_text(encoding="utf-8"), contexto, dossier)
    finally:
        client.close()
    modelo = ", ".join(dict.fromkeys(modelos))
    tentativas = [dict(t, lote=r["lote"]) for r in lotes_gemini for t in r["tentativas"]]
    log = {"data_execucao": hoje.isoformat(), "executado_em": agora.isoformat(), "janela": {"inicio": inicio_iso, "fim": fim_iso}, "fontes_processadas": processadas, "fontes_suspensas": [{"fonte": f["fonte"], "motivo": f.get("motivo_suspensao", "Suspensão temporária"), "reativar_em": f.get("reativar_em", "")} for f in suspensas], "fontes_inativas": [{"fonte": f["fonte"]} for f in inativas], "tentativas_gemini": tentativas, "lotes_gemini": lotes_gemini}
    if boletim is None:
        log["resultado"] = {"status": "falha_gemini", "boletim_anterior_preservado": BOLETIM.exists()}
        salvar(LOG, log)
        raise SystemExit("Cascata Gemini falhou em todos os lotes; boletim anterior preservado.")
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
    ), "rejeicoes_por_boletim": dict(rejeicoes), "resgates_por_escassez": resgates, "top_palavras_chave_detectadas": [{"palavra": p, "ocorrencias": c} for p, c in palavras.most_common(20)]}
    log["resultado"] = {"status": "sucesso", "modelo_gemini_utilizado": modelo, "itens_aceitos": len(itens), "fontes_ativas": len(ativas), "fontes_suspensas": len(suspensas), "fontes_inativas": len(inativas), "fontes_sem_resultado": len(sem_resultado), "fontes_sem_publicacao_hoje": len(sem_publicacao), "fontes_com_erro_tecnico": len(erros), "itens_por_boletim": stats, "filtro1_bloqueios": {s: len(v) for s, v in bloqueios.items()}, "auditoria": boletim["auditoria"]}
    if bloqueios:
        log["filtro1_bloqueios_detalhe"] = bloqueios
    salvar(BOLETIM, boletim)
    salvar(LOG, log)
    print(f"Concluído: {len(itens)} itens; modelo {modelo}.")

if __name__ == "__main__":
    main()
