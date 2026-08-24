"""
Radares Lobo de Rizzo - geracao automatica.
Arquitetura: Firecrawl (coleta) -> Gemini (Filtro 2 tematico) -> JSON.

VERSAO 2026.08.2
- Mantem os 9 slugs tecnicos existentes.
- Filtro 1: fonte -> Radares permitidos pela matriz editorial.
- Filtro 2: conteudo -> Radares sugeridos pelo Gemini.
- Controla o limite por minuto do Firecrawl e repete erros 429.
- Normaliza listas de fontes devolvidas pelo Gemini como strings ou objetos.
- Usa o SDK atual google-genai.
"""

import datetime
import json
import os
import sys
import time
from collections import Counter
from zoneinfo import ZoneInfo

from firecrawl import Firecrawl
from google import genai
from google.genai import types

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTES_PATH = os.path.join(BASE_DIR, "fontes.json")
PROMPT_PATH = os.path.join(BASE_DIR, "prompt.md")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "boletim.json")
LOG_PATH = os.path.join(OUTPUT_DIR, "log_execucao.json")

FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
MIN_CONTEUDO_CHARS = 500
MAX_CONTEUDO_CHARS = 10000
INTERVALO_ENTRE_SCRAPES_SEGUNDOS = 6.5
MAX_TENTATIVAS_SCRAPE = 3
ESPERA_RATE_LIMIT_SEGUNDOS = 65

DESCRICAO_RADARES = (
    "Informativo com atualizacoes legislativas, regulamentacoes, "
    "consultas publicas e publicacoes de orgaos reguladores."
)

BOLETINS_DISPONIVEIS = [
    "trabalhista-empresarial",
    "direito-tributario",
    "societario-ma",
    "mercado-capitais-fundos",
    "regulatorio-oleo-gas",
    "imobiliario-infraestrutura",
    "ambiental-esg",
    "propriedade-intelectual",
    "contencioso-civel",
]

NOMES_RADARES = {
    "trabalhista-empresarial": "Radar Trabalhista Empresarial",
    "direito-tributario": "Radar Tributario",
    "societario-ma": "Radar Societario, Fusoes e Aquisicoes",
    "mercado-capitais-fundos": "Radar Mercado de Capitais e Fundos de Investimento",
    "regulatorio-oleo-gas": "Radar Regulatorio e Oleo e Gas",
    "imobiliario-infraestrutura": "Radar Negocios Imobiliarios e Infraestrutura",
    "ambiental-esg": "Radar Ambiental e ESG",
    "propriedade-intelectual": "Radar Propriedade Intelectual, Tecnologia e Privacidade",
    "contencioso-civel": "Radar Solucao de Conflitos",
}

CLUSTERS_POR_BOLETIM = {
    "trabalhista-empresarial": ["Amber", "Pink"],
    "direito-tributario": ["Tributario Consultivo", "Tributario Contencioso"],
    "societario-ma": ["White", "Purple", "Due Diligence"],
    "mercado-capitais-fundos": ["Financeiro Green", "Fundos"],
    "regulatorio-oleo-gas": ["Regulatorio", "Oleo & Gas Blue"],
    "imobiliario-infraestrutura": ["Imobiliario", "Infraestrutura"],
    "ambiental-esg": ["Ambiental"],
    "propriedade-intelectual": ["Propriedade Intelectual"],
    "contencioso-civel": ["Contencioso Carbon", "Contencioso Gold"],
}

FONTES_EM_DEFESO = [
    "CGU | Noticias",
    "Ministerio do Meio Ambiente | Noticias",
    "Secretaria de Premios e Apostas | Noticias",
]

FONTES_PENDENTES_INTEGRACAO = {
    "regulatorio-oleo-gas": [
        "CADE - Diario Oficial da Uniao (Secoes 1 e 3)",
        "MEC - Diario Oficial da Uniao (Secoes 1 e 3)",
        "MDIC - Diario Oficial da Uniao (Secao 1)",
        "ANATEL",
        "SUSEP",
        "ANTT",
        "Portal da Legislacao",
        "Portal da Camara dos Deputados",
        "Portal do Senado Federal",
        "Consulta Publica da ANP",
        "Consulta Previa da ANP",
        "ANP - Pautas e atas de reunioes de diretoria",
        "Consulta Publica do MME",
        "Agencia Eixos",
    ]
}

