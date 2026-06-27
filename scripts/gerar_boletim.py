"""
Boletim Jurídico/Regulatório - Geração automática
Arquitetura: Firecrawl (scrape) -> Gemini (curadoria) -> JSON

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

MIN_CONTEUDO_CHARS = 500  # abaixo disso, considera erro técnico (página vazia/quebrada)

if not FIRECRAWL_API_KEY:
    print("❌ ERRO: FIRECRAWL_API_KEY não encontrada.")
    sys.exit(1)
if not GEMINI_API_KEY:
    print("❌ ERRO: GEMINI_API_KEY não encontrada.")
    sys.exit(1)

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# 2) Janela temporal (fuso BRT)
# ---------------------------------------------------------------------------

BRT = ZoneInfo("America/Sao_Paulo")
agora = datetime.datetime.now(BRT)
hoje = agora.date()
dia_semana = hoje.weekday()  # 0=segunda, 6=domingo

if dia_semana == 0:  # segunda: pega sex-sáb-dom-seg
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
print(f"📅 Janela: {janela_inicio} até {janela_fim}")
print(f"   (dia: {['seg','ter','qua','qui','sex','sáb','dom'][dia_semana]})")

# ---------------------------------------------------------------------------
# 3) Carregar fontes + adicionar Planalto dinamicamente
# ---------------------------------------------------------------------------

with open(FONTES_PATH, "r", encoding="utf-8") as f:
    fontes = json.load(f)

# Adiciona Planalto com URL do mês corrente (sem acento nos meses, como o Planalto usa)
meses_planalto = [
    "janeiro", "fevereiro", "marco", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"
]
mes_atual = meses_planalto[hoje.month - 1]
url_planalto = f"http://www4.planalto.gov.br/legislacao/portal-legis/resenha-diaria/{mes_atual}-resenha-diaria"

planalto_fonte = {
    "fonte": "Planalto | Resenha Diária",
    "categoria": "Legislação Federal",
    "url": url_planalto
}
fontes.insert(0, planalto_fonte)  # adiciona no início

print(f"📚 {len(fontes)} fontes a processar (Planalto dinâmico: {url_planalto})\n")

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
    "fontes_processadas": []
}

for i, fonte in enumerate(fontes, 1):
    nome = fonte["fonte"]
    url = fonte["url"]
    categoria = fonte["categoria"]
    print(f"  [{i}/{len(fontes)}] {nome}")

    try:
        result = firecrawl.scrape(
            url,
            formats=["markdown"],
            only_main_content=True
        )
        conteudo = (result.markdown or "")[:10000]

        # Verifica se o conteúdo é suficiente
        if len(conteudo) < MIN_CONTEUDO_CHARS:
            print(f"      ⚠️ Conteúdo curto ({len(conteudo)} chars) - marcando como erro técnico")
            dossier.append({
                "fonte": nome,
                "categoria": categoria,
                "url": url,
                "conteudo": "",
                "erro_tecnico": f"Conteúdo muito curto ({len(conteudo)} chars) - página possivelmente vazia, fora do ar ou bloqueando scraping"
            })
            log["fontes_processadas"].append({
                "fonte": nome,
                "status": "erro_tecnico",
                "tamanho_chars": len(conteudo),
                "detalhe": "conteúdo abaixo do mínimo"
            })
        else:
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
            print(f"      ✅ {len(conteudo)} chars")

    except Exception as e:
        erro_msg = str(e)[:200]
        print(f"      ❌ Erro: {erro_msg}")
        dossier.append({
            "fonte": nome,
            "categoria": categoria,
            "url": url,
            "conteudo": "",
            "erro_tecnico": erro_msg
        })
        log["fontes_processadas"].append({
            "fonte": nome,
            "status": "erro",
            "erro": erro_msg
        })

# ---------------------------------------------------------------------------
# 6) Curadoria com Gemini
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
# 7) Parse e validação
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
        "fontes_sem_resultado": [],
        "fontes_sem_publicacao_hoje": [],
        "fontes_com_erro_tecnico": []
    }

boletim_json["data_execucao"] = hoje.isoformat()
boletim_json["janela_aplicada"] = {"inicio": janela_inicio, "fim": janela_fim}

# Garante existência das 3 categorias de "fontes sem item"
for chave in ["fontes_sem_resultado", "fontes_sem_publicacao_hoje", "fontes_com_erro_tecnico"]:
    if chave not in boletim_json:
        boletim_json[chave] = []

# Reforço pós-Gemini: fontes com erro_tecnico no dossier vão obrigatoriamente para fontes_com_erro_tecnico
fontes_com_erro_no_dossier = [
    {"fonte": d["fonte"], "motivo": d.get("erro_tecnico", "erro técnico")}
    for d in dossier if "erro_tecnico" in d
]
# Remove dessas listas qualquer fonte que já esteja em fontes_com_erro_tecnico (evita duplicidade)
nomes_com_erro = {f["fonte"] for f in fontes_com_erro_no_dossier}
boletim_json["fontes_sem_resultado"] = [
    f for f in boletim_json["fontes_sem_resultado"] if f.get("fonte") not in nomes_com_erro
]
boletim_json["fontes_sem_publicacao_hoje"] = [
    f for f in boletim_json["fontes_sem_publicacao_hoje"] if f.get("fonte") not in nomes_com_erro
]
# Mescla erros técnicos
nomes_ja_em_erro = {f["fonte"] for f in boletim_json["fontes_com_erro_tecnico"]}
for f in fontes_com_erro_no_dossier:
    if f["fonte"] not in nomes_ja_em_erro:
        boletim_json["fontes_com_erro_tecnico"].append(f)

# ---------------------------------------------------------------------------
# 8) Validação temporal pós-Gemini
# ---------------------------------------------------------------------------

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
            dt = datetime.datetime.combine(
                datetime.date.fromisoformat(data_str),
                datetime.time(0, 0),
                tzinfo=BRT
            )

        data_item_dia = dt.date()
        if janela_inicio_dt.date() <= data_item_dia <= agora.date():
            itens_validados.append(item)
        else:
            itens_descartados.append({
                "titulo": item.get("titulo", "")[:80],
                "data": data_str,
                "motivo": f"fora da janela ({janela_inicio_dt.date()} a {agora.date()})"
            })
    except (ValueError, TypeError):
        item["data_publicacao"] = ""
        itens_validados.append(item)

boletim_json["itens"] = itens_validados

# ---------------------------------------------------------------------------
# 9) Salvar
# ---------------------------------------------------------------------------

log["resultado"] = {
    "itens_aceitos": len(itens_validados),
    "itens_descartados_pos_validacao": len(itens_descartados),
    "fontes_sem_resultado": len(boletim_json.get("fontes_sem_resultado", [])),
    "fontes_sem_publicacao_hoje": len(boletim_json.get("fontes_sem_publicacao_hoje", [])),
    "fontes_com_erro_tecnico": len(boletim_json.get("fontes_com_erro_tecnico", []))
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
print(f"   📭 {log['resultado']['fontes_sem_publicacao_hoje']} fontes sem publicação hoje")
print(f"   ⚠️  {log['resultado']['fontes_sem_resultado']} fontes sem resultado (outro motivo)")
print(f"   🔴 {log['resultado']['fontes_com_erro_tecnico']} fontes com erro técnico")
print("✅ Concluído")
