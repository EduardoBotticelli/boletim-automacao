"""
Radares Lobo de Rizzo - geracao automatica.
Arquitetura: Firecrawl (coleta) -> Gemini (Filtro 2 tematico) -> JSON.

VERSAO 2026.08
- Mantem os 9 slugs tecnicos existentes.
- Atualiza os nomes visiveis para Radar.
- Filtro 1: fonte -> Radares permitidos pela matriz editorial.
- Filtro 2: conteudo -> Radares sugeridos pelo Gemini.
- Resultado final: intersecao entre Filtro 1 e Filtro 2.
- Registra clusters, fontes pendentes, defeso e auditoria no boletim.json.
- Fontes com "ativo": false no fontes.json sao puladas.
"""

import datetime
import json
import os
import sys
import time
from collections import Counter
from zoneinfo import ZoneInfo

from firecrawl import Firecrawl
import google.generativeai as genai


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

# Fontes aprovadas editorialmente, mas ainda sem coleta tecnica implementada.
# Elas ficam registradas no JSON, mas nao sao enviadas ao Firecrawl ate serem
# adicionadas e testadas no fontes.json ou em um coletor especifico.
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
    ],
}

# Filtro 1: matriz editorial das fontes que ja existem tecnicamente.
FONTE_PARA_BOLETINS = {
    "Planalto | Resenha Diaria": BOLETINS_DISPONIVEIS.copy(),
    "Destaques do D.O.U.": [
        "trabalhista-empresarial",
        "direito-tributario",
        "regulatorio-oleo-gas",
        "contencioso-civel",
    ],
    "Ministerio da Fazenda | Noticias": BOLETINS_DISPONIVEIS.copy(),
    "CGU | Noticias": ["trabalhista-empresarial", "regulatorio-oleo-gas"],
    "Receita Federal | Normas": ["direito-tributario"],
    "Banco Central | Normas": [
        "direito-tributario",
        "societario-ma",
        "mercado-capitais-fundos",
    ],
    "COAF | Noticias": ["direito-tributario", "mercado-capitais-fundos"],
    "CVM | Noticias": [
        "mercado-capitais-fundos",
        "regulatorio-oleo-gas",
        "imobiliario-infraestrutura",
    ],
    "B3 | Oficios e Comunicados": ["mercado-capitais-fundos"],
    "ANP | Noticias": [
        "regulatorio-oleo-gas",
        "imobiliario-infraestrutura",
        "ambiental-esg",
    ],
    "ANEEL | Ultimas Noticias": [
        "regulatorio-oleo-gas",
        "imobiliario-infraestrutura",
        "ambiental-esg",
    ],
    "ANM | Noticias": [
        "regulatorio-oleo-gas",
        "imobiliario-infraestrutura",
        "ambiental-esg",
    ],
    "ANVISA | Noticias": ["regulatorio-oleo-gas"],
    "SENACON | Noticias": [
        "regulatorio-oleo-gas",
        "propriedade-intelectual",
        "contencioso-civel",
    ],
    "Secretaria de Premios e Apostas | Noticias": [],
    "ONS | Noticias": ["imobiliario-infraestrutura", "ambiental-esg"],
    "CCEE | Noticias": ["imobiliario-infraestrutura", "ambiental-esg"],
    "EPE | Noticias": [
        "regulatorio-oleo-gas",
        "imobiliario-infraestrutura",
        "ambiental-esg",
    ],
    "MME | Noticias": [
        "regulatorio-oleo-gas",
        "imobiliario-infraestrutura",
        "ambiental-esg",
    ],
    "Ministerio do Meio Ambiente | Noticias": ["ambiental-esg"],
    "Ministerio da Agricultura | Noticias": [
        "imobiliario-infraestrutura",
        "ambiental-esg",
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
        "Agencia iNFRA",
        "iNFRA Energia",
        "IRIB",
        "Latin Lawyer",
    ],
    "ambiental-esg": ["RC Ambiental"],
    "propriedade-intelectual": [],
    "contencioso-civel": [],
}


