"""Gera os Radares Lobo de Rizzo com Firecrawl, cascata Gemini e auditoria."""
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

CASCATA_MODELOS = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
]
TENTATIVAS_POR_MODELO = 2
ESPERAS_GEMINI_SEGUNDOS = [10, 30]
MIN_CONTEUDO_CHARS = 500
MAX_CONTEUDO_CHARS = 10000
INTERVALO_ENTRE_SCRAPES_SEGUNDOS = 6.5
MAX_TENTATIVAS_SCRAPE = 3
ESPERA_RATE_LIMIT_SEGUNDOS = 65

DESCRICAO_RADARES = (
    "Informativo com atualizações legislativas, regulamentações, "
    "consultas públicas e publicações de órgãos reguladores."
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
    "direito-tributario": "Radar Tributário",
    "societario-ma": "Radar Societário, Fusões e Aquisições",
    "mercado-capitais-fundos": "Radar Mercado de Capitais e Fundos de Investimento",
    "regulatorio-oleo-gas": "Radar Regulatório e Óleo e Gás",
    "imobiliario-infraestrutura": "Radar Negócios Imobiliários e Infraestrutura",
    "ambiental-esg": "Radar Ambiental e ESG",
    "propriedade-intelectual": "Radar Propriedade Intelectual, Tecnologia e Privacidade",
    "contencioso-civel": "Radar Solução de Conflitos",
}

CLUSTERS_POR_BOLETIM = {
    "trabalhista-empresarial": ["Amber", "Pink"],
    "direito-tributario": ["Tributário Consultivo", "Tributário Contencioso"],
    "societario-ma": ["White", "Purple", "Due Diligence"],
    "mercado-capitais-fundos": ["Financeiro Green", "Fundos"],
    "regulatorio-oleo-gas": ["Regulatório", "Óleo & Gás Blue"],
    "imobiliario-infraestrutura": ["Imobiliário", "Infraestrutura"],
    "ambiental-esg": ["Ambiental"],
    "propriedade-intelectual": ["Propriedade Intelectual"],
    "contencioso-civel": ["Contencioso Carbon", "Contencioso Gold"],
}

FONTES_EM_DEFESO = [
    "CGU | Notícias",
    "Ministério do Meio Ambiente | Notícias",
    "Secretaria de Prêmios e Apostas | Notícias",
]

FONTES_PENDENTES_INTEGRACAO = {
    "regulatorio-oleo-gas": [
        "CADE - Diário Oficial da União (Seções 1 e 3)",
        "MEC - Diário Oficial da União (Seções 1 e 3)",
        "MDIC - Diário Oficial da União (Seção 1)",
        "ANATEL", "SUSEP", "ANTT", "Portal da Legislação",
        "Portal da Câmara dos Deputados", "Portal do Senado Federal",
        "Consulta Pública da ANP", "Consulta Prévia da ANP",
        "ANP - Pautas e atas de reuniões de diretoria",
        "Consulta Pública do MME", "Agência Eixos",
    ]
}