FONTE_PARA_BOLETINS = {
    "Planalto | Resenha Diaria": BOLETINS_DISPONIVEIS.copy(),
    "Destaques do D.O.U.": [
        "trabalhista-empresarial", "direito-tributario",
        "regulatorio-oleo-gas", "contencioso-civel",
    ],
    "Ministerio da Fazenda | Noticias": BOLETINS_DISPONIVEIS.copy(),
    "CGU | Noticias": ["trabalhista-empresarial", "regulatorio-oleo-gas"],
    "Receita Federal | Normas": ["direito-tributario"],
    "Banco Central | Normas": [
        "direito-tributario", "societario-ma", "mercado-capitais-fundos",
    ],
    "COAF | Noticias": ["direito-tributario", "mercado-capitais-fundos"],
    "CVM | Noticias": [
        "mercado-capitais-fundos", "regulatorio-oleo-gas",
        "imobiliario-infraestrutura",
    ],
    "B3 | Oficios e Comunicados": ["mercado-capitais-fundos"],
    "ANP | Noticias": [
        "regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg",
    ],
    "ANEEL | Ultimas Noticias": [
        "regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg",
    ],
    "ANM | Noticias": [
        "regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg",
    ],
    "ANVISA | Noticias": ["regulatorio-oleo-gas"],
    "SENACON | Noticias": [
        "regulatorio-oleo-gas", "propriedade-intelectual", "contencioso-civel",
    ],
    "Secretaria de Premios e Apostas | Noticias": [],
    "ONS | Noticias": ["imobiliario-infraestrutura", "ambiental-esg"],
    "CCEE | Noticias": ["imobiliario-infraestrutura", "ambiental-esg"],
    "EPE | Noticias": [
        "regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg",
    ],
    "MME | Noticias": [
        "regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg",
    ],
    "Ministerio do Meio Ambiente | Noticias": ["ambiental-esg"],
    "Ministerio da Agricultura | Noticias": [
        "imobiliario-infraestrutura", "ambiental-esg",
    ],
    "INPI | Noticias": ["propriedade-intelectual"],
    "ANPD | Noticias": ["propriedade-intelectual"],
    "ANTAQ | Noticias": ["regulatorio-oleo-gas"],
    "CNPE | Comunicacoes": ["regulatorio-oleo-gas"],
    "Kollemata | Decretos": ["imobiliario-infraestrutura"],
}

FONTES_EMAIL_PENDENTES = {
    "trabalhista-empresarial": [],
    "direito-tributario": ["Tributario.com"],
    "societario-ma": ["Latin Lawyer"],
    "mercado-capitais-fundos": ["Latin Lawyer"],
    "regulatorio-oleo-gas": ["Agencia iNFRA", "iNFRA Energia", "Agencia Eixos"],
    "imobiliario-infraestrutura": [
        "Agencia iNFRA", "iNFRA Energia", "IRIB", "Latin Lawyer",
    ],
    "ambiental-esg": ["RC Ambiental"],
    "propriedade-intelectual": [],
    "contencioso-civel": [],
}

ALIASES_FONTES = {
    "Ministério da Fazenda | Notícias": "Ministerio da Fazenda | Noticias",
    "CGU | Notícias": "CGU | Noticias",
    "B3 | Ofícios e Comunicados": "B3 | Oficios e Comunicados",
    "ANP | Notícias": "ANP | Noticias",
    "ANEEL | Últimas Notícias": "ANEEL | Ultimas Noticias",
    "ANM | Notícias": "ANM | Noticias",
    "ANVISA | Notícias": "ANVISA | Noticias",
    "SENACON | Notícias": "SENACON | Noticias",
    "Secretaria de Prêmios e Apostas | Notícias": "Secretaria de Premios e Apostas | Noticias",
    "ONS | Notícias": "ONS | Noticias",
    "EPE | Notícias": "EPE | Noticias",
    "MME | Notícias": "MME | Noticias",
    "Ministério do Meio Ambiente | Notícias": "Ministerio do Meio Ambiente | Noticias",
    "Ministério da Agricultura | Notícias": "Ministerio da Agricultura | Noticias",
    "INPI | Notícias": "INPI | Noticias",
    "ANPD | Notícias": "ANPD | Noticias",
    "COAF | Notícias": "COAF | Noticias",
    "CVM | Notícias": "CVM | Noticias",
    "ANTAQ | Notícias": "ANTAQ | Noticias",
    "CNPE | Comunicações": "CNPE | Comunicacoes",
}


