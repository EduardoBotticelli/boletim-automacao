"""
Boletim Juridico/Regulatorio - Geracao automatica
Arquitetura: Firecrawl (scrape) -> Gemini (curadoria com Filtro 2) -> JSON

VERSAO COM 9 BOLETINS + FILTRO 2 + AUDITORIA
- Filtro 1: fonte -> boletim (matriz da Alice/Fe)
- Filtro 2: item -> boletim (Gemini decide pelo tema)
- Auditoria: cada item registra boletins_rejeitados e palavras_chave_detectadas
Item so aparece em boletim se PASSAR nos dois filtros (fonte mapeada E tema confere).
"""

import os
import json
import datetime
import sys
import time
from collections import Counter
from zoneinfo import ZoneInfo
from firecrawl import Firecrawl
import google.generativeai as genai

# Configuracao
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

# Os 9 boletins da versao revisada (Alice + Fe)
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

# FILTRO 1: matriz fonte -> boletins onde a fonte esta disponivel
FONTE_PARA_BOLETINS = {
    "Planalto | Resenha Diaria": [
        "trabalhista-empresarial", "direito-tributario", "societario-ma",
        "mercado-capitais-fundos", "regulatorio-oleo-gas", "imobiliario-infraestrutura",
        "ambiental-esg", "propriedade-intelectual", "contencioso-civel"
    ],
    "Destaques do D.O.U.": [
        "trabalhista-empresarial", "direito-tributario",
        "regulatorio-oleo-gas", "contencioso-civel"
    ],
    "Ministério da Fazenda | Notícias": [
        "trabalhista-empresarial", "direito-tributario", "societario-ma",
        "mercado-capitais-fundos", "regulatorio-oleo-gas",
        "imobiliario-infraestrutura", "ambiental-esg",
        "propriedade-intelectual", "contencioso-civel"
    ],
    "CGU | Notícias": [
        "trabalhista-empresarial", "regulatorio-oleo-gas"
    ],
    "Receita Federal | Normas": [
        "direito-tributario"
    ],
    "Banco Central | Normas": [
        "direito-tributario", "societario-ma", "mercado-capitais-fundos"
    ],
    "COAF | Notícias": [
        "direito-tributario", "mercado-capitais-fundos"
    ],
    "CVM | Notícias": [
        "mercado-capitais-fundos"
    ],
    "B3 | Ofícios e Comunicados": [
        "mercado-capitais-fundos"
    ],
    "ANP | Notícias": [
        "regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"
    ],
    "ANEEL | Últimas Notícias": [
        "regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"
    ],
    "ANM | Notícias": [
        "regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"
    ],
    "ANVISA | Notícias": [
        "regulatorio-oleo-gas"
    ],
    "SENACON | Notícias": [
        "regulatorio-oleo-gas", "propriedade-intelectual", "contencioso-civel"
    ],
    "Secretaria de Prêmios e Apostas | Notícias": [
        "regulatorio-oleo-gas"
    ],
    "ONS | Notícias": [
        "imobiliario-infraestrutura", "ambiental-esg"
    ],
    "CCEE | Noticias": [
        "imobiliario-infraestrutura", "ambiental-esg"
    ],
    "EPE | Notícias": [
        "imobiliario-infraestrutura", "ambiental-esg"
    ],
    "MME | Notícias": [
        "imobiliario-infraestrutura", "ambiental-esg"
    ],
    "Ministério do Meio Ambiente | Notícias": [
        "ambiental-esg"
    ],
    "Ministério da Agricultura | Notícias": [
        "ambiental-esg"
    ],
    "INPI | Notícias": [
        "propriedade-intelectual"
    ],
    "ANPD | Notícias": [
        "propriedade-intelectual"
    ],
}

# Fontes por e-mail pendentes por boletim (pra aviso no HTML)
FONTES_EMAIL_PENDENTES = {
    "trabalhista-empresarial": [],
    "direito-tributario": ["Tributário.com"],
    "societario-ma": ["Latin Lawyer", "Agência iNFRA"],
    "mercado-capitais-fundos": ["Latin Lawyer"],
    "regulatorio-oleo-gas": ["iNFRA Energia"],
    "imobiliario-infraestrutura": ["Agência iNFRA", "iNFRA Energia", "IRIB"],
    "ambiental-esg": ["RC Ambiental"],
    "propriedade-intelectual": [],
    "contencioso-civel": ["Tributário.com"],
}

if not FIRECRAWL_API_KEY:
    print("ERRO: FIRECRAWL_API_KEY nao encontrada.")
    sys.exit(1)
if not GEMINI_API_KEY:
    print("ERRO: GEMINI_API_KEY nao encontrada.")
    sys.exit(1)

os.makedirs(OUTPUT_DIR, exist_ok=True)

