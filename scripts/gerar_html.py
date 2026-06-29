"""
Gera boletim.html a partir de boletim.json
Estilo: inspirado no boletim oficial Lobo de Rizzo (verde escuro / branding)
Uso: este script roda APOS gerar_boletim.py no mesmo workflow
"""

import os
import json
import datetime
from zoneinfo import ZoneInfo

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_PATH = os.path.join(BASE_DIR, "output", "boletim.json")
OUTPUT_HTML = os.path.join(BASE_DIR, "output", "boletim.html")

if not os.path.exists(INPUT_PATH):
    raise SystemExit("ERRO: boletim.json nao encontrado em " + INPUT_PATH)

with open(INPUT_PATH, "r", encoding="utf-8") as f:
    boletim = json.load(f)

data_exec_iso = boletim.get("data_execucao", "")
itens = boletim.get("itens", [])
sem_publicacao = boletim.get("fontes_sem_publicacao_hoje", [])
sem_resultado = boletim.get("fontes_sem_resultado", [])
com_erro = boletim.get("fontes_com_erro_tecnico", [])
janela = boletim.get("janela_aplicada", {})

# Formatar data por extenso em portugues
meses_pt = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho",
            "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
try:
    d = datetime.date.fromisoformat(data_exec_iso)
    data_extenso = str(d.day) + " de " + meses_pt[d.month - 1] + " de " + str(d.year)
    data_curta = d.strftime("%d/%m/%Y")
except Exception:
    data_extenso = data_exec_iso
    data_curta = data_exec_iso

# Agrupar itens por categoria
categorias = {}
ordem_categorias = []
for item in itens:
    cat = item.get("categoria", "Outros")
    if cat not in categorias:
        categorias[cat] = []
        ordem_categorias.append(cat)
    categorias[cat].append(item)

# Top destaques (5 itens de Alta relevancia)
destaques = [i for i in itens if i.get("relevancia") == "Alta"][:5]

# Contadores
n_total = len(itens)
n_alta = sum(1 for i in itens if i.get("relevancia") == "Alta")
n_media = sum(1 for i in itens if i.get("relevancia") == "Media" or i.get("relevancia") == "Média")
n_baixa = sum(1 for i in itens if i.get("relevancia") == "Baixa")

# Helpers HTML
def escape_html(s):
    if s is None:
        return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))

def badge_relevancia(rel):
    rel_norm = rel.replace("Média", "Media") if rel else ""
    cores = {
        "Alta": "#c0392b",
        "Media": "#d68910",
        "Baixa": "#7f8c8d"
    }
    cor = cores.get(rel_norm, "#7f8c8d")
    return '<span style="background:' + cor + ';color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">' + escape_html(rel or "") + '</span>'

def render_item(item):
    titulo = escape_html(item.get("titulo", ""))
    resumo = escape_html(item.get("resumo", ""))
    url = escape_html(item.get("url", "#"))
    data_pub = escape_html(item.get("data_publicacao", "") or "data nao identificada")
    motivo = escape_html(item.get("motivo_relevancia", ""))
    rel = item.get("relevancia", "")
    return '''
    <div style="background:#fff;border-left:4px solid #1a4d2e;padding:16px 20px;margin:12px 0;border-radius:6px;box-shadow:0 1px 3px rgba(0,0,0,0.08);">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;gap:12px;flex-wrap:wrap;">
            <h3 style="margin:0;font-size:15px;color:#1a1a1a;font-weight:600;line-height:1.4;flex:1;">''' + titulo + '''</h3>
            <div style="white-space:nowrap;">''' + badge_relevancia(rel) + '''</div>
        </div>
        <p style="margin:6px 0 10px 0;font-size:13.5px;color:#4a4a4a;line-height:1.6;">''' + resumo + '''</p>
        <div style="font-size:12px;color:#7a7a7a;border-top:1px solid #eee;padding-top:8px;">
            <span style="display:inline-block;margin-right:14px;"><strong>Publicado:</strong> ''' + data_pub + '''</span>
            <a href="''' + url + '''" style="color:#1a4d2e;text-decoration:none;font-weight:600;">Acessar materia &raquo;</a>
        </div>
        <div style="font-size:11.5px;color:#999;margin-top:6px;font-style:italic;">''' + motivo + '''</div>
    </div>
    '''

# Montar HTML
html_parts = []

