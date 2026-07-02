"""
Boletim Juridico/Regulatorio - Geracao automatica
Arquitetura: Firecrawl (scrape) -> Gemini (curadoria) -> mapeamento por area -> JSON

VERSAO COM MAPEAMENTO POR AREA (Fase 1)
Cada item recebe um campo 'boletins' com a lista de areas de destino.
"""

import os
import json
import datetime
import sys
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

# Matriz de mapeamento: nome-da-fonte-no-json -> lista de boletins destino
# Baseado no arquivo "Boletim - esqueleto 1.docx" da Alice
FONTE_PARA_BOLETINS = {
    "Planalto | Resenha Diaria": ["trabalhista", "tributario", "empresarial", "regulatorio", "imobiliario", "ambiental", "propriedade-intelectual", "contencioso"],
    "Destaques do D.O.U.": ["trabalhista", "tributario", "regulatorio", "contencioso"],
    "Ministério da Fazenda | Notícias": ["trabalhista", "tributario", "empresarial"],
    "CGU | Notícias": ["trabalhista", "regulatorio"],
    "Receita Federal | Normas": ["tributario"],
    "Banco Central | Normas": ["tributario", "empresarial", "regulatorio", "contencioso"],
    "COAF | Notícias": ["tributario", "empresarial"],
    "CVM | Notícias": ["empresarial", "propriedade-intelectual", "contencioso"],
    "B3 | Ofícios e Comunicados": ["empresarial"],
    "ANP | Notícias": ["regulatorio", "imobiliario", "ambiental"],
    "ANEEL | Últimas Notícias": ["regulatorio", "imobiliario", "ambiental"],
    "ANM | Notícias": ["regulatorio", "imobiliario", "ambiental"],
    "ANVISA | Notícias": ["regulatorio", "propriedade-intelectual"],
    "SENACON | Notícias": ["regulatorio", "propriedade-intelectual"],
    "Secretaria de Prêmios e Apostas | Notícias": ["regulatorio"],
    "ONS | Notícias": ["imobiliario", "ambiental"],
    "CCEE | Noticias": ["imobiliario", "ambiental"],
    "EPE | Notícias": ["imobiliario", "ambiental"],
    "MME | Notícias": ["imobiliario", "ambiental"],
    "Ministério do Meio Ambiente | Notícias": ["ambiental"],
    "Ministério da Agricultura | Notícias": ["ambiental"],
    "INPI | Notícias": ["propriedade-intelectual"],
    "ANPD | Notícias": ["propriedade-intelectual"],
    # Fontes por e-mail (integracao futura):
    # "Tributário.com": ["tributario", "contencioso"],
    # "Latin Lawyer": ["empresarial"],
    # "Agência iNFRA": ["empresarial", "imobiliario"],
    # "iNFRA Energia": ["imobiliario"],
    # "IRIB": ["imobiliario"],
    # "RC Ambiental": ["ambiental"],
}

# Fontes por e-mail que ainda nao coletamos (usado no aviso do boletim)
FONTES_EMAIL_PENDENTES = {
    "trabalhista": [],
    "tributario": ["Tributário.com"],
    "empresarial": ["Latin Lawyer", "Agência iNFRA"],
    "regulatorio": [],
    "imobiliario": ["Agência iNFRA", "iNFRA Energia", "IRIB"],
    "ambiental": ["RC Ambiental"],
    "propriedade-intelectual": [],
    "contencioso": ["Tributário.com"],
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

# Carregar fontes + URLs dinamicas com janela temporal
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

# Carregar prompt
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

# Configurar e chamar Gemini
print("")
print("Enviando dossier para o Gemini...")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_MODEL, generation_config={"temperature": 0.2, "response_mime_type": "application/json"})

prompt_final = prompt_base + "\n\n## Contexto desta execucao\n\ndata_execucao: " + hoje.isoformat() + "\njanela_inicio: " + janela_inicio + "\njanela_fim: " + janela_fim + "\n\n## Dossier das fontes\n\n" + json.dumps(dossier, ensure_ascii=False, indent=2)

