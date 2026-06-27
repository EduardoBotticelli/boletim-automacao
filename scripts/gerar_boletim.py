"""
Boletim Juridico/Regulatorio - Geracao automatica
Arquitetura: Firecrawl (scrape) -> Gemini (curadoria) -> JSON
"""

import os
import json
import datetime
import sys
from zoneinfo import ZoneInfo
from firecrawl import Firecrawl
import google.generativeai as genai

# ---------------------------------------------------------------------------
# 1) Configuracao
# ---------------------------------------------------------------------------

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

if not FIRECRAWL_API_KEY:
    print("ERRO: FIRECRAWL_API_KEY nao encontrada.")
    sys.exit(1)
if not GEMINI_API_KEY:
    print("ERRO: GEMINI_API_KEY nao encontrada.")
    sys.exit(1)

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# 2) Janela temporal (BRT)
# ---------------------------------------------------------------------------

BRT = ZoneInfo("America/Sao_Paulo")
agora = datetime.datetime.now(BRT)
hoje = agora.date()
dia_semana = hoje.weekday()

if dia_semana == 0:
    janela_inicio_dt = datetime.datetime.combine(
        hoje - datetime.timedelta(days=3),
        datetime.time(0, 0),
        tzinfo=BRT
    )
else:
    janela_inicio_dt = datetime.datetime.combine(
        hoje - datetime.timedelta(days=1),
        datetime.time(0, 0),
        tzinfo=BRT
    )

janela_inicio = janela_inicio_dt.strftime("%Y-%m-%dT%H:%M")
janela_fim = agora.strftime("%Y-%m-%dT%H:%M")

print("Boletim - execucao em " + agora.strftime("%Y-%m-%d %H:%M") + " BRT")
print("Janela: " + janela_inicio + " ate " + janela_fim)
print("Dia da semana: " + ["seg","ter","qua","qui","sex","sab","dom"][dia_semana])

# ---------------------------------------------------------------------------
# 3) Carregar fontes + adicionar Planalto dinamicamente
# ---------------------------------------------------------------------------

with open(FONTES_PATH, "r", encoding="utf-8") as f:
    fontes = json.load(f)

meses_planalto = [
    "janeiro", "fevereiro", "marco", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"
]
mes_atual = meses_planalto[hoje.month - 1]
url_planalto = "http://www4.planalto.gov.br/legislacao/portal-legis/resenha-diaria/" + mes_atual + "-resenha-diaria"

planalto_fonte = {
    "fonte": "Planalto | Resenha Diaria",
    "categoria": "Legislacao Federal",
    "url": url_planalto
}
fontes.insert(0, planalto_fonte)

print(str(len(fontes)) + " fontes a processar")
print("Planalto dinamico: " + url_planalto)
print("")

# ---------------------------------------------------------------------------
# 4) Carregar prompt
# ---------------------------------------------------------------------------

with open(PROMPT_PATH, "r", encoding="utf-8") as f:
    prompt_base = f.read()

# ---------------------------------------------------------------------------
# 5) Scraping com Firecrawl
# ---------------------------------------------------------------------------

firecrawl = Firecrawl(api_key=FIRECRAWL_API_KEY)
dossier = []
log = {
    "data_execucao": hoje.isoformat(),
    "executado_em": agora.isoformat(),
    "janela": {"inicio": janela_inicio, "fim": janela_fim},