# Janela temporal BRT
BRT = ZoneInfo("America/Sao_Paulo")
agora = datetime.datetime.now(BRT)
hoje = agora.date()
dia_semana = hoje.weekday()

if dia_semana == 0:
    janela_inicio_dt = datetime.datetime.combine(hoje - datetime.timedelta(days=3), datetime.time(0, 0), tzinfo=BRT)
else:
    janela_inicio_dt = datetime.datetime.combine(hoje - datetime.timedelta(days=1), datetime.time(0, 0), tzinfo=BRT)

janela_inicio = janela_inicio_dt.strftime("%Y-%m-%dT%H:%M")
janela_fim = agora.strftime("%Y-%m-%dT%H:%M")

print("Boletim - execucao em " + agora.strftime("%Y-%m-%d %H:%M") + " BRT")
print("Janela: " + janela_inicio + " ate " + janela_fim)
print("Dia da semana: " + ["seg", "ter", "qua", "qui", "sex", "sab", "dom"][dia_semana])

# Carregar fontes + URLs dinamicas
with open(FONTES_PATH, "r", encoding="utf-8") as f:
    fontes = json.load(f)

data_ini_url = janela_inicio_dt.strftime("%d/%m/%Y").replace("/", "%2F")
data_fim_url = agora.strftime("%d/%m/%Y").replace("/", "%2F")

meses_planalto = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
mes_atual = meses_planalto[hoje.month - 1]
url_planalto = "http://www4.planalto.gov.br/legislacao/portal-legis/resenha-diaria/" + mes_atual + "-resenha-diaria"
url_bcb = "https://www.bcb.gov.br/estabilidadefinanceira/buscanormas?dataInicioBusca=" + data_ini_url + "&dataFimBusca=" + data_fim_url + "&tipoDocumento=Todos"
url_ccee = "https://www.ccee.org.br/busca-ccee?q=&dtIni=" + data_ini_url + "&dtFim=" + data_fim_url + "&structure=ccee-noticias&ordenacao=Mais%20recentes"

fontes.insert(0, {"fonte": "Planalto | Resenha Diaria", "categoria": "Legislacao Federal", "url": url_planalto})
fontes.insert(1, {"fonte": "Banco Central | Normas", "categoria": "Financeiro e Mercado de Capitais", "url": url_bcb})
fontes.insert(2, {"fonte": "CCEE | Noticias", "categoria": "Energia e Recursos", "url": url_ccee})

print(str(len(fontes)) + " fontes a processar")
print("")

with open(PROMPT_PATH, "r", encoding="utf-8") as f:
    prompt_base = f.read()

# Scraping com Firecrawl
firecrawl = Firecrawl(api_key=FIRECRAWL_API_KEY)
dossier = []
log = {"data_execucao": hoje.isoformat(), "executado_em": agora.isoformat(), "janela": {"inicio": janela_inicio, "fim": janela_fim}, "fontes_processadas": []}

for i, fonte in enumerate(fontes, 1):
    nome = fonte["fonte"]
    url = fonte["url"]
    categoria = fonte["categoria"]
    print("  [" + str(i) + "/" + str(len(fontes)) + "] " + nome)

    try:
        result = firecrawl.scrape(url, formats=["markdown"], only_main_content=True)
        conteudo = (result.markdown or "")[:10000]

        if len(conteudo) < MIN_CONTEUDO_CHARS:
            print("      Conteudo curto (" + str(len(conteudo)) + " chars) - marcando como erro tecnico")
            dossier.append({"fonte": nome, "categoria": categoria, "url": url, "conteudo": "", "erro_tecnico": "Conteudo muito curto (" + str(len(conteudo)) + " chars) - pagina possivelmente vazia, fora do ar ou bloqueando scraping"})
            log["fontes_processadas"].append({"fonte": nome, "status": "erro_tecnico", "tamanho_chars": len(conteudo), "detalhe": "conteudo abaixo do minimo"})
        else:
            dossier.append({"fonte": nome, "categoria": categoria, "url": url, "conteudo": conteudo})
            log["fontes_processadas"].append({"fonte": nome, "status": "ok", "tamanho_chars": len(conteudo)})
            print("      OK - " + str(len(conteudo)) + " chars")

    except Exception as e:
        erro_msg = str(e)[:200]
        print("      Erro: " + erro_msg)
        dossier.append({"fonte": nome, "categoria": categoria, "url": url, "conteudo": "", "erro_tecnico": erro_msg})
        log["fontes_processadas"].append({"fonte": nome, "status": "erro", "erro": erro_msg})

# Chamar Gemini
print("")
print("Enviando dossier para o Gemini...")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_MODEL, generation_config={"temperature": 0.2, "response_mime_type": "application/json"})