try:
    response = model.generate_content(prompt_final)
    texto = response.text
except Exception as e:
    print("Erro no Gemini: " + str(e))
    sys.exit(1)

# Parse JSON do Gemini
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

# Reforco: garantir categoria certa para erros tecnicos
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

# NOVO: enriquecimento com mapeamento fonte -> boletins
sem_mapeamento = set()
for item in itens_validados:
    fonte_item = item.get("fonte", "")
    boletins_destino = FONTE_PARA_BOLETINS.get(fonte_item, [])
    item["boletins"] = boletins_destino
    if not boletins_destino:
        sem_mapeamento.add(fonte_item)

boletim_json["itens"] = itens_validados

# Metadados dos boletins
boletim_json["boletins_config"] = {
    "boletins_disponiveis": ["trabalhista", "tributario", "empresarial", "regulatorio", "imobiliario", "ambiental", "propriedade-intelectual", "contencioso"],
    "fontes_email_pendentes": FONTES_EMAIL_PENDENTES,
    "mapeamento_fonte_boletim": FONTE_PARA_BOLETINS
}

# Estatisticas por boletim
stats_por_boletim = {}
for slug in boletim_json["boletins_config"]["boletins_disponiveis"]:
    itens_do_boletim = [i for i in itens_validados if slug in i.get("boletins", [])]
    stats_por_boletim[slug] = {
        "total": len(itens_do_boletim),
        "alta": len([i for i in itens_do_boletim if i.get("relevancia") == "Alta"]),
        "media": len([i for i in itens_do_boletim if i.get("relevancia") in ["Media", "Média"]]),
        "baixa": len([i for i in itens_do_boletim if i.get("relevancia") == "Baixa"]),
    }
boletim_json["estatisticas_por_boletim"] = stats_por_boletim

# Salvar arquivos
log["resultado"] = {
    "itens_aceitos": len(itens_validados),
    "itens_descartados_pos_validacao": len(itens_descartados),
    "fontes_sem_resultado": len(boletim_json.get("fontes_sem_resultado", [])),
    "fontes_sem_publicacao_hoje": len(boletim_json.get("fontes_sem_publicacao_hoje", [])),
    "fontes_com_erro_tecnico": len(boletim_json.get("fontes_com_erro_tecnico", [])),
    "itens_sem_mapeamento_para_boletins": len(sem_mapeamento),
    "fontes_sem_mapeamento": sorted(list(sem_mapeamento)),
    "itens_por_boletim": stats_por_boletim
}
if itens_descartados:
    log["itens_descartados"] = itens_descartados

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(boletim_json, f, ensure_ascii=False, indent=2)

with open(LOG_PATH, "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False, indent=2)

print("")
print("Boletim salvo em: " + OUTPUT_PATH)
print("  Itens aceitos: " + str(len(itens_validados)))
print("  Itens descartados: " + str(len(itens_descartados)))
print("  Fontes sem publicacao hoje: " + str(log["resultado"]["fontes_sem_publicacao_hoje"]))
print("  Fontes sem resultado: " + str(log["resultado"]["fontes_sem_resultado"]))
print("  Fontes com erro tecnico: " + str(log["resultado"]["fontes_com_erro_tecnico"]))
print("")
print("Distribuicao por boletim:")
for slug in boletim_json["boletins_config"]["boletins_disponiveis"]:
    s = stats_por_boletim[slug]
    print("  " + slug + ": " + str(s["total"]) + " itens (Alta:" + str(s["alta"]) + " Media:" + str(s["media"]) + " Baixa:" + str(s["baixa"]) + ")")
if sem_mapeamento:
    print("")
    print("AVISO: fontes sem mapeamento para boletim:")
    for f in sorted(sem_mapeamento):
        print("  - " + f)
print("Concluido")