# Chaves técnicas normalizadas, sem acentos, para preservar o Filtro 1.
FONTE_PARA_BOLETINS = {
    "Planalto | Resenha Diaria": BOLETINS_DISPONIVEIS.copy(),
    "Destaques do D.O.U.": ["trabalhista-empresarial", "direito-tributario", "regulatorio-oleo-gas", "contencioso-civel"],
    "Ministerio da Fazenda | Noticias": BOLETINS_DISPONIVEIS.copy(),
    "CGU | Noticias": ["trabalhista-empresarial", "regulatorio-oleo-gas"],
    "Receita Federal | Normas": ["direito-tributario"],
    "Banco Central | Normas": ["direito-tributario", "societario-ma", "mercado-capitais-fundos"],
    "COAF | Noticias": ["direito-tributario", "mercado-capitais-fundos"],
    "CVM | Noticias": ["mercado-capitais-fundos", "regulatorio-oleo-gas", "imobiliario-infraestrutura"],
    "B3 | Oficios e Comunicados": ["mercado-capitais-fundos"],
    "ANP | Noticias": ["regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"],
    "ANEEL | Ultimas Noticias": ["regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"],
    "ANM | Noticias": ["regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"],
    "ANVISA | Noticias": ["regulatorio-oleo-gas"],
    "SENACON | Noticias": ["regulatorio-oleo-gas", "propriedade-intelectual", "contencioso-civel"],
    "Secretaria de Premios e Apostas | Noticias": [],
    "ONS | Noticias": ["imobiliario-infraestrutura", "ambiental-esg"],
    "CCEE | Noticias": ["imobiliario-infraestrutura", "ambiental-esg"],
    "EPE | Noticias": ["regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"],
    "MME | Noticias": ["regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"],
    "Ministerio do Meio Ambiente | Noticias": ["ambiental-esg"],
    "Ministerio da Agricultura | Noticias": ["imobiliario-infraestrutura", "ambiental-esg"],
    "INPI | Noticias": ["propriedade-intelectual"],
    "ANPD | Noticias": ["propriedade-intelectual"],
    "ANTAQ | Noticias": ["regulatorio-oleo-gas"],
    "CNPE | Comunicacoes": ["regulatorio-oleo-gas"],
    "Kollemata | Decretos": ["imobiliario-infraestrutura"],
}

FONTES_EMAIL_PENDENTES = {
    "trabalhista-empresarial": [],
    "direito-tributario": ["Tributário.com"],
    "societario-ma": ["Latin Lawyer"],
    "mercado-capitais-fundos": ["Latin Lawyer"],
    "regulatorio-oleo-gas": ["Agência iNFRA", "iNFRA Energia", "Agência Eixos"],
    "imobiliario-infraestrutura": ["Agência iNFRA", "iNFRA Energia", "IRIB", "Latin Lawyer"],
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
    "ONS | Notícias": "ONS | Noticias", "EPE | Notícias": "EPE | Noticias",
    "MME | Notícias": "MME | Noticias",
    "Ministério do Meio Ambiente | Notícias": "Ministerio do Meio Ambiente | Noticias",
    "Ministério da Agricultura | Notícias": "Ministerio da Agricultura | Noticias",
    "INPI | Notícias": "INPI | Noticias", "ANPD | Notícias": "ANPD | Noticias",
    "COAF | Notícias": "COAF | Noticias", "CVM | Notícias": "CVM | Noticias",
    "ANTAQ | Notícias": "ANTAQ | Noticias", "CNPE | Comunicações": "CNPE | Comunicacoes",
}


def exigir_secrets():
    if not FIRECRAWL_API_KEY:
        raise SystemExit("ERRO: FIRECRAWL_API_KEY não encontrada.")
    if not GEMINI_API_KEY:
        raise SystemExit("ERRO: GEMINI_API_KEY não encontrada.")


def normalizar_nome_fonte(nome):
    return ALIASES_FONTES.get(nome, nome)


def normalizar_lista_objetos(valor, motivo_padrao):
    if not isinstance(valor, list):
        return []
    resultado, vistos = [], set()
    for item in valor:
        if isinstance(item, dict):
            fonte = str(item.get("fonte", "")).strip()
            motivo = str(item.get("motivo", motivo_padrao)).strip() or motivo_padrao
        elif isinstance(item, str):
            fonte, motivo = item.strip(), motivo_padrao
        else:
            continue
        if fonte and fonte not in vistos:
            vistos.add(fonte)
            resultado.append({"fonte": fonte, "motivo": motivo})
    return resultado


def eh_rate_limit(erro):
    texto = str(erro).lower()
    return "rate limit" in texto or "429" in texto or "too many requests" in texto


def erro_gemini_recuperavel(erro):
    texto = str(erro).lower()
    marcadores = ["429", "500", "502", "503", "504", "unavailable", "high demand", "resource_exhausted", "deadline_exceeded", "timeout", "temporarily", "not found", "not_found", "model not found", "not supported", "permission denied for model"]
    return any(marcador in texto for marcador in marcadores)


def resumir_erro(erro, limite=500):
    return " ".join(str(erro).split())[:limite]