prompt_final = prompt_base + "\n\n## Contexto desta execucao\n\ndata_execucao: " + hoje.isoformat() + "\njanela_inicio: " + janela_inicio + "\njanela_fim: " + janela_fim + "\n\n## Dossier das fontes\n\n" + json.dumps(dossier, ensure_ascii=False, indent=2)

texto = ""
ultimo_erro_gemini = ""
for tentativa in range(1, 4):
    try:
        response = model.generate_content(prompt_final)
        texto = response.text
        break
    except Exception as e:
        ultimo_erro_gemini = str(e)
        print("Erro no Gemini (tentativa " + str(tentativa) + "/3): " + ultimo_erro_gemini)
        if tentativa < 3:
            time.sleep(3 * tentativa)

if not texto:
    print("Falha ao consultar Gemini apos 3 tentativas - gerando boletim vazio para nao interromper o workflow")
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
    print("Gemini nao retornou JSON valido - salvando como fallback")
    boletim_json = {"data_execucao": hoje.isoformat(), "erro": "JSON invalido retornado pelo Gemini", "resposta_bruta": texto, "itens": [], "fontes_sem_resultado": [], "fontes_sem_publicacao_hoje": [], "fontes_com_erro_tecnico": []}

boletim_json["data_execucao"] = hoje.isoformat()
boletim_json["janela_aplicada"] = {"inicio": janela_inicio, "fim": janela_fim}

for chave in ["fontes_sem_resultado", "fontes_sem_publicacao_hoje", "fontes_com_erro_tecnico"]:
    if chave not in boletim_json:
        boletim_json[chave] = []

# Reforco: garantir categoria correta para erros tecnicos
fontes_com_erro_no_dossier = [{"fonte": d["fonte"], "motivo": d.get("erro_tecnico", "erro tecnico")} for d in dossier if "erro_tecnico" in d]
nomes_com_erro = set(f["fonte"] for f in fontes_com_erro_no_dossier)

boletim_json["fontes_sem_resultado"] = [f for f in boletim_json["fontes_sem_resultado"] if f.get("fonte") not in nomes_com_erro]
boletim_json["fontes_sem_publicacao_hoje"] = [f for f in boletim_json["fontes_sem_publicacao_hoje"] if f.get("fonte") not in nomes_com_erro]

nomes_ja_em_erro = set(f["fonte"] for f in boletim_json["fontes_com_erro_tecnico"])
for f in fontes_com_erro_no_dossier:
    if f["fonte"] not in nomes_ja_em_erro:
        boletim_json["fontes_com_erro_tecnico"].append(f)

# Validacao temporal pos-Gemini
itens_originais = boletim_json.get("itens", [])
itens_validados = []
itens_descartados = []

for item in itens_originais:
    data_str = item.get("data_publicacao", "").strip()

    if not data_str:
        itens_validados.append(item)
        continue

    try:
        if "T" in data_str:
            dt = datetime.datetime.fromisoformat(data_str).replace(tzinfo=BRT)
        else:
            dt = datetime.datetime.combine(datetime.date.fromisoformat(data_str), datetime.time(0, 0), tzinfo=BRT)

        data_item_dia = dt.date()
        if janela_inicio_dt.date() <= data_item_dia <= agora.date():
            itens_validados.append(item)
        else:
            itens_descartados.append({"titulo": item.get("titulo", "")[:80], "data": data_str, "motivo": "fora da janela"})
    except (ValueError, TypeError):
        item["data_publicacao"] = ""
        itens_validados.append(item)

# APLICAR FILTRO 1 + FILTRO 2 combinados + AUDITORIA
# Filtro 1: fonte deve estar mapeada para o boletim
# Filtro 2: Gemini classificou item como pertencente ao boletim
# Resultado final: intersecao dos dois
# Auditoria: preservar boletins_rejeitados e palavras_chave_detectadas do Gemini,
# e adicionar rejeicoes do F1 ao mesmo campo (audit trail completo)

filtro2_removido_por_boletim = {}  # log: quando Gemini quis mas F1 barrou
itens_com_f1_bloqueio = 0
itens_com_qualquer_rejeicao = 0
palavras_chave_counter = Counter()
rejeicoes_por_boletim = Counter()