html_parts.append('''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Boletim Juridico - ''' + data_curta + '''</title>
</head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;color:#2c3e50;">
<div style="max-width:780px;margin:0 auto;background:#fafafa;">

<!-- CAPA -->
<div style="background:linear-gradient(135deg,#0d3320 0%,#1a4d2e 50%,#2d8659 100%);padding:48px 36px;color:#fff;position:relative;">
    <div style="position:absolute;top:24px;right:36px;background:#2d8659;width:80px;height:80px;border-radius:50%;opacity:0.4;"></div>
    <div style="position:absolute;top:60px;right:80px;background:#5cb88a;width:40px;height:40px;border-radius:50%;opacity:0.3;"></div>
    <h1 style="margin:0;font-size:48px;font-weight:300;letter-spacing:-1px;color:#fff;">Boletim</h1>
    <div style="height:3px;width:60px;background:#5cb88a;margin:16px 0;"></div>
    <p style="margin:8px 0 0 0;font-size:13px;color:#a8d8b9;letter-spacing:1px;text-transform:uppercase;">Curadoria automatizada de fontes oficiais</p>
</div>

<!-- BARRA DA DATA -->
<div style="background:#2c2c2c;color:#fff;padding:18px 36px;text-align:right;">
    <span style="font-size:16px;font-weight:300;">''' + data_extenso + '''</span>
    <span style="color:#5cb88a;margin:0 12px;">|</span>
    <span style="font-size:13px;color:#bbb;">Rascunho automatizado</span>
</div>

<!-- ESTATISTICAS -->
<div style="background:#fff;padding:24px 36px;border-bottom:1px solid #e5e5e5;display:flex;justify-content:space-around;text-align:center;flex-wrap:wrap;gap:12px;">
    <div style="min-width:90px;">
        <div style="font-size:32px;font-weight:300;color:#1a4d2e;">''' + str(n_total) + '''</div>
        <div style="font-size:11px;text-transform:uppercase;color:#888;letter-spacing:1px;">Itens totais</div>
    </div>
    <div style="min-width:90px;">
        <div style="font-size:32px;font-weight:300;color:#c0392b;">''' + str(n_alta) + '''</div>
        <div style="font-size:11px;text-transform:uppercase;color:#888;letter-spacing:1px;">Alta relevancia</div>
    </div>
    <div style="min-width:90px;">
        <div style="font-size:32px;font-weight:300;color:#d68910;">''' + str(n_media) + '''</div>
        <div style="font-size:11px;text-transform:uppercase;color:#888;letter-spacing:1px;">Media</div>
    </div>
    <div style="min-width:90px;">
        <div style="font-size:32px;font-weight:300;color:#7f8c8d;">''' + str(n_baixa) + '''</div>
        <div style="font-size:11px;text-transform:uppercase;color:#888;letter-spacing:1px;">Baixa</div>
    </div>
</div>
''')

# SECAO DESTAQUES
if destaques:
    html_parts.append('''
<div style="background:#1a4d2e;padding:20px 36px;color:#fff;">
    <h2 style="margin:0;font-size:22px;font-weight:400;letter-spacing:-0.5px;">Destaques do dia</h2>
    <p style="margin:4px 0 0 0;font-size:13px;color:#a8d8b9;">Selecionados por alta relevancia para o escritorio</p>
</div>
<div style="padding:20px 28px 8px 28px;">
''')
    for item in destaques:
        titulo = escape_html(item.get("titulo", ""))
        resumo = escape_html(item.get("resumo", ""))
        url = escape_html(item.get("url", "#"))
        fonte = escape_html(item.get("fonte", ""))
        html_parts.append('''
    <div style="background:#fff;border:1px solid #d4e6d9;padding:14px 18px;margin:10px 0;border-radius:6px;">
        <div style="font-size:11px;color:#1a4d2e;font-weight:600;letter-spacing:1px;text-transform:uppercase;margin-bottom:4px;">''' + fonte + '''</div>
        <a href="''' + url + '''" style="color:#1a1a1a;text-decoration:none;">
            <h3 style="margin:0 0 6px 0;font-size:15px;font-weight:600;line-height:1.4;">''' + titulo + '''</h3>
        </a>
        <p style="margin:0;font-size:13px;color:#555;line-height:1.5;">''' + resumo + '''</p>
    </div>
''')
    html_parts.append('</div>')

# INDICE
html_parts.append('''
<div style="background:#1a4d2e;padding:20px 36px;color:#fff;">
    <h2 style="margin:0;font-size:22px;font-weight:400;letter-spacing:-0.5px;">Indice por categoria</h2>
</div>
<div style="padding:18px 28px;background:#fff;border-bottom:1px solid #e5e5e5;">
    <ul style="list-style:none;padding:0;margin:0;">
''')
for cat in ordem_categorias:
    cat_id = cat.lower().replace(" ", "-").replace("/", "-").replace("ç", "c").replace("ã", "a").replace("é", "e").replace("ó", "o")
    qtd = len(categorias[cat])
    html_parts.append('<li style="padding:8px 0;border-bottom:1px dotted #ddd;"><a href="#' + cat_id + '" style="color:#1a4d2e;text-decoration:none;font-weight:600;font-size:14px;">' + escape_html(cat) + '</a> <span style="color:#888;font-size:12px;float:right;">' + str(qtd) + ' itens</span></li>')
