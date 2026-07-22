"""
Gera os 9 boletins finais (email_*.html) a partir da revisao da Alice.

VERSAO 2: HTML compativel com clientes de email (Outlook, Gmail, Apple Mail).
Usa tabelas HTML e CSS inline em vez de divs com CSS moderno.
"""
import os
import json
import datetime
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOLETIM_PATH = os.path.join(BASE_DIR, "output", "boletim.json")
DECISOES_PATH = os.path.join(BASE_DIR, "output", "decisoes_alice.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

NOMES_BOLETINS = {
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

MESES_PT = [
    "janeiro", "fevereiro", "marco", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]

COR_VERDE_ESCURO = "#0d3320"
COR_VERDE_MEDIO = "#1a4d2e"
COR_VERDE_CLARO = "#a8d8b9"
COR_TEXTO_SUAVE = "#4a5d51"
COR_LINK = "#1a4d2e"
COR_CINZA_LINHA = "#d9dee0"
COR_CINZA_FUNDO = "#f4f6f5"
COR_BRANCO = "#ffffff"
COR_TEXTO_PRETO = "#1a1a1a"


def escape_html(texto):
    if texto is None:
        return ""
    s = str(texto)
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    s = s.replace('"', "&quot;")
    return s


def formatar_data_extenso(iso):
    try:
        d = datetime.date.fromisoformat(iso[:10])
        return str(d.day) + " de " + MESES_PT[d.month - 1] + " de " + str(d.year)
    except Exception:
        return iso or ""


def formatar_data_curta(iso):
    try:
        d = datetime.date.fromisoformat(iso[:10])
        return d.strftime("%d/%m/%Y")
    except Exception:
        return iso or ""


def carregar_boletim_original():
    if not os.path.exists(BOLETIM_PATH):
        raise SystemExit("ERRO: " + BOLETIM_PATH + " nao encontrado")
    with open(BOLETIM_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def carregar_decisoes():
    if not os.path.exists(DECISOES_PATH):
        print("AVISO: " + DECISOES_PATH + " nao encontrado.")
        print("Sem decisoes da Alice - nenhum boletim final sera gerado.")
        return None
    with open(DECISOES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def aplicar_decisoes(itens_originais, decisoes):
    mapa_decisoes = {}
    itens_manuais_payload = {}

    for dec in decisoes.get("itens", []):
        id_dec = dec.get("id", "")
        mapa_decisoes[id_dec] = dec
        if "noticia" in dec:
            itens_manuais_payload[id_dec] = dec["noticia"]

    resultado = []

    for indice, item_original in enumerate(itens_originais):
        id_item = "real-" + str(indice)
        decisao = mapa_decisoes.get(id_item)

        if decisao is None:
            boletins_originais = item_original.get("boletins", [])
            if boletins_originais:
                resultado.append({
                    "noticia": item_original,
                    "boletins_finais": list(boletins_originais),
                })
            continue

        status = decisao.get("status", "")
        boletins = decisao.get("boletins", [])

        if status in ("aprovado", "ajustado") and boletins:
            resultado.append({
                "noticia": item_original,
                "boletins_finais": list(boletins),
            })

    for id_dec, decisao in mapa_decisoes.items():
        if not id_dec.startswith("manual-"):
            continue

        status = decisao.get("status", "")
        boletins = decisao.get("boletins", [])

        if status not in ("aprovado", "ajustado") or not boletins:
            continue

        noticia_manual = itens_manuais_payload.get(id_dec)
        if noticia_manual is None:
            print("AVISO: item manual " + id_dec + " sem payload - ignorado")
            continue

        resultado.append({
            "noticia": noticia_manual,
            "boletins_finais": list(boletins),
        })

    return resultado


def agrupar_por_boletim(itens):
    agrupados = {slug: [] for slug in NOMES_BOLETINS.keys()}
    for item in itens:
        for slug in item["boletins_finais"]:
            if slug in agrupados:
                agrupados[slug].append(item["noticia"])
    return agrupados


def renderizar_item(noticia, ultimo=False):
    titulo = escape_html(noticia.get("titulo", ""))
    resumo = escape_html(noticia.get("resumo", ""))
    fonte = escape_html(noticia.get("fonte", ""))
    data_pub = escape_html(formatar_data_curta(noticia.get("data_publicacao", "")))
    url = escape_html(noticia.get("url", ""))

    border_bottom = "" if ultimo else "border-bottom:1px solid " + COR_CINZA_LINHA + ";"

    html = '<tr>'
    html += '<td style="padding:24px 32px 24px 32px;' + border_bottom + '">'

    html += '<div style="margin:0 0 10px 0;font-size:16px;font-weight:600;line-height:1.4;color:' + COR_VERDE_ESCURO + ';font-family:Georgia,\'Times New Roman\',serif;">'
    html += titulo
    html += '</div>'

    html += '<div style="margin:0 0 14px 0;font-size:14px;line-height:1.6;color:' + COR_TEXTO_PRETO + ';font-family:Arial,Helvetica,sans-serif;">'
    html += resumo
    html += '</div>'

    html += '<div style="font-size:12px;color:' + COR_TEXTO_SUAVE + ';font-family:Arial,Helvetica,sans-serif;">'
    html += '<span style="font-weight:600;color:' + COR_VERDE_MEDIO + ';">' + fonte + '</span>'
    if data_pub:
        html += ' &nbsp;&middot;&nbsp; ' + data_pub

    if url:
        html += '<br style="line-height:12px;">'
        html += '' + url + ':inline-block;margin-top:8px;color:' + COR_LINK + ';text-decoration:none;font-weight:600;font-size:12px;">'
        html += 'Ler noticia completa &rarr;'
        html += '</a>'

    html += '</div>'
    html += '</td>'
    html += '</tr>'
    return html


def renderizar_boletim(slug, nome_bonito, noticias, data_extenso):
    total = len(noticias)

    if total == 0:
        corpo_linhas = '<tr>'
        corpo_linhas += '<td style="padding:60px 32px;text-align:center;font-family:Georgia,serif;font-style:italic;color:' + COR_TEXTO_SUAVE + ';font-size:14px;">'
        corpo_linhas += 'Nenhuma noticia relevante nesta edicao.'
        corpo_linhas += '</td>'
        corpo_linhas += '</tr>'
    else:
        corpo_linhas = ''
        for i, noticia in enumerate(noticias):
            ultimo = (i == total - 1)
            corpo_linhas += renderizar_item(noticia, ultimo=ultimo)

    if total == 1:
        contador = '1 destaque'
    else:
        contador = str(total) + ' destaques'

    html = '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">\n'
    html += '<html xmlns="http://www.w3.org/1999/xhtml" lang="pt-BR">\n'
    html += '<head>\n'
    html += '<meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />\n'
    html += '<meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
    html += '<title>Boletim ' + escape_html(nome_bonito) + '</title>\n'
    html += '</head>\n'
    html += '<body style="margin:0;padding:0;background-color:' + COR_CINZA_FUNDO + ';">\n'

    html += '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color:' + COR_CINZA_FUNDO + ';">\n'
    html += '<tr>\n'
    html += '<td align="center" style="padding:24px 12px;">\n'

    html += '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="680" style="max-width:680px;width:100%;background-color:' + COR_BRANCO + ';">\n'

    # HEADER
    html += '<tr>\n'
    html += '<td style="background-color:' + COR_VERDE_ESCURO + ';padding:36px 32px 32px 32px;">\n'
    html += '<div style="font-size:11px;letter-spacing:2.5px;color:' + COR_VERDE_CLARO + ';text-transform:uppercase;font-family:Arial,Helvetica,sans-serif;font-weight:600;margin-bottom:10px;">Boletim Diario</div>\n'
    html += '<h1 style="margin:0;font-size:26px;font-weight:400;color:' + COR_BRANCO + ';font-family:Georgia,\'Times New Roman\',serif;line-height:1.2;letter-spacing:-0.3px;">' + escape_html(nome_bonito) + '</h1>\n'
    html += '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-top:16px;">\n'
    html += '<tr><td style="width:36px;height:2px;background-color:' + COR_VERDE_CLARO + ';font-size:0;line-height:0;">&nbsp;</td></tr>\n'
    html += '</table>\n'
    html += '<div style="margin-top:14px;font-size:13px;color:' + COR_VERDE_CLARO + ';font-family:Arial,Helvetica,sans-serif;">'
    html += escape_html(data_extenso)
    html += ' &nbsp;&middot;&nbsp; '
    html += contador
    html += '</div>\n'
    html += '</td>\n'
    html += '</tr>\n'

    # CORPO
    html += corpo_linhas

    # FOOTER
    html += '<tr>\n'
    html += '<td style="background-color:' + COR_VERDE_ESCURO + ';padding:24px 32px;text-align:center;">\n'
    html += '<div style="font-family:Arial,Helvetica,sans-serif;font-size:11px;letter-spacing:2px;color:' + COR_VERDE_CLARO + ';font-weight:600;margin-bottom:6px;">LOBO DE RIZZO ADVOGADOS</div>\n'
    html += '<div style="font-family:Georgia,serif;font-size:12px;font-style:italic;color:' + COR_VERDE_CLARO + ';opacity:0.85;">Curadoria automatizada com revisao editorial</div>\n'
    html += '</td>\n'
    html += '</tr>\n'

    html += '</table>\n'
    html += '</td>\n'
    html += '</tr>\n'
    html += '</table>\n'
    html += '</body>\n'
    html += '</html>\n'

    return html


def salvar_boletim(slug, conteudo_html):
    path = os.path.join(OUTPUT_DIR, "email_" + slug + ".html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(conteudo_html)
    return path


def main():
    print("=" * 60)
    print("Gerador de Boletins Finais (pos-revisao Alice)")
    print("Versao 2 - HTML compativel com Outlook/Gmail")
    print("=" * 60)

    print("\nCarregando boletim original...")
    boletim = carregar_boletim_original()
    itens_originais = boletim.get("itens", [])
    print("  " + str(len(itens_originais)) + " itens no boletim original")

    print("\nCarregando decisoes da Alice...")
    decisoes = carregar_decisoes()
    if decisoes is None:
        sys.exit(0)

    total_decisoes = len(decisoes.get("itens", []))
    confirmado_em = decisoes.get("confirmadoEm", "desconhecido")
    print("  " + str(total_decisoes) + " decisoes registradas")
    print("  Revisao confirmada em: " + confirmado_em)

    print("\nAplicando decisoes...")
    itens_finais = aplicar_decisoes(itens_originais, decisoes)
    print("  " + str(len(itens_finais)) + " itens efetivos (aprovados+ajustados)")

    print("\nAgrupando por boletim...")
    agrupados = agrupar_por_boletim(itens_finais)
    for slug, noticias in agrupados.items():
        print("  " + slug + ": " + str(len(noticias)) + " noticias")

    data_execucao = boletim.get("data_execucao", "")
    if data_execucao:
        data_extenso = formatar_data_extenso(data_execucao)
    else:
        data_extenso = formatar_data_extenso(str(datetime.date.today()))

    print("\nGerando arquivos HTML...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for slug, nome_bonito in NOMES_BOLETINS.items():
        noticias = agrupados.get(slug, [])
        html = renderizar_boletim(slug, nome_bonito, noticias, data_extenso)
        path = salvar_boletim(slug, html)
        print("  " + os.path.basename(path) + " (" + str(len(noticias)) + " noticias)")

    print("\n" + "=" * 60)
    print("Concluido. 9 arquivos email_*.html sobrescritos em output/")
    print("Otimizados para renderizar em Outlook e demais clientes de email.")
    print("=" * 60)


if __name__ == "__main__":
    main()