for item in itens_validados:
    fonte_item = item.get("fonte", "")
    boletins_permitidos_por_fonte = set(FONTE_PARA_BOLETINS.get(fonte_item, []))
    boletins_sugeridos_por_gemini = set(item.get("boletins_confirmados", []))

    # Intersecao: item so entra se AMBOS os filtros aprovarem
    boletins_finais = list(boletins_permitidos_por_fonte & boletins_sugeridos_por_gemini)

    # Log de bloqueios F1 (Gemini quis colocar mas Filtro 1 impediu)
    boletins_bloqueados_f1 = boletins_sugeridos_por_gemini - boletins_permitidos_por_fonte
    if boletins_bloqueados_f1:
        itens_com_f1_bloqueio += 1
        titulo_curto = item.get("titulo", "")[:60]
        for b in boletins_bloqueados_f1:
            filtro2_removido_por_boletim.setdefault(b, []).append(titulo_curto)

    # PRESERVAR / NORMALIZAR campos de auditoria vindos do Gemini
    if "boletins_rejeitados" not in item or not isinstance(item["boletins_rejeitados"], list):
        item["boletins_rejeitados"] = []
    if "palavras_chave_detectadas" not in item or not isinstance(item["palavras_chave_detectadas"], list):
        item["palavras_chave_detectadas"] = []

    # ADICIONAR rejeicoes do F1 ao audit trail
    for b in boletins_bloqueados_f1:
        item["boletins_rejeitados"].append({
            "boletim": b,
            "motivo": "Filtro 1: fonte '" + fonte_item + "' nao esta mapeada para este boletim"
        })

    # Estatisticas de auditoria
    if item["boletins_rejeitados"]:
        itens_com_qualquer_rejeicao += 1
    for pc in item["palavras_chave_detectadas"]:
        if isinstance(pc, str):
            palavras_chave_counter[pc.lower().strip()] += 1
    for rej in item["boletins_rejeitados"]:
        if isinstance(rej, dict) and "boletim" in rej:
            rejeicoes_por_boletim[rej["boletim"]] += 1

    item["boletins"] = boletins_finais  # campo final (compat com gerar_email_html.py)

boletim_json["itens"] = itens_validados

# Metadados
boletim_json["boletins_config"] = {
    "boletins_disponiveis": BOLETINS_DISPONIVEIS,
    "fontes_email_pendentes": FONTES_EMAIL_PENDENTES,
    "mapeamento_fonte_boletim": FONTE_PARA_BOLETINS,
}

# Estatisticas por boletim
stats_por_boletim = {}
for slug in BOLETINS_DISPONIVEIS:
    itens_do_boletim = [i for i in itens_validados if slug in i.get("boletins", [])]
    stats_por_boletim[slug] = {"total": len(itens_do_boletim)}
boletim_json["estatisticas_por_boletim"] = stats_por_boletim

# Auditoria consolidada (top 20 palavras-chave mais detectadas)
top_palavras = palavras_chave_counter.most_common(20)
boletim_json["auditoria"] = {
    "total_itens": len(itens_validados),
    "itens_com_alguma_rejeicao": itens_com_qualquer_rejeicao,
    "itens_com_bloqueio_f1": itens_com_f1_bloqueio,
    "rejeicoes_por_boletim": dict(rejeicoes_por_boletim),
    "top_palavras_chave_detectadas": [{"palavra": p, "ocorrencias": c} for p, c in top_palavras],
}

# Log
log["resultado"] = {
    "itens_aceitos": len(itens_validados),
    "itens_descartados_pos_validacao": len(itens_descartados),
    "fontes_sem_resultado": len(boletim_json.get("fontes_sem_resultado", [])),
    "fontes_sem_publicacao_hoje": len(boletim_json.get("fontes_sem_publicacao_hoje", [])),
    "fontes_com_erro_tecnico": len(boletim_json.get("fontes_com_erro_tecnico", [])),
    "itens_por_boletim": stats_por_boletim,
    "filtro2_bloqueios": {k: len(v) for k, v in filtro2_removido_por_boletim.items()},
    "auditoria": boletim_json["auditoria"],
}
if itens_descartados:
    log["itens_descartados"] = itens_descartados
if filtro2_removido_por_boletim:
    log["filtro2_bloqueios_detalhe"] = filtro2_removido_por_boletim

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(boletim_json, f, ensure_ascii=False, indent=2)

with open(LOG_PATH, "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False, indent=2)

print("")
print("Boletim salvo em: " + OUTPUT_PATH)
print("  Itens aceitos: " + str(len(itens_validados)))
print("  Itens descartados: " + str(len(itens_descartados)))
print("  Itens com rejeicao F1: " + str(itens_com_f1_bloqueio))
print("  Itens com alguma rejeicao (F1+F2): " + str(itens_com_qualquer_rejeicao))
print("")
print("Distribuicao por boletim (F1 + F2):")
for slug in BOLETINS_DISPONIVEIS:
    total = stats_por_boletim[slug]["total"]
    bloqueios = len(filtro2_removido_por_boletim.get(slug, []))
    extra = ""
    if bloqueios > 0:
        extra = " (F1 bloqueou " + str(bloqueios) + " sugestoes do F2)"
    print("  " + slug + ": " + str(total) + " itens" + extra)

if top_palavras:
    print("")
    print("Top 10 palavras-chave detectadas:")
    for p, c in top_palavras[:10]:
        print("  " + p + ": " + str(c))

print("Concluido")