html_parts.append('</ul></div>')

# SECOES POR CATEGORIA
for cat in ordem_categorias:
    cat_id = cat.lower().replace(" ", "-").replace("/", "-").replace("ç", "c").replace("ã", "a").replace("é", "e").replace("ó", "o")
    html_parts.append('''
<div id="''' + cat_id + '''" style="background:#1a4d2e;padding:18px 36px;color:#fff;margin-top:24px;">
    <h2 style="margin:0;font-size:20px;font-weight:400;letter-spacing:-0.5px;">''' + escape_html(cat) + '''</h2>
</div>
<div style="padding:8px 28px 16px 28px;background:#f7f8fa;">
''')

    # Agrupar itens dentro da categoria por fonte
    fontes_na_cat = {}
    ordem_fontes = []
    for item in categorias[cat]:
        fonte = item.get("fonte", "Sem fonte")
        if fonte not in fontes_na_cat:
            fontes_na_cat[fonte] = []
            ordem_fontes.append(fonte)
        fontes_na_cat[fonte].append(item)

    for fonte in ordem_fontes:
        html_parts.append('<div style="margin:18px 0 8px 0;font-size:13px;font-weight:600;color:#1a4d2e;letter-spacing:0.5px;text-transform:uppercase;border-bottom:2px solid #1a4d2e;padding-bottom:6px;">' + escape_html(fonte) + '</div>')
        for item in fontes_na_cat[fonte]:
            html_parts.append(render_item(item))

    html_parts.append('</div>')

# SECAO DE TRANSPARENCIA
html_parts.append('''
<div style="background:#2c2c2c;padding:20px 36px;color:#fff;margin-top:24px;">
    <h2 style="margin:0;font-size:18px;font-weight:400;">Transparencia da coleta</h2>
</div>
<div style="padding:18px 28px;background:#fff;font-size:13px;color:#555;">
''')

if sem_publicacao:
    html_parts.append('<p style="margin:8px 0 4px 0;color:#1a4d2e;font-weight:600;">Fontes sem publicacao na janela:</p><ul style="margin:4px 0 12px 20px;color:#666;font-size:12.5px;">')
    for f in sem_publicacao:
        html_parts.append('<li>' + escape_html(f.get("fonte", "")) + ' - ' + escape_html(f.get("motivo", "")) + '</li>')
    html_parts.append('</ul>')

if sem_resultado:
    html_parts.append('<p style="margin:8px 0 4px 0;color:#d68910;font-weight:600;">Fontes sem resultado relevante:</p><ul style="margin:4px 0 12px 20px;color:#666;font-size:12.5px;">')
    for f in sem_resultado:
        html_parts.append('<li>' + escape_html(f.get("fonte", "")) + ' - ' + escape_html(f.get("motivo", "")) + '</li>')
    html_parts.append('</ul>')

if com_erro:
    html_parts.append('<p style="margin:8px 0 4px 0;color:#c0392b;font-weight:600;">Fontes com erro tecnico:</p><ul style="margin:4px 0 12px 20px;color:#666;font-size:12.5px;">')
    for f in com_erro:
        html_parts.append('<li>' + escape_html(f.get("fonte", "")) + ' - ' + escape_html(f.get("motivo", "")) + '</li>')
    html_parts.append('</ul>')

janela_ini = escape_html(janela.get("inicio", ""))
janela_fim = escape_html(janela.get("fim", ""))
html_parts.append('<p style="margin:14px 0 4px 0;font-size:12px;color:#888;border-top:1px solid #eee;padding-top:10px;"><strong>Janela analisada:</strong> ' + janela_ini + ' ate ' + janela_fim + '</p>')
html_parts.append('</div>')

# RODAPE
html_parts.append('''
<div style="background:#0d3320;padding:24px 36px;color:#a8d8b9;text-align:center;font-size:12px;">
    <p style="margin:4px 0;">Rascunho gerado automaticamente para validacao interna.</p>
    <p style="margin:4px 0;">Curadoria por IA + revisao humana recomendada antes da distribuicao.</p>
    <p style="margin:12px 0 4px 0;color:#5cb88a;font-size:11px;letter-spacing:1px;text-transform:uppercase;">Boletim Juridico - Pipeline automatizado</p>
</div>

</div>
</body>
</html>''')

# Salvar
os.makedirs(os.path.dirname(OUTPUT_HTML), exist_ok=True)
with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
    f.write("".join(html_parts))

print("HTML gerado: " + OUTPUT_HTML)
print("  " + str(n_total) + " itens em " + str(len(ordem_categorias)) + " categorias")
print("  " + str(len(destaques)) + " destaques de alta relevancia")