def exigir_secrets():
    if not FIRECRAWL_API_KEY:
        print("ERRO: FIRECRAWL_API_KEY nao encontrada.")
        sys.exit(1)
    if not GEMINI_API_KEY:
        print("ERRO: GEMINI_API_KEY nao encontrada.")
        sys.exit(1)


def normalizar_nome_fonte(nome):
    return ALIASES_FONTES.get(nome, nome)


def normalizar_lista_objetos(valor, motivo_padrao):
    """Aceita lista de objetos ou lista de strings devolvida pelo Gemini."""
    if not isinstance(valor, list):
        return []
    resultado = []
    vistos = set()
    for item in valor:
        if isinstance(item, dict):
            fonte = str(item.get("fonte", "")).strip()
            motivo = str(item.get("motivo", motivo_padrao)).strip() or motivo_padrao
        elif isinstance(item, str):
            fonte = item.strip()
            motivo = motivo_padrao
        else:
            continue
        if fonte and fonte not in vistos:
            vistos.add(fonte)
            resultado.append({"fonte": fonte, "motivo": motivo})
    return resultado


def eh_rate_limit(erro):
    texto = str(erro).lower()
    return "rate limit" in texto or "429" in texto or "too many requests" in texto


def scrape_com_retry(firecrawl, url):
    ultimo_erro = None
    for tentativa in range(1, MAX_TENTATIVAS_SCRAPE + 1):
        try:
            return firecrawl.scrape(
                url,
                formats=["markdown"],
                only_main_content=True,
            )
        except Exception as erro:
            ultimo_erro = erro
            if not eh_rate_limit(erro) or tentativa == MAX_TENTATIVAS_SCRAPE:
                raise
            print(
                "      Limite do Firecrawl atingido. Nova tentativa "
                + str(tentativa + 1)
                + "/"
                + str(MAX_TENTATIVAS_SCRAPE)
            )
            time.sleep(ESPERA_RATE_LIMIT_SEGUNDOS)
    raise ultimo_erro


def carregar_fontes(janela_inicio_dt, agora, hoje):
    with open(FONTES_PATH, "r", encoding="utf-8") as arquivo:
        fontes = json.load(arquivo)

    data_ini_url = janela_inicio_dt.strftime("%d/%m/%Y").replace("/", "%2F")
    data_fim_url = agora.strftime("%d/%m/%Y").replace("/", "%2F")
    meses = [
        "janeiro", "fevereiro", "marco", "abril", "maio", "junho",
        "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
    ]
    url_planalto = (
        "http://www4.planalto.gov.br/legislacao/portal-legis/resenha-diaria/"
        + meses[hoje.month - 1]
        + "-resenha-diaria"
    )
    url_bcb = (
        "https://www.bcb.gov.br/estabilidadefinanceira/buscanormas?dataInicioBusca="
        + data_ini_url + "&dataFimBusca=" + data_fim_url + "&tipoDocumento=Todos"
    )
    url_ccee = (
        "https://www.ccee.org.br/busca-ccee?q=&dtIni=" + data_ini_url
        + "&dtFim=" + data_fim_url
        + "&structure=ccee-noticias&ordenacao=Mais%20recentes"
    )

    dinamicas = [
        {"fonte": "Planalto | Resenha Diaria", "categoria": "Legislacao Federal", "url": url_planalto, "ativo": True},
        {"fonte": "Banco Central | Normas", "categoria": "Financeiro e Mercado de Capitais", "url": url_bcb, "ativo": True},
        {"fonte": "CCEE | Noticias", "categoria": "Energia e Recursos", "url": url_ccee, "ativo": True},
    ]
    return dinamicas + fontes


def ordenar_slugs(slugs):
    conjunto = set(slugs)
    return [slug for slug in BOLETINS_DISPONIVEIS if slug in conjunto]


