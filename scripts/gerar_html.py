"""
Gera 9 e-mails HTML de validacao a partir de boletim.json (um por boletim).
Uso: roda APOS gerar_boletim.py no mesmo workflow.
Saida: output/email_<slug>.html
"""

import os
import json
import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_PATH = os.path.join(BASE_DIR, "output", "boletim.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

if not os.path.exists(INPUT_PATH):
    raise SystemExit("ERRO: boletim.json nao encontrado em " + INPUT_PATH)

with open(INPUT_PATH, "r", encoding="utf-8") as f:
    boletim = json.load(f)

data_exec_iso = boletim.get("data_execucao", "")
todos_itens = boletim.get("itens", [])
janela = boletim.get("janela_aplicada", {})
config = boletim.get("boletins_config", {})
fontes_email_pendentes = config.get("fontes_email_pendentes", {})
mapeamento_fonte = config.get("mapeamento_fonte_boletim", {})

NOMES_BONITOS = {
    "trabalhista-empresarial": "Trabalhista Empresarial",
    "direito-tributario": "Direito Tributario",
    "societario-ma": "Societario, Fusoes e Aquisicoes",
    "mercado-capitais-fundos": "Mercado de Capitais e Fundos de Investimento",
    "regulatorio-oleo-gas": "Regulatorio e Oleo e Gas",
    "imobiliario-infraestrutura": "Negocios Imobiliarios e Infraestrutura",
    "ambiental-esg": "Ambiental e ESG",
    "propriedade-intelectual": "Propriedade Intelectual, Tecnologia e Privacidade",
    "contencioso-civel": "Contencioso Civel",
}

meses_pt = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho",
            "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]

try:
    d = datetime.date.fromisoformat(data_exec_iso)
    data_extenso = str(d.day) + " de " + meses_pt[d.month - 1] + " de " + str(d.year)
except Exception:
    data_extenso = data_exec_iso


def escape_html(s):
    if s is None:
        return ""
    s = str(s)
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    s = s.replace('"', "&quot;")
    return s


def render_item(item):
    titulo = escape_html(item.get("titulo", ""))
    resumo = escape_html(item.get("resumo", ""))
    url = escape_html(item.get("url", "#"))
    data_pub = escape_html(item.get("data_publicacao", "") or "data nao identificada")
    motivo = escape_html(item.get("motivo_filtragem", ""))

    template = (
        '<div style="background:#fff;border-left:4px solid #1a4d2e;padding:14px 18px;margin:10px 0;border-radius:4px;box-shadow:0 1px 2px rgba(0,0,0,0.06);">'
        '<h3 style="margin:0 0 6px 0;font-size:14.5px;color:#1a1a1a;font-weight:600;line-height:1.4;">{titulo}</h3>'
        '<p style="margin:4px 0 8px 0;font-size:13px;color:#4a4a4a;line-height:1.5;">{resumo}</p>'
        '<div style="font-size:12px;color:#7a7a7a;border-top:1px solid #eee;padding-top:6px;">'
        '<span style="margin-right:14px;"><strong>Publicado:</strong> {data_pub}</span>'
        '{url}text-decoration:none;font-weight:600;">Acessar materia &raquo;</a>'
        '</div>'
        '<div style="font-size:11px;color:#999;margin-top:4px;font-style:italic;">Motivo da filtragem: {motivo}</div>'
        '</div>'
    )
    return template.format(titulo=titulo, resumo=resumo, url=url, data_pub=data_pub, motivo=motivo)


def gerar_email_html(nome_boletim, itens, fontes_desta_area, aviso_email_pendente):
    parts = []

    parts.append('<!DOCTYPE html>')
    parts.append('<html lang="pt-BR">')
    parts.append('<head><meta charset="UTF-8"><title>Boletim ' + escape_html(nome_boletim) + ' - Validacao</title></head>')
    parts.append('<body style="margin:0;padding:0;background:#f0f2f5;font-family:Segoe UI,Tahoma,Geneva,Verdana,sans-serif;color:#2c3e50;">')
    parts.append('<div style="max-width:780px;margin:0 auto;background:#fafafa;">')

    parts.append('<div style="background:linear-gradient(135deg,#0d3320 0%,#1a4d2e 50%,#2d8659 100%);padding:32px 32px 24px 32px;color:#fff;">')
    parts.append('<div style="font-size:11px;color:#a8d8b9;letter-spacing:2px;text-transform:uppercase;margin-bottom:6px;">Versao de validacao</div>')
    parts.append('<h1 style="margin:0;font-size:32px;font-weight:300;letter-spacing:-0.5px;color:#fff;">Boletim</h1>')
    parts.append('<div style="height:2px;width:40px;background:#5cb88a;margin:10px 0;"></div>')
    parts.append('<p style="margin:6px 0 0 0;font-size:16px;color:#fff;font-weight:500;">' + escape_html(nome_boletim) + '</p>')
    parts.append('<p style="margin:4px 0 0 0;font-size:13px;color:#a8d8b9;">' + data_extenso + '</p>')
    parts.append('</div>')

    parts.append('<div style="background:#fef5e7;border-left:4px solid #d68910;padding:18px 24px;color:#5d4400;font-size:13.5px;line-height:1.6;">')
    parts.append('<p style="margin:0 0 10px 0;"><strong>Boa noite!.</strong></p>')
    parts.append('<p style="margin:0 0 10px 0;">Este e um <strong>teste de validacao</strong> do sistema automatizado de curadoria de boletins juridicos. Envio para voce ver como o boletim de <strong>' + escape_html(nome_boletim) + '</strong> ficaria com a nova estrutura e o novo criterio de filtragem por tema.</p>')
    parts.append('<p style="margin:0 0 6px 0;"><strong>Gostaria da sua avaliacao sobre:</strong></p>')
    parts.append('<ul style="margin:6px 0 12px 20px;padding:0;">')
    parts.append('<li style="margin-bottom:4px;">Os itens que apareceram fazem sentido para essa area?</li>')
    parts.append('<li style="margin-bottom:4px;">Algum item importante ficou de fora?</li>')
    parts.append('<li style="margin-bottom:4px;">Ha vocabulario tipico da area que o sistema poderia reconhecer melhor?</li>')
    parts.append('</ul>')
    parts.append('</div>')

    parts.append('<div style="background:#fff;padding:18px 24px;border-bottom:1px solid #e5e5e5;font-size:12.5px;color:#555;line-height:1.6;">')
    parts.append('<p style="margin:0 0 8px 0;color:#1a4d2e;"><strong>Como funciona o criterio de filtragem</strong></p>')
    parts.append('<p style="margin:0 0 6px 0;">O sistema aplica <strong>2 filtros combinados</strong> para decidir se um item entra neste boletim:</p>')
    parts.append('<p style="margin:0 0 4px 0;"><strong>1. Filtro por fonte:</strong> apenas fontes mapeadas para esta area (definidas por Alice/Fe na revisao) podem contribuir com itens.</p>')
    parts.append('<p style="margin:0 0 4px 0;"><strong>2. Filtro por tema:</strong> dentro dessas fontes, a IA classifica cada item usando as <strong>descricoes oficiais das areas de atuacao do LDR</strong> (site institucional) combinadas com palavras-chave especificas.</p>')
    parts.append('<p style="margin:8px 0 0 0;font-style:italic;color:#888;">Assim, um item so aparece aqui se a fonte estiver mapeada para esta area <strong>e</strong> o conteudo realmente tratar de tema pertinente.</p>')
    parts.append('</div>')

    fontes_str = ", ".join(fontes_desta_area) if fontes_desta_area else "Nenhuma"
    parts.append('<div style="background:#f4f7f5;padding:14px 24px;border-bottom:1px solid #e5e5e5;font-size:12px;color:#666;">')
    parts.append('<strong style="color:#1a4d2e;">Fontes disponibilizadas para este boletim (' + str(len(fontes_desta_area)) + '):</strong><br>')
    parts.append(escape_html(fontes_str))
    parts.append('</div>')

    if aviso_email_pendente:
        aviso_str = ", ".join(aviso_email_pendente)
        parts.append('<div style="background:#fff3cd;border-left:4px solid #d68910;padding:12px 20px;color:#7d5a10;font-size:12.5px;">')
        parts.append('<strong>Aviso:</strong> As seguintes fontes desta area chegam por e-mail e ainda nao estao integradas ao sistema (integracao futura): ' + escape_html(aviso_str) + '.')
        parts.append('</div>')

    if not itens:
        parts.append('<div style="padding:40px 28px;text-align:center;color:#888;background:#fff;">')
        parts.append('<p style="font-size:15px;margin:0 0 6px 0;">Nenhum item classificado para este boletim na janela temporal atual.</p>')
        parts.append('<p style="font-size:12.5px;margin:0;font-style:italic;">Isso pode ocorrer em dias sem publicacoes tematicas ou por o filtro ter sido restritivo demais (justamente o que queremos validar com voce).</p>')
        parts.append('</div>')
    else:
        parts.append('<div style="background:#fff;padding:0 24px 20px 24px;">')

        fontes_com_itens = {}
        ordem_fontes = []
        for item in itens:
            fonte = item.get("fonte", "Sem fonte")
            if fonte not in fontes_com_itens:
                fontes_com_itens[fonte] = []
                ordem_fontes.append(fonte)
            fontes_com_itens[fonte].append(item)

        for fonte in ordem_fontes:
            qtd = len(fontes_com_itens[fonte])
            parts.append('<div style="margin:20px 0 6px 0;font-size:12.5px;font-weight:700;color:#1a4d2e;letter-spacing:0.5px;text-transform:uppercase;border-bottom:2px solid #1a4d2e;padding-bottom:4px;">' + escape_html(fonte) + ' (' + str(qtd) + ')</div>')
            for item in fontes_com_itens[frts.append(render_item(item))

        parts.append('</div>')

    janela_ini = escape_html(janela.get("inicio", ""))
    janela_fim_str = escape_html(janela.get("fim", ""))
    parts.append('<div style="background:#f4f7f5;padding:16px 24px;border-top:1px solid #e5e5e5;font-size:11.5px;color:#888;line-height:1.6;">')
    parts.append('<p style="margin:0 0 4px 0;"><strong>Janela analisada:</strong> ' + janela_ini + ' ate ' + janela_fim_str + '</p>')
    parts.append('<p style="margin:0;">Sistema em fase de validacao.</p>')
    parts.append('</div>')

    parts.append('<div style="background:#0d3320;padding:18px 24px;color:#a8d8b9;text-align:center;font-size:11px;letter-spacing:1px;">')
    parts.append('<p style="margin:0;">Boletim juridico automatizado &middot; Lobo de Rizzo Advogados</p>')
    parts.append('<p style="margin:6px 0 0 0;font-style:italic;">Duvidas ou sugestoes: responder este e-mail</p>')
    parts.append('</div>')

    parts.append('</div>')
    parts.append('</body>')
    parts.append('</html>')

    return "".join(parts)


os.makedirs(OUTPUT_DIR, exist_ok=True)

slugs = config.get("boletins_disponiveis", [])
resumo_geracao = {}

for slug in slugs:
    itens_do_boletim = [i for i in todos_itens if slug in i.get("boletins", [])]
    aviso = fontes_email_pendentes.get(slug, [])
    nome_bonito = NOMES_BONITOS.get(slug, slug.title())
    fontes_desta_area = [fonte for fonte, boletins in mapeamento_fonte.items() if slug in boletins]

    html = gerar_email_html(
        nome_boletim=nome_bonito,
        itens=itens_do_boletim,
        fontes_desta_area=fontes_desta_area,
        aviso_email_pendente=aviso,
    )

    path = os.path.join(OUTPUT_DIR, "email_" + slug + ".html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    resumo_geracao[slug] = len(itens_do_boletim)
    print("Email " + slug + ": " + str(len(itens_do_boletim)) + " itens")

print("")
print("Concluido - " + str(len(slugs)) + " e-mails HTML gerados")
