"""
Boletim Jurídico/Regulatório - Geração automática
Arquitetura: Firecrawl (scrape) -> Gemini (curadoria) -> JSON
"""

import os
import json
import datetime
import sys
from firecrawl import Firecrawl
import google.generativeai as genai

# ---------------------------------------------------------------------------
# 1) Configuração e validação de variáveis de ambiente
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

if not FIRECRAWL_API_KEY:
    print("❌ ERRO: FIRECRAWL_API_KEY não encontrada nos secrets.")
    sys.exit(1)

if not GEMINI_API_KEY:
    print("❌ ERRO: GEMINI_API_KEY não encontrada nos secrets.")
    sys.exit(1)

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# 2) Carregar fontes e prompt
# ---------------------------------------------------------------------------

with open(FONTES_PATH, "r", encoding="utf-8") as f:
    fontes = json.load(f)

with open(PROMPT_PATH, "r", encoding="utf-8") as f:
    prompt_base = f.read()

hoje = datetime.date.today().isoformat()
print(f"🚀 Iniciando boletim de {hoje} com {len(fontes)} fontes")

# ---------------------------------------------------------------------------
# 3) Scraping com Firecrawl
# ---------------------------------------------------------------------------

firecrawl = Firecrawl(api_key=FIRECRAWL_API_KEY)
dossier = []
log = {"data_execucao": hoje, "fontes_processadas": []}

for i, fonte in enumerate(fontes, 1):
    nome = fonte["fonte"]
    url = fonte["url"]
    categoria = fonte["categoria"]
    print(f"  [{i}/{len(fontes)}] Coletando: {nome}")

    try:
        result = firecrawl.scrape(url, formats=["markdown"])
        # Limita o tamanho para economizar tokens do Gemini
        conteudo = (result.markdown or "")[:8000]

        dossier.append({
            "fonte": nome,
            "categoria": categoria,
            "url": url,
            "conteudo": conteudo
        })
        log["fontes_processadas"].append({
            "fonte": nome,
            "status": "ok",
            "tamanho_chars": len(conteudo)
        })
        print(f"      ✅ {len(conteudo)} caracteres")

    except Exception as e:
        erro_msg = str(e)[:200]
        print(f"      ❌ Erro: {erro_msg}")
        dossier.append({
            "fonte": nome,
            "categoria": categoria,
            "url": url,
            "conteudo": "",
            "erro": erro_msg
        })
        log["fontes_processadas"].append({
            "fonte": nome,
            "status": "erro",
            "erro": erro_msg
        })

# ---------------------------------------------------------------------------
# 4) Curadoria com Gemini
# ---------------------------------------------------------------------------

print("\n🤖 Enviando dossier para o Gemini...")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(
    GEMINI_MODEL,
    generation_config={
        "temperature": 0.2,
        "response_mime_type": "application/json"
    }
)

prompt_final = f"""{prompt_base}

Data de hoje: {hoje}

Dossier das fontes:
{json.dumps(dossier, ensure_ascii=False, indent=2)}
"""

try:
    response = model.generate_content(prompt_final)
    texto = response.text
except Exception as e:
    print(f"❌ Erro no Gemini: {e}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# 5) Validação e salvamento
# ---------------------------------------------------------------------------

try:
    boletim_json = json.loads(texto)
    print("✅ Gemini retornou JSON válido")
except json.JSONDecodeError:
    print("⚠️ Gemini não retornou JSON válido — salvando como fallback")
    boletim_json = {
        "data_execucao": hoje,
        "erro": "JSON inválido retornado pelo Gemini",
        "resposta_bruta": texto,
        "itens": [],
        "fontes_sem_resultado": []
    }

# Garante data_execucao
boletim_json["data_execucao"] = hoje

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(boletim_json, f, ensure_ascii=False, indent=2)

with open(LOG_PATH, "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False, indent=2)

n_itens = len(boletim_json.get("itens", []))
n_falhas = len(boletim_json.get("fontes_sem_resultado", []))
print(f"\n📄 Boletim salvo em: {OUTPUT_PATH}")
print(f"   - {n_itens} itens relevantes")
print(f"   - {n_falhas} fontes sem resultado")
print("✅ Concluído com sucesso")