def scrape_com_retry(firecrawl, url):
    ultimo_erro = None
    for tentativa in range(1, MAX_TENTATIVAS_SCRAPE + 1):
        try:
            return firecrawl.scrape(url, formats=["markdown"], only_main_content=True)
        except Exception as erro:
            ultimo_erro = erro
            if not eh_rate_limit(erro) or tentativa == MAX_TENTATIVAS_SCRAPE:
                raise
            print(f"      Limite do Firecrawl atingido. Nova tentativa {tentativa + 1}/{MAX_TENTATIVAS_SCRAPE}")
            time.sleep(ESPERA_RATE_LIMIT_SEGUNDOS)
    raise ultimo_erro


def gerar_com_cascata(cliente, prompt_final):
    tentativas_log = []
    for modelo in CASCATA_MODELOS:
        for tentativa in range(1, TENTATIVAS_POR_MODELO + 1):
            print(f"Gemini: modelo {modelo} - tentativa {tentativa}/{TENTATIVAS_POR_MODELO}")
            try:
                resposta = cliente.models.generate_content(
                    model=modelo,
                    contents=prompt_final,
                    config=types.GenerateContentConfig(temperature=0.2, response_mime_type="application/json"),
                )
                texto = resposta.text or ""
                if not texto.strip():
                    raise RuntimeError("Resposta vazia do modelo")
                teste = json.loads(texto)
                if not isinstance(teste, dict) or not isinstance(teste.get("itens"), list):
                    raise ValueError("Resposta JSON sem estrutura mínima válida")
                tentativas_log.append({"modelo": modelo, "tentativa": tentativa, "status": "sucesso"})
                return texto, modelo, tentativas_log
            except json.JSONDecodeError as erro:
                mensagem = resumir_erro(erro)
                tentativas_log.append({"modelo": modelo, "tentativa": tentativa, "status": "json_invalido", "erro": mensagem})
                print("  JSON inválido: " + mensagem)
            except Exception as erro:
                mensagem = resumir_erro(erro)
                recuperavel = erro_gemini_recuperavel(erro)
                tentativas_log.append({"modelo": modelo, "tentativa": tentativa, "status": "erro", "recuperavel": recuperavel, "erro": mensagem})
                print("  Erro: " + mensagem)
                if not recuperavel:
                    return "", "", tentativas_log
            if tentativa < TENTATIVAS_POR_MODELO:
                espera = ESPERAS_GEMINI_SEGUNDOS[min(tentativa - 1, len(ESPERAS_GEMINI_SEGUNDOS) - 1)]
                print(f"  Aguardando {espera} segundos antes de repetir...")
                time.sleep(espera)
        print("  Avançando para o próximo modelo da cascata...")
    return "", "", tentativas_log


def carregar_fontes(janela_inicio_dt, agora, hoje):
    with open(FONTES_PATH, "r", encoding="utf-8") as arquivo:
        fontes = json.load(arquivo)
    data_ini_url = janela_inicio_dt.strftime("%d/%m/%Y").replace("/", "%2F")
    data_fim_url = agora.strftime("%d/%m/%Y").replace("/", "%2F")
    meses = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
    url_planalto = "http://www4.planalto.gov.br/legislacao/portal-legis/resenha-diaria/" + meses[hoje.month - 1] + "-resenha-diaria"
    url_bcb = "https://www.bcb.gov.br/estabilidadefinanceira/buscanormas?dataInicioBusca=" + data_ini_url + "&dataFimBusca=" + data_fim_url + "&tipoDocumento=Todos"
    url_ccee = "https://www.ccee.org.br/busca-ccee?q=&dtIni=" + data_ini_url + "&dtFim=" + data_fim_url + "&structure=ccee-noticias&ordenacao=Mais%20recentes"
    dinamicas = [
        {"fonte": "Planalto | Resenha Diaria", "categoria": "Legislação Federal", "url": url_planalto, "ativo": True},
        {"fonte": "Banco Central | Normas", "categoria": "Financeiro e Mercado de Capitais", "url": url_bcb, "ativo": True},
        {"fonte": "CCEE | Noticias", "categoria": "Energia e Recursos", "url": url_ccee, "ativo": True},
    ]
    return dinamicas + fontes