def main():
    exigir_secrets()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    brt = ZoneInfo("America/Sao_Paulo")
    agora = datetime.datetime.now(brt)
    hoje = agora.date()
    dias_retroativos = 3 if hoje.weekday() == 0 else 1
    janela_inicio_dt = datetime.datetime.combine(
        hoje - datetime.timedelta(days=dias_retroativos),
        datetime.time(0, 0),
        tzinfo=brt,
    )
    janela_inicio = janela_inicio_dt.strftime("%Y-%m-%dT%H:%M")
    janela_fim = agora.strftime("%Y-%m-%dT%H:%M")

    print("Radares - execucao em " + agora.strftime("%Y-%m-%d %H:%M") + " BRT")
    print("Janela: " + janela_inicio + " ate " + janela_fim)

    fontes = carregar_fontes(janela_inicio_dt, agora, hoje)
    fontes_ativas = [fonte for fonte in fontes if fonte.get("ativo", True)]
    fontes_inativas = [fonte for fonte in fontes if not fonte.get("ativo", True)]

    print(str(len(fontes_ativas)) + " fontes ativas a processar")
    if fontes_inativas:
        print(
            str(len(fontes_inativas)) + " fontes inativas: "
            + ", ".join(fonte["fonte"] for fonte in fontes_inativas)
        )

    with open(PROMPT_PATH, "r", encoding="utf-8") as arquivo:
        prompt_base = arquivo.read()

    firecrawl = Firecrawl(api_key=FIRECRAWL_API_KEY)
    dossier = []
    log = {
        "data_execucao": hoje.isoformat(),
        "executado_em": agora.isoformat(),
        "janela": {"inicio": janela_inicio, "fim": janela_fim},
        "fontes_processadas": [],
    }

    for indice, fonte in enumerate(fontes_ativas, 1):
        nome = fonte["fonte"]
        url = fonte["url"]
        categoria = fonte["categoria"]
        print("  [" + str(indice) + "/" + str(len(fontes_ativas)) + "] " + nome)
        try:
            resultado = scrape_com_retry(firecrawl, url)
            conteudo = (resultado.markdown or "")[:MAX_CONTEUDO_CHARS]
            if len(conteudo) < MIN_CONTEUDO_CHARS:
                detalhe = "Conteudo muito curto (" + str(len(conteudo)) + " chars)"
                dossier.append({"fonte": nome, "categoria": categoria, "url": url, "conteudo": "", "erro_tecnico": detalhe})
                log["fontes_processadas"].append({"fonte": nome, "status": "erro_tecnico", "tamanho_chars": len(conteudo), "detalhe": detalhe})
                print("      " + detalhe)
            else:
                dossier.append({"fonte": nome, "categoria": categoria, "url": url, "conteudo": conteudo})
                log["fontes_processadas"].append({"fonte": nome, "status": "ok", "tamanho_chars": len(conteudo)})
                print("      OK - " + str(len(conteudo)) + " chars")
        except Exception as erro:
            mensagem = str(erro)[:300]
            dossier.append({"fonte": nome, "categoria": categoria, "url": url, "conteudo": "", "erro_tecnico": mensagem})
            log["fontes_processadas"].append({"fonte": nome, "status": "erro", "erro": mensagem})
            print("      Erro: " + mensagem)
        finally:
            if indice < len(fontes_ativas):
                time.sleep(INTERVALO_ENTRE_SCRAPES_SEGUNDOS)

    print("\nEnviando dossier para o Gemini...")
    cliente = genai.Client(api_key=GEMINI_API_KEY)
    prompt_final = (
        prompt_base
        + "\n\n## Contexto desta execucao\n\n"
        + "data_execucao: " + hoje.isoformat()
        + "\njanela_inicio: " + janela_inicio
        + "\njanela_fim: " + janela_fim
        + "\n\n## Dossier das fontes\n\n"
        + json.dumps(dossier, ensure_ascii=False, indent=2)
    )

    texto = ""
    ultimo_erro = ""
    for tentativa in range(1, 4):
        try:
            resposta = cliente.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt_final,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    response_mime_type="application/json",
                ),
            )
            texto = resposta.text or ""
            break
        except Exception as erro:
            ultimo_erro = str(erro)
            print("Erro no Gemini (tentativa " + str(tentativa) + "/3): " + ultimo_erro)
            if tentativa < 3:
                time.sleep(3 * tentativa)
    cliente.close()

    if not texto:
        texto = json.dumps({
            "data_execucao": hoje.isoformat(),
            "erro": "Falha na consulta ao Gemini",
            "detalhe_erro": ultimo_erro[:500],
            "itens": [],
            "fontes_sem_resultado": [],
            "fontes_sem_publicacao_hoje": [],
            "fontes_com_erro_tecnico": [],
        }, ensure_ascii=False)

    try:
        boletim_json = json.loads(texto)
        print("Gemini retornou JSON valido")
    except json.JSONDecodeError:
        boletim_json = {
            "data_execucao": hoje.isoformat(),
            "erro": "JSON invalido retornado pelo Gemini",
            "resposta_bruta": texto,
            "itens": [],
            "fontes_sem_resultado": [],
            "fontes_sem_publicacao_hoje": [],
            "fontes_com_erro_tecnico": [],
        }

    boletim_json["data_execucao"] = hoje.isoformat()
    boletim_json["janela_aplicada"] = {"inicio": janela_inicio, "fim": janela_fim}
    boletim_json["fontes_sem_resultado"] = normalizar_lista_objetos(
        boletim_json.get("fontes_sem_resultado", []),
        "A pagina foi acessada, mas nao foi possivel identificar conteudo utilizavel.",
    )
    boletim_json["fontes_sem_publicacao_hoje"] = normalizar_lista_objetos(
        boletim_json.get("fontes_sem_publicacao_hoje", []),
        "Nenhuma publicacao foi identificada dentro da janela.",
    )
    boletim_json["fontes_com_erro_tecnico"] = normalizar_lista_objetos(
        boletim_json.get("fontes_com_erro_tecnico", []),
        "Erro tecnico informado durante a coleta.",
    )

    erros_dossier = [
        {"fonte": item["fonte"], "motivo": item.get("erro_tecnico", "erro tecnico")}
        for item in dossier if "erro_tecnico" in item
    ]
    nomes_com_erro = {item["fonte"] for item in erros_dossier}
    boletim_json["fontes_sem_resultado"] = [
        item for item in boletim_json["fontes_sem_resultado"]
        if item["fonte"] not in nomes_com_erro
    ]
    boletim_json["fontes_sem_publicacao_hoje"] = [
        item for item in boletim_json["fontes_sem_publicacao_hoje"]
        if item["fonte"] not in nomes_com_erro
    ]
    erros_existentes = {item["fonte"] for item in boletim_json["fontes_com_erro_tecnico"]}
    for item in erros_dossier:
        if item["fonte"] not in erros_existentes:
            boletim_json["fontes_com_erro_tecnico"].append(item)

    itens_originais = boletim_json.get("itens", [])
    if not isinstance(itens_originais, list):
        itens_originais = []
    itens_validados = []
    itens_descartados = []
    for item in itens_originais:
        if not isinstance(item, dict):
            continue
        data_str = str(item.get("data_publicacao", "")).strip()
        if not data_str:
            itens_validados.append(item)
            continue
        try:
            data_item = datetime.date.fromisoformat(data_str[:10])
            if janela_inicio_dt.date() <= data_item <= hoje:
                itens_validados.append(item)
            else:
                itens_descartados.append({"titulo": item.get("titulo", "")[:80], "data": data_str, "motivo": "fora da janela"})
        except (ValueError, TypeError):
            item["data_publicacao"] = ""
            itens_validados.append(item)

    bloqueios_detalhe = {}
    itens_com_bloqueio = 0
    itens_com_rejeicao = 0
    palavras_counter = Counter()
    rejeicoes_counter = Counter()

    for item in itens_validados:
        fonte_original = str(item.get("fonte", ""))
        fonte_mapeamento = normalizar_nome_fonte(fonte_original)
        permitidos = set(FONTE_PARA_BOLETINS.get(fonte_mapeamento, []))
        confirmados = item.get("boletins_confirmados", [])
        if not isinstance(confirmados, list):
            confirmados = []
        sugeridos = {slug for slug in confirmados if slug in BOLETINS_DISPONIVEIS}
        finais = ordenar_slugs(permitidos & sugeridos)
        bloqueados = sugeridos - permitidos

        if bloqueados:
            itens_com_bloqueio += 1
            for slug in ordenar_slugs(bloqueados):
                bloqueios_detalhe.setdefault(slug, []).append(item.get("titulo", "")[:60])

        rejeitados = item.get("boletins_rejeitados", [])
        if not isinstance(rejeitados, list):
            rejeitados = []
        rejeitados = [r for r in rejeitados if isinstance(r, dict)]
        rejeicoes_existentes = {r.get("boletim") for r in rejeitados}
        for slug in ordenar_slugs(bloqueados):
            if slug not in rejeicoes_existentes:
                rejeitados.append({
                    "boletim": slug,
                    "motivo": "Filtro 1: fonte '" + fonte_original + "' nao esta mapeada para este Radar",
                })
        item["boletins_rejeitados"] = rejeitados

        palavras = item.get("palavras_chave_detectadas", [])
        if not isinstance(palavras, list):
            palavras = []
        item["palavras_chave_detectadas"] = palavras
        if rejeitados:
            itens_com_rejeicao += 1
        for palavra in palavras:
            if isinstance(palavra, str) and palavra.strip():
                palavras_counter[palavra.lower().strip()] += 1
        for rejeicao in rejeitados:
            if rejeicao.get("boletim"):
                rejeicoes_counter[rejeicao["boletim"]] += 1
        item["boletins"] = finais

    boletim_json["itens"] = itens_validados
    boletim_json["boletins_config"] = {
        "descricao": DESCRICAO_RADARES,
        "boletins_disponiveis": BOLETINS_DISPONIVEIS,
        "nomes_radares": NOMES_RADARES,
        "clusters_por_boletim": CLUSTERS_POR_BOLETIM,
        "fontes_email_pendentes": FONTES_EMAIL_PENDENTES,
        "fontes_pendentes_integracao": FONTES_PENDENTES_INTEGRACAO,
        "mapeamento_fonte_boletim": FONTE_PARA_BOLETINS,
        "fontes_em_defeso": FONTES_EM_DEFESO,
    }

    stats = {}
    for slug in BOLETINS_DISPONIVEIS:
        stats[slug] = {
            "nome": NOMES_RADARES[slug],
            "clusters": CLUSTERS_POR_BOLETIM[slug],
            "total": sum(1 for item in itens_validados if slug in item.get("boletins", [])),
        }
    boletim_json["estatisticas_por_boletim"] = stats
    boletim_json["auditoria"] = {
        "total_itens": len(itens_validados),
        "itens_com_alguma_rejeicao": itens_com_rejeicao,
        "itens_com_bloqueio_f1": itens_com_bloqueio,
        "rejeicoes_por_boletim": dict(rejeicoes_counter),
        "top_palavras_chave_detectadas": [
            {"palavra": p, "ocorrencias": c} for p, c in palavras_counter.most_common(20)
        ],
    }

    log["resultado"] = {
        "itens_aceitos": len(itens_validados),
        "itens_descartados_pos_validacao": len(itens_descartados),
        "fontes_ativas": len(fontes_ativas),
        "fontes_inativas": len(fontes_inativas),
        "fontes_sem_resultado": len(boletim_json["fontes_sem_resultado"]),
        "fontes_sem_publicacao_hoje": len(boletim_json["fontes_sem_publicacao_hoje"]),
        "fontes_com_erro_tecnico": len(boletim_json["fontes_com_erro_tecnico"]),
        "itens_por_boletim": stats,
        "filtro1_bloqueios": {slug: len(titulos) for slug, titulos in bloqueios_detalhe.items()},
        "auditoria": boletim_json["auditoria"],
    }
    if fontes_inativas:
        log["fontes_inativas_defeso"] = [fonte["fonte"] for fonte in fontes_inativas]
    if itens_descartados:
        log["itens_descartados"] = itens_descartados
    if bloqueios_detalhe:
        log["filtro1_bloqueios_detalhe"] = bloqueios_detalhe

    with open(OUTPUT_PATH, "w", encoding="utf-8") as arquivo:
        json.dump(boletim_json, arquivo, ensure_ascii=False, indent=2)
    with open(LOG_PATH, "w", encoding="utf-8") as arquivo:
        json.dump(log, arquivo, ensure_ascii=False, indent=2)

    print("\nRadar salvo em: " + OUTPUT_PATH)
    print("  Itens aceitos: " + str(len(itens_validados)))
    print("  Itens descartados: " + str(len(itens_descartados)))
    print("  Itens com bloqueio F1: " + str(itens_com_bloqueio))
    print("\nDistribuicao por Radar (F1 + F2):")
    for slug in BOLETINS_DISPONIVEIS:
        bloqueios = len(bloqueios_detalhe.get(slug, []))
        extra = "" if not bloqueios else " (F1 bloqueou " + str(bloqueios) + " sugestoes do F2)"
        print("  " + NOMES_RADARES[slug] + ": " + str(stats[slug]["total"]) + " itens" + extra)
    print("Concluido")


if __name__ == "__main__":
    main()