def exigir_secrets():
    if not FIRECRAWL_API_KEY:
        print("ERRO: FIRECRAWL_API_KEY nao encontrada.")
        sys.exit(1)
    if not GEMINI_API_KEY:
        print("ERRO: GEMINI_API_KEY nao encontrada.")
        sys.exit(1)


def normalizar_nome_fonte(nome):
    """Converte apenas variantes conhecidas para as chaves historicas do Filtro 1."""
    aliases = {
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
    return aliases.get(nome, nome)


def carregar_fontes(janela_inicio_dt, agora, hoje):
    with open(FONTES_PATH, "r", encoding="utf-8") as arquivo:
        fontes = json.load(arquivo)

    data_ini_url = janela_inicio_dt.strftime("%d/%m/%Y").replace("/", "%2F")
    data_fim_url = agora.strftime("%d/%m/%Y").replace("/", "%2F")

    meses_planalto = [
        "janeiro", "fevereiro", "marco", "abril", "maio", "junho",
        "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
    ]
    mes_atual = meses_planalto[hoje.month - 1]

    url_planalto = (
        "http://www4.planalto.gov.br/legislacao/portal-legis/resenha-diaria/"
        + mes_atual
        + "-resenha-diaria"
    )
    url_bcb = (
        "https://www.bcb.gov.br/estabilidadefinanceira/buscanormas?dataInicioBusca="
        + data_ini_url
        + "&dataFimBusca="
        + data_fim_url
        + "&tipoDocumento=Todos"
    )
    url_ccee = (
        "https://www.ccee.org.br/busca-ccee?q=&dtIni="
        + data_ini_url
        + "&dtFim="
        + data_fim_url
        + "&structure=ccee-noticias&ordenacao=Mais%20recentes"
    )

    fontes.insert(0, {
        "fonte": "Planalto | Resenha Diaria",
        "categoria": "Legislacao Federal",
        "url": url_planalto,
        "ativo": True,
    })
    fontes.insert(1, {
        "fonte": "Banco Central | Normas",
        "categoria": "Financeiro e Mercado de Capitais",
        "url": url_bcb,
        "ativo": True,
    })
    fontes.insert(2, {
        "fonte": "CCEE | Noticias",
        "categoria": "Energia e Recursos",
        "url": url_ccee,
        "ativo": True,
    })

    return fontes


def ordenar_slugs(slugs):
    conjunto = set(slugs)
    return [slug for slug in BOLETINS_DISPONIVEIS if slug in conjunto]


def main():
    exigir_secrets()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    brt = ZoneInfo("America/Sao_Paulo")
    agora = datetime.datetime.now(brt)
    hoje = agora.date()
    dia_semana = hoje.weekday()

    dias_retroativos = 3 if dia_semana == 0 else 1
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
            str(len(fontes_inativas))
            + " fontes inativas: "
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
            resultado = firecrawl.scrape(
                url,
                formats=["markdown"],
                only_main_content=True,
            )
            conteudo = (resultado.markdown or "")[:MAX_CONTEUDO_CHARS]

            if len(conteudo) < MIN_CONTEUDO_CHARS:
                detalhe = (
                    "Conteudo muito curto ("
                    + str(len(conteudo))
                    + " chars) - pagina possivelmente vazia, fora do ar ou bloqueando scraping"
                )
                dossier.append({
                    "fonte": nome,
                    "categoria": categoria,
                    "url": url,
                    "conteudo": "",
                    "erro_tecnico": detalhe,
                })
                log["fontes_processadas"].append({
                    "fonte": nome,
                    "status": "erro_tecnico",
                    "tamanho_chars": len(conteudo),
                    "detalhe": "conteudo abaixo do minimo",
                })
                print("      " + detalhe)
            else:
                dossier.append({
                    "fonte": nome,
                    "categoria": categoria,
                    "url": url,
                    "conteudo": conteudo,
                })
                log["fontes_processadas"].append({
                    "fonte": nome,
                    "status": "ok",
                    "tamanho_chars": len(conteudo),
                })
                print("      OK - " + str(len(conteudo)) + " chars")
        except Exception as erro:
            mensagem = str(erro)[:200]
            dossier.append({
                "fonte": nome,
                "categoria": categoria,
                "url": url,
                "conteudo": "",
                "erro_tecnico": mensagem,
            })
            log["fontes_processadas"].append({
                "fonte": nome,
                "status": "erro",
                "erro": mensagem,
            })
            print("      Erro: " + mensagem)

    print("\nEnviando dossier para o Gemini...")
    genai.configure(api_key=GEMINI_API_KEY)
    modelo = genai.GenerativeModel(
        GEMINI_MODEL,
        generation_config={
            "temperature": 0.2,
            "response_mime_type": "application/json",
        },
    )

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
    ultimo_erro_gemini = ""
    for tentativa in range(1, 4):
        try:
            resposta = modelo.generate_content(prompt_final)
            texto = resposta.text
            break
        except Exception as erro:
            ultimo_erro_gemini = str(erro)
            print("Erro no Gemini (tentativa " + str(tentativa) + "/3): " + ultimo_erro_gemini)
            if tentativa < 3:
                time.sleep(3 * tentativa)

    if not texto:
        texto = json.dumps({
            "data_execucao": hoje.isoformat(),
            "erro": "Falha na consulta ao Gemini",
            "detalhe_erro": ultimo_erro_gemini[:500],
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

    for chave in [
        "fontes_sem_resultado",
        "fontes_sem_publicacao_hoje",
        "fontes_com_erro_tecnico",
    ]:
        if not isinstance(boletim_json.get(chave), list):
            boletim_json[chave] = []

    fontes_com_erro_no_dossier = [
        {
            "fonte": item["fonte"],
            "motivo": item.get("erro_tecnico", "erro tecnico"),
        }
        for item in dossier
        if "erro_tecnico" in item
    ]
    nomes_com_erro = {item["fonte"] for item in fontes_com_erro_no_dossier}

    boletim_json["fontes_sem_resultado"] = [
        item for item in boletim_json["fontes_sem_resultado"]
        if item.get("fonte") not in nomes_com_erro
    ]
    boletim_json["fontes_sem_publicacao_hoje"] = [
        item for item in boletim_json["fontes_sem_publicacao_hoje"]
        if item.get("fonte") not in nomes_com_erro
    ]

    nomes_ja_em_erro = {
        item.get("fonte") for item in boletim_json["fontes_com_erro_tecnico"]
    }
    for item in fontes_com_erro_no_dossier:
        if item["fonte"] not in nomes_ja_em_erro:
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
                itens_descartados.append({
                    "titulo": item.get("titulo", "")[:80],
                    "data": data_str,
                    "motivo": "fora da janela",
                })
        except (ValueError, TypeError):
            item["data_publicacao"] = ""
            itens_validados.append(item)

    filtro1_bloqueios_detalhe = {}
    itens_com_f1_bloqueio = 0
    itens_com_qualquer_rejeicao = 0
    palavras_chave_counter = Counter()
    rejeicoes_por_boletim = Counter()

    for item in itens_validados:
        fonte_original = item.get("fonte", "")
        fonte_mapeamento = normalizar_nome_fonte(fonte_original)
        permitidos = set(FONTE_PARA_BOLETINS.get(fonte_mapeamento, []))
        sugeridos = {
            slug for slug in item.get("boletins_confirmados", [])
            if slug in BOLETINS_DISPONIVEIS
        }

        finais = ordenar_slugs(permitidos & sugeridos)
        bloqueados = sugeridos - permitidos

        if bloqueados:
            itens_com_f1_bloqueio += 1
            titulo_curto = item.get("titulo", "")[:60]
            for slug in ordenar_slugs(bloqueados):
                filtro1_bloqueios_detalhe.setdefault(slug, []).append(titulo_curto)

        if not isinstance(item.get("boletins_rejeitados"), list):
            item["boletins_rejeitados"] = []
        if not isinstance(item.get("palavras_chave_detectadas"), list):
            item["palavras_chave_detectadas"] = []

        rejeicoes_existentes = {
            rejeicao.get("boletim")
            for rejeicao in item["boletins_rejeitados"]
            if isinstance(rejeicao, dict)
        }
        for slug in ordenar_slugs(bloqueados):
            if slug not in rejeicoes_existentes:
                item["boletins_rejeitados"].append({
                    "boletim": slug,
                    "motivo": (
                        "Filtro 1: fonte '"
                        + fonte_original
                        + "' nao esta mapeada para este Radar"
                    ),
                })

        if item["boletins_rejeitados"]:
            itens_com_qualquer_rejeicao += 1
        for palavra in item["palavras_chave_detectadas"]:
            if isinstance(palavra, str) and palavra.strip():
                palavras_chave_counter[palavra.lower().strip()] += 1
        for rejeicao in item["boletins_rejeitados"]:
            if isinstance(rejeicao, dict) and rejeicao.get("boletim"):
                rejeicoes_por_boletim[rejeicao["boletim"]] += 1

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

    stats_por_boletim = {}
    for slug in BOLETINS_DISPONIVEIS:
        total = sum(1 for item in itens_validados if slug in item.get("boletins", []))
        stats_por_boletim[slug] = {
            "nome": NOMES_RADARES[slug],
            "clusters": CLUSTERS_POR_BOLETIM[slug],
            "total": total,
        }
    boletim_json["estatisticas_por_boletim"] = stats_por_boletim

    top_palavras = palavras_chave_counter.most_common(20)
    boletim_json["auditoria"] = {
        "total_itens": len(itens_validados),
        "itens_com_alguma_rejeicao": itens_com_qualquer_rejeicao,
        "itens_com_bloqueio_f1": itens_com_f1_bloqueio,
        "rejeicoes_por_boletim": dict(rejeicoes_por_boletim),
        "top_palavras_chave_detectadas": [
            {"palavra": palavra, "ocorrencias": ocorrencias}
            for palavra, ocorrencias in top_palavras
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
        "itens_por_boletim": stats_por_boletim,
        "filtro1_bloqueios": {
            slug: len(titulos) for slug, titulos in filtro1_bloqueios_detalhe.items()
        },
        "auditoria": boletim_json["auditoria"],
    }
    if fontes_inativas:
        log["fontes_inativas_defeso"] = [fonte["fonte"] for fonte in fontes_inativas]
    if itens_descartados:
        log["itens_descartados"] = itens_descartados
    if filtro1_bloqueios_detalhe:
        log["filtro1_bloqueios_detalhe"] = filtro1_bloqueios_detalhe

    with open(OUTPUT_PATH, "w", encoding="utf-8") as arquivo:
        json.dump(boletim_json, arquivo, ensure_ascii=False, indent=2)
    with open(LOG_PATH, "w", encoding="utf-8") as arquivo:
        json.dump(log, arquivo, ensure_ascii=False, indent=2)

    print("\nRadar salvo em: " + OUTPUT_PATH)
    print("  Itens aceitos: " + str(len(itens_validados)))
    print("  Itens descartados: " + str(len(itens_descartados)))
    print("  Itens com bloqueio F1: " + str(itens_com_f1_bloqueio))
    print("\nDistribuicao por Radar (F1 + F2):")
    for slug in BOLETINS_DISPONIVEIS:
        total = stats_por_boletim[slug]["total"]
        bloqueios = len(filtro1_bloqueios_detalhe.get(slug, []))
        sufixo = ""
        if bloqueios:
            sufixo = " (F1 bloqueou " + str(bloqueios) + " sugestoes do F2)"
        print("  " + NOMES_RADARES[slug] + ": " + str(total) + " itens" + sufixo)

    print("Concluido")


if __name__ == "__main__":
    main()