def ordenar_slugs(slugs):
    conjunto = set(slugs)
    return [slug for slug in BOLETINS_DISPONIVEIS if slug in conjunto]


def salvar_json_atomico(caminho, dados):
    temporario = caminho + ".tmp"
    with open(temporario, "w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, indent=2)
        arquivo.flush()
        os.fsync(arquivo.fileno())
    os.replace(temporario, caminho)


def main():
    exigir_secrets()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    brt = ZoneInfo("America/Sao_Paulo")
    agora = datetime.datetime.now(brt)
    hoje = agora.date()
    dias_retroativos = 3 if hoje.weekday() == 0 else 1
    janela_inicio_dt = datetime.datetime.combine(hoje - datetime.timedelta(days=dias_retroativos), datetime.time(0, 0), tzinfo=brt)
    janela_inicio = janela_inicio_dt.strftime("%Y-%m-%dT%H:%M")
    janela_fim = agora.strftime("%Y-%m-%dT%H:%M")
    print("Radares - execução em " + agora.strftime("%Y-%m-%d %H:%M") + " BRT")
    print("Janela: " + janela_inicio + " até " + janela_fim)

    fontes = carregar_fontes(janela_inicio_dt, agora, hoje)
    fontes_ativas = [f for f in fontes if f.get("ativo", True)]
    fontes_inativas = [f for f in fontes if not f.get("ativo", True)]
    print(f"{len(fontes_ativas)} fontes ativas a processar")
    if fontes_inativas:
        print(f"{len(fontes_inativas)} fontes inativas: " + ", ".join(f["fonte"] for f in fontes_inativas))

    with open(PROMPT_PATH, "r", encoding="utf-8") as arquivo:
        prompt_base = arquivo.read()

    firecrawl = Firecrawl(api_key=FIRECRAWL_API_KEY)
    dossier = []
    log = {"data_execucao": hoje.isoformat(), "executado_em": agora.isoformat(), "janela": {"inicio": janela_inicio, "fim": janela_fim}, "modelos_gemini_configurados": CASCATA_MODELOS, "fontes_processadas": []}

    for indice, fonte in enumerate(fontes_ativas, 1):
        nome, url, categoria = fonte["fonte"], fonte["url"], fonte["categoria"]
        print(f"  [{indice}/{len(fontes_ativas)}] {nome}")
        try:
            resultado = scrape_com_retry(firecrawl, url)
            conteudo = (resultado.markdown or "")[:MAX_CONTEUDO_CHARS]
            if len(conteudo) < MIN_CONTEUDO_CHARS:
                detalhe = f"Conteúdo muito curto ({len(conteudo)} chars)"
                dossier.append({"fonte": nome, "categoria": categoria, "url": url, "conteudo": "", "erro_tecnico": detalhe})
                log["fontes_processadas"].append({"fonte": nome, "status": "erro_tecnico", "tamanho_chars": len(conteudo), "detalhe": detalhe})
            else:
                dossier.append({"fonte": nome, "categoria": categoria, "url": url, "conteudo": conteudo})
                log["fontes_processadas"].append({"fonte": nome, "status": "ok", "tamanho_chars": len(conteudo)})
                print(f"      OK - {len(conteudo)} chars")
        except Exception as erro:
            mensagem = resumir_erro(erro, 300)
            dossier.append({"fonte": nome, "categoria": categoria, "url": url, "conteudo": "", "erro_tecnico": mensagem})
            log["fontes_processadas"].append({"fonte": nome, "status": "erro", "erro": mensagem})
            print("      Erro: " + mensagem)
        finally:
            if indice < len(fontes_ativas):
                time.sleep(INTERVALO_ENTRE_SCRAPES_SEGUNDOS)

    print("\nEnviando dossier para a cascata Gemini...")
    cliente = genai.Client(api_key=GEMINI_API_KEY)
    prompt_final = prompt_base + "\n\n## Contexto desta execução\n\n" + f"data_execucao: {hoje.isoformat()}\njanela_inicio: {janela_inicio}\njanela_fim: {janela_fim}\n\n## Dossier das fontes\n\n" + json.dumps(dossier, ensure_ascii=False, indent=2)
    try:
        texto, modelo_utilizado, tentativas_gemini = gerar_com_cascata(cliente, prompt_final)
    finally:
        cliente.close()

    log["tentativas_gemini"] = tentativas_gemini
    if not texto:
        log["resultado"] = {"status": "falha_gemini", "boletim_anterior_preservado": os.path.exists(OUTPUT_PATH)}
        salvar_json_atomico(LOG_PATH, log)
        raise SystemExit("ERRO: todos os modelos falharam. O boletim.json anterior foi preservado.")

    boletim = json.loads(texto)
    if not isinstance(boletim, dict) or not isinstance(boletim.get("itens"), list):
        log["resultado"] = {"status": "resposta_gemini_invalida", "modelo": modelo_utilizado, "boletim_anterior_preservado": os.path.exists(OUTPUT_PATH)}
        salvar_json_atomico(LOG_PATH, log)
        raise SystemExit("ERRO: resposta final do Gemini sem estrutura mínima válida.")

    boletim["data_execucao"] = hoje.isoformat()
    boletim["janela_aplicada"] = {"inicio": janela_inicio, "fim": janela_fim}
    boletim["modelo_gemini_utilizado"] = modelo_utilizado
    boletim["fontes_sem_resultado"] = normalizar_lista_objetos(boletim.get("fontes_sem_resultado", []), "A página foi acessada, mas não foi possível identificar conteúdo utilizável.")
    boletim["fontes_sem_publicacao_hoje"] = normalizar_lista_objetos(boletim.get("fontes_sem_publicacao_hoje", []), "Nenhuma publicação foi identificada dentro da janela.")
    boletim["fontes_com_erro_tecnico"] = normalizar_lista_objetos(boletim.get("fontes_com_erro_tecnico", []), "Erro técnico informado durante a coleta.")

    erros_dossier = [{"fonte": x["fonte"], "motivo": x.get("erro_tecnico", "Erro técnico") } for x in dossier if "erro_tecnico" in x]
    nomes_com_erro = {x["fonte"] for x in erros_dossier}
    boletim["fontes_sem_resultado"] = [x for x in boletim["fontes_sem_resultado"] if x["fonte"] not in nomes_com_erro]
    boletim["fontes_sem_publicacao_hoje"] = [x for x in boletim["fontes_sem_publicacao_hoje"] if x["fonte"] not in nomes_com_erro]
    erros_existentes = {x["fonte"] for x in boletim["fontes_com_erro_tecnico"]}
    boletim["fontes_com_erro_tecnico"].extend(x for x in erros_dossier if x["fonte"] not in erros_existentes)

    itens_validados, itens_descartados = [], []
    for item in boletim["itens"]:
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

    bloqueios_detalhe, itens_com_bloqueio, itens_com_rejeicao = {}, 0, 0
    palavras_counter, rejeicoes_counter = Counter(), Counter()
    for item in itens_validados:
        fonte_original = str(item.get("fonte", ""))
        permitidos = set(FONTE_PARA_BOLETINS.get(normalizar_nome_fonte(fonte_original), []))
        confirmados = item.get("boletins_confirmados", [])
        if not isinstance(confirmados, list):
            confirmados = []
        sugeridos = {s for s in confirmados if s in BOLETINS_DISPONIVEIS}
        finais, bloqueados = ordenar_slugs(permitidos & sugeridos), sugeridos - permitidos
        if bloqueados:
            itens_com_bloqueio += 1
            for slug in ordenar_slugs(bloqueados):
                bloqueios_detalhe.setdefault(slug, []).append(item.get("titulo", "")[:60])

        rejeitados = item.get("boletins_rejeitados", [])
        rejeitados = [r for r in rejeitados if isinstance(r, dict)] if isinstance(rejeitados, list) else []
        existentes = {r.get("boletim") for r in rejeitados}
        for slug in ordenar_slugs(bloqueados):
            if slug not in existentes:
                rejeitados.append({"boletim": slug, "motivo": f"Filtro 1: fonte '{fonte_original}' não está mapeada para este Radar"})
        item["boletins_rejeitados"] = rejeitados
        palavras = item.get("palavras_chave_detectadas", [])
        item["palavras_chave_detectadas"] = palavras if isinstance(palavras, list) else []
        if rejeitados:
            itens_com_rejeicao += 1
        for p in item["palavras_chave_detectadas"]:
            if isinstance(p, str) and p.strip():
                palavras_counter[p.lower().strip()] += 1
        for r in rejeitados:
            if r.get("boletim"):
                rejeicoes_counter[r["boletim"]] += 1
        item["boletins"] = finais

    boletim["itens"] = itens_validados
    boletim["boletins_config"] = {
        "descricao": DESCRICAO_RADARES,
        "boletins_disponiveis": BOLETINS_DISPONIVEIS,
        "nomes_radares": NOMES_RADARES,
        "clusters_por_boletim": CLUSTERS_POR_BOLETIM,
        "fontes_email_pendentes": FONTES_EMAIL_PENDENTES,
        "fontes_pendentes_integracao": FONTES_PENDENTES_INTEGRACAO,
        "mapeamento_fonte_boletim": FONTE_PARA_BOLETINS,
        "fontes_em_defeso": FONTES_EM_DEFESO,
    }

    stats = {slug: {"nome": NOMES_RADARES[slug], "clusters": CLUSTERS_POR_BOLETIM[slug], "total": sum(1 for item in itens_validados if slug in item.get("boletins", []))} for slug in BOLETINS_DISPONIVEIS}
    boletim["estatisticas_por_boletim"] = stats
    boletim["auditoria"] = {
        "total_itens": len(itens_validados),
        "itens_com_alguma_rejeicao": itens_com_rejeicao,
        "itens_com_bloqueio_f1": itens_com_bloqueio,
        "rejeicoes_por_boletim": dict(rejeicoes_counter),
        "top_palavras_chave_detectadas": [{"palavra": p, "ocorrencias": c} for p, c in palavras_counter.most_common(20)],
    }

    log["resultado"] = {
        "status": "sucesso", "modelo_gemini_utilizado": modelo_utilizado,
        "itens_aceitos": len(itens_validados), "itens_descartados_pos_validacao": len(itens_descartados),
        "fontes_ativas": len(fontes_ativas), "fontes_inativas": len(fontes_inativas),
        "fontes_sem_resultado": len(boletim["fontes_sem_resultado"]),
        "fontes_sem_publicacao_hoje": len(boletim["fontes_sem_publicacao_hoje"]),
        "fontes_com_erro_tecnico": len(boletim["fontes_com_erro_tecnico"]),
        "itens_por_boletim": stats,
        "filtro1_bloqueios": {slug: len(titulos) for slug, titulos in bloqueios_detalhe.items()},
        "auditoria": boletim["auditoria"],
    }
    if fontes_inativas:
        log["fontes_inativas_defeso"] = [f["fonte"] for f in fontes_inativas]
    if itens_descartados:
        log["itens_descartados"] = itens_descartados
    if bloqueios_detalhe:
        log["filtro1_bloqueios_detalhe"] = bloqueios_detalhe

    salvar_json_atomico(OUTPUT_PATH, boletim)
    salvar_json_atomico(LOG_PATH, log)
    print("\nRadar salvo em: " + OUTPUT_PATH)
    print("  Modelo Gemini utilizado: " + modelo_utilizado)
    print(f"  Itens aceitos: {len(itens_validados)}")
    print(f"  Itens descartados: {len(itens_descartados)}")
    print(f"  Itens com bloqueio F1: {itens_com_bloqueio}")
    print("\nDistribuição por Radar (F1 + F2):")
    for slug in BOLETINS_DISPONIVEIS:
        bloqueios = len(bloqueios_detalhe.get(slug, []))
        extra = "" if not bloqueios else f" (F1 bloqueou {bloqueios} sugestões do F2)"
        print(f"  {NOMES_RADARES[slug]}: {stats[slug]['total']} itens{extra}")
    print("Concluído")


if __name__ == "__main__":
    main()
