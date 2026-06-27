"""
Boletim Jurídico/Regulatório - Geração automática
Arquitetura: Firecrawl (scrape) -> Gemini (curadoria) -> JSON

Mudanças nesta versão:
- onlyMainContent=True no Firecrawl (remove boilerplate)
- Janela temporal dinâmica (cobre fim de semana às segundas)
- Validação pós-Gemini contra a janela
"""

import os
import json
import datetime
import sys
from zoneinfo import ZoneInfo
from firecrawl import Firecrawl
import google.generativeai as genai

# ---------------------------------------------------------------------------
# 1) Configuração e validação
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
    print("❌ ERRO: FIRECRAWL_API_KEY não encontrada.")
    sys.exit(1)
if not GEMINI_API_KEY:
    print("❌ ERRO: GEMINI_API_KEY não encontrada.")
    sys.exit(1)

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# 2) Calcular janela temporal (fuso BRT)
# ---------------------------------------------------------------------------

BRT = ZoneInfo("America/Sao_Paulo")
agora = datetime.datetime.now(BRT)
hoje = agora.date()
dia_semana = hoje.weekday()  # 0=segunda, 6=domingo

# Lógica da janela:
# - Segunda-feira (dia_semana==0): janela = sexta 00:00 até agora (cobre fds)
# - Outros dias úteis: janela = ontem 00:00 até agora (24h+ pra cobrir publicações tardias)
if dia_semana == 0:  # segunda
    janela_inicio = (hoje - datetime.timedelta(days=3)).replace().strftime("%Y-%m-%d") + "T00:00"
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

print(f"🚀 Boletim - execução em {agora.strftime('%Y-%m-%d %H:%M')} BRT")
print(f"📅 Janela temporal: {janela_inicio} até {janela_fim}")
print(f"   (dia da semana: {['segunda','terça','quarta','quinta','sexta','sábado','domingo'][dia_semana]})")

# ---------------------------------------------------------------------------
# 3) Carregar fontes e prompt
# ---------------------------------------------------------------------------

with open(FONTES_PATH, "r", encoding="utf-8") as f:
    fontes = json.load(f)

with open(PROMPT_PATH, "r", encoding="utf-8") as f:
    prompt_base = f.read()

print(f"📚 {len(fontes)} fontes a processar\n")

# ---------------------------------------------------------------------------
# 4) Scraping com Firecrawl (otimizado)
# ---------------------------------------------------------------------------

firecrawl = Firecrawl(api_key=FIRECRAWL_API_KEY)
dossier = []
log = {
    "data_execucao": hoje.isoformat(),
    "executado_em": agora.isoformat(),
    "janela": {"inicio": janela_inicio, "fim": janela_fim},
    "fontes_processadas": []
}

for i, fonte in enumerate(fontes, 1):
    nome = fonte["fonte"]
    url = fonte["url"]
    categoria = fonte["categoria"]
    print(f"  [{i}/{len(fontes)}] {nome}")

    try:
        # onlyMainContent=True remove menu, rodapé, ads
        result = firecrawl.scrape(
            url,
            formats=["markdown"],
            only_main_content=True
        )
        conteudo = (result.markdown or "")[:10000]  # subiu para 10k já que tirou boilerplate

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
        print(f"      ✅ {len(conteudo)} caracteres (main content)")

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
# 5) Curadoria com Gemini
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

## Contexto desta execução

data_execucao: {hoje.isoformat()}
janela_inicio: {janela_inicio}
janela_fim: {janela_fim}

## Dossier das fontes

{json.dumps(dossier, ensure_ascii=False, indent=2)}
"""

try:
    response = model.generate_content(prompt_final)
    texto = response.text
except Exception as e:
    print(f"❌ Erro no Gemini: {e}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# 6) Parse e validação
# ---------------------------------------------------------------------------

try:
    boletim_json = json.loads(texto)
    print("✅ Gemini retornou JSON válido")
except json.JSONDecodeError:
    print("⚠️ Gemini não retornou JSON válido — salvando como fallback")
    boletim_json = {
        "data_execucao": hoje.isoformat(),
        "erro": "JSON inválido retornado pelo Gemini",
        "resposta_bruta": texto,
        "itens": [],
        "fontes_sem_resultado": []
    }

# Garante campos obrigatórios
boletim_json["data_execucao"] = hoje.isoformat()
boletim_json["janela_aplicada"] = {"inicio": janela_inicio, "fim": janela_fim}

# ---------------------------------------------------------------------------
# 7) Validação pós-Gemini (rede de segurança contra datas fora da janela)
# ---------------------------------------------------------------------------

itens_originais = boletim_json.get("itens", [])
itens_validados = []
itens_descartados = []

for item in itens_originais:
    data_str = item.get("data_publicacao", "").strip()

    # Item sem data: incluir (decisão do usuário)
    if not data_str:
        itens_validados.append(item)
        continue

    # Tenta parsear a data
    try:
        if "T" in data_str:
            dt = datetime.datetime.fromisoformat(data_str).replace(tzinfo=BRT)
        else:
            dt = datetime.datetime.combine(
                datetime.date.fromisoformat(data_str),
                datetime.time(0, 0),
                tzinfo=BRT
            )

        # Verifica se está na janela (com tolerância: aceita o dia todo)
        data_item_dia = dt.date()
        janela_inicio_dia = janela_inicio_dt.date()
        janela_fim_dia = agora.date()

        if janela_inicio_dia <= data_item_dia <= janela_fim_dia:
            itens_validados.append(item)
        else:
            itens_descartados.append({
                "titulo": item.get("titulo", "")[:80],
                "data": data_str,
                "motivo": f"fora da janela ({janela_inicio_dia} a {janela_fim_dia})"
            })
    except (ValueError, TypeError):
        # Data malformada: incluir mesmo assim
        item["data_publicacao"] = ""
        itens_validados.append(item)

boletim_json["itens"] = itens_validados

# ---------------------------------------------------------------------------
# 8) Salvar arquivos
# ---------------------------------------------------------------------------

log["resultado"] = {
    "itens_aceitos": len(itens_validados),
    "itens_descartados_pos_validacao": len(itens_descartados),
    "fontes_sem_resultado": len(boletim_json.get("fontes_sem_resultado", []))
}
if itens_descartados:
    log["itens_descartados"] = itens_descartados

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(boletim_json, f, ensure_ascii=False, indent=2)

with open(LOG_PATH, "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False, indent=2)

print(f"\n📄 Boletim salvo: {OUTPUT_PATH}")
print(f"   ✅ {len(itens_validados)} itens aceitos")
print(f"   🗑️  {len(itens_descartados)} itens descartados (fora da janela)")
print(f"   ⚠️  {len(boletim_json.get('fontes_sem_resultado', []))} fontes sem resultado")
print("✅ Concluído com sucesso")
