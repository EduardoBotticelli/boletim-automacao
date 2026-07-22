"""
Gera os 9 boletins finais (email_*.html) a partir da revisao.

VERSAO 4: Identidade visual baseada nos banners oficiais do LDR.
- Verde escuro (#0d3320) + verde vibrante (#22c55e) da identidade
- Layout inspirado nos boletins do Marketing
- Compatibilidade Outlook via bgcolor + VML
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

# Paleta LDR (baseada nos banners oficiais)
COR_VERDE_ESCURO = "#0d3320"         # Fundo principal (banner header)
COR_VERDE_VIBRANTE = "#22c55e"       # Verde vibrante da logo/detalhes
COR_VERDE_MEDIO = "#1a4d2e"          # Verde escuro medio
COR_VERDE_CLARO = "#a8d8b9"          # Texto sobre verde escuro
COR_VERDE_OLIVA = "#6b7c6e"          # Rodape (banner 3)
COR_TEXTO_SUAVE = "#4a5d51"
COR_LINK = "#0d3320"
COR_CINZA_LINHA = "#e5e7eb"
COR_CINZA_FUNDO = "#f4f6f5"
COR_BRANCO = "#ffffff"
COR_TEXTO_PRETO = "#1a1a1a"
COR_METADADO = "#6b7280"

NUMERO_EDICAO = "1"


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


def renderizar_item(noticia, primeiro=False):
    titulo = escape_html(noticia.get("titulo", ""))
    resumo = escape_html(noticia.get("resumo", ""))
    fonte = escape_html(noticia.get("fonte", ""))
    data_pub = escape_html(formatar_data_curta(noticia.get("data_publicacao", "")))
    url = escape_html(noticia.get("url", ""))

    padding_top = "0" if primeiro else "24"

    html = '<tr>'
    html += '<td bgcolor="' + COR_BRANCO + '" style="background-color:' + COR_BRANCO + ';padding:' + padding_top + 'px 40px 24px 40px;">'

    # Linha verde vibrante decorativa em cima do item (elemento de marca)
    if not primeiro:
        html += '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 20px 0;">\n'
        html += '<tr><td bgcolor="' + COR_VERDE_VIBRANTE + '" style="background-color:' + COR_VERDE_VIBRANTE + ';width:32px;height:3px;font-size:0;line-height:0;">&nbsp;</td></tr>\n'
        html += '</table>\n'

    # Metadado superior: fonte + data (estilo do template Marketing)
    html += '<div style="font-family:Arial,Helvetica,sans-serif;font-size:11px;color:' + COR_METADADO + ';margin-bottom:10px;letter-spacing:0.3px;">'
    html += '<span style="font-weight:600;color:' + COR_VERDE_MEDIO + ';text-transform:uppercase;">' + fonte + '</span>'
    if data_pub:
        html += ' &nbsp;&middot;&nbsp; ' + data_pub
    html += '</div>'

    # Titulo (destaque)
    html += '<div style="margin:0 0 12px 0;font-family:Arial,Helvetica,sans-serif;font-size:18px;font-weight:700;line-height:1.35;color:' + COR_VERDE_ESCURO + ';">'
    html += titulo
    html += '</div>'

    # Resumo
    html += '<div style="margin:0 0 16px 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.65;color:' + COR_TEXTO_PRETO + ';">'
    html += resumo
    html += '</div>'

    # Botao "Ler noticia completa" com estilo LDR
    if url:
        html += '<table role="presentation" cellpadding="0" cellspacing="0" border="0">\n'
        html += '<tr><td>'
        html += '' + url + ':inline-block;font-family:Arial,Helvetica,sans-serif;font-size:12px;font-weight:600;color:' + COR_VERDE_ESCURO + ';text-decoration:none;padding:8px 0 0 0;border-bottom:2px solid ' + COR_VERDE_VIBRANTE + ';">'
        html += 'Ler noticia completa &rarr;'
        html += '</a>'
        html += '</td></tr>\n'
        html += '</table>\n'

    html += '</td>'
    html += '</tr>'
    return html


def renderizar_header(nome_bonito, data_extenso, contador):
    """
    Header inspirado no banner oficial do LDR.
    Verde escuro solido + detalhe verde vibrante (linha divisora).
    """
    html = '<tr>\n'
    html += '<td bgcolor="' + COR_VERDE_ESCURO + '" style="background-color:' + COR_VERDE_ESCURO + ';padding:0;">\n'

    # VML fallback pro Outlook desktop
    html += '<!--[if mso]>\n'
    html += '<v:rect xmlns:v="urn:schemas-microsoft-com:vml" fill="true" stroke="false" style="width:680px;">\n'
    html += '<v:fill type="tile" color="' + COR_VERDE_ESCURO + '" />\n'
    html += '<v:textbox inset="0,0,0,0">\n'
    html += '<![endif]-->\n'

    html += '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="' + COR_VERDE_ESCURO + '" style="background-color:' + COR_VERDE_ESCURO + ';">\n'
    html += '<tr>\n'
    html += '<td bgcolor="' + COR_VERDE_ESCURO + '" style="background-color:' + COR_VERDE_ESCURO + ';padding:40px 40px 36px 40px;">\n'

    # Numero de edicao (topo)
    html += '<div style="font-family:Arial,Helvetica,sans-serif;font-size:11px;letter-spacing:2px;color:' + COR_VERDE_CLARO + ';text-transform:uppercase;font-weight:600;margin-bottom:24px;mso-line-height-rule:exactly;">'
    html += 'Boletim Lobo de Rizzo &nbsp;&middot;&nbsp; Edicao ' + NUMERO_EDICAO
    html += '</div>\n'

    # Nome do boletim (destaque - Arial grande sem serifa como no banner)
    html += '<div style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:32px;font-weight:700;color:' + COR_BRANCO + ';line-height:1.15;letter-spacing:-0.5px;mso-line-height-rule:exactly;">'
    html += escape_html(nome_bonito)
    html += '</div>\n'

    # Linha verde vibrante decorativa (assinatura visual LDR)
    html += '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-top:24px;">\n'
    html += '<tr><td bgcolor="' + COR_VERDE_VIBRANTE + '" style="background-color:' + COR_VERDE_VIBRANTE + ';width:64px;height:4px;font-size:0;line-height:0;">&nbsp;</td></tr>\n'
    html += '</table>\n'

    # Data + contador
    html += '<div style="margin-top:20px;font-family:Arial,Helvetica,sans-serif;font-size:13px;color:' + COR_VERDE_CLARO + ';mso-line-height-rule:exactly;">'
    html += escape_html(data_extenso)
    html += ' &nbsp;&middot;&nbsp; '
    html += contador
    html += '</div>\n'

    html += '</td>\n'
    html += '</tr>\n'
    html += '</table>\n'

    html += '<!--[if mso]>\n'
    html += '</v:textbox>\n'
    html += '</v:rect>\n'
    html += '<![endif]-->\n'

    html += '</td>\n'
    html += '</tr>\n'
    return html


def renderizar_footer():
    """
    Footer inspirado no banner 3 (verde oliva/acinzentado).
    Simples, com aviso de circulacao interna e endereco.
    """
    html = ''

    # Aviso de circulacao interna (bloco branco antes do rodape)
    html += '<tr>\n'
    html += '<td bgcolor="' + COR_BRANCO + '" style="background-color:' + COR_BRANCO + ';padding:32px 40px;border-top:1px solid ' + COR_CINZA_LINHA + ';">\n'
    html += '<div style="font-family:Arial,Helvetica,sans-serif;font-size:11px;color:' + COR_METADADO + ';font-style:italic;text-align:center;line-height:1.5;">'
    html += 'Este boletim eh somente para circulacao interna.<br />'
    html += 'A distribuicao das informacoes aqui contidas eh proibida.'
    html += '</div>\n'
    html += '</td>\n'
    html += '</tr>\n'

    # Rodape verde oliva (banner 3)
    html += '<tr>\n'
    html += '<td bgcolor="' + COR_VERDE_OLIVA + '" style="background-color:' + COR_VERDE_OLIVA + ';padding:0;">\n'

    html += '<!--[if mso]>\n'
    html += '<v:rect xmlns:v="urn:schemas-microsoft-com:vml" fill="true" stroke="false" style="width:680px;">\n'
    html += '<v:fill type="tile" color="' + COR_VERDE_OLIVA + '" />\n'
    html += '<v:textbox inset="0,0,0,0">\n'
    html += '<![endif]-->\n'

    html += '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="' + COR_VERDE_OLIVA + '" style="background-color:' + COR_VERDE_OLIVA + ';">\n'
    html += '<tr>\n'
    html += '<td bgcolor="' + COR_VERDE_OLIVA + '" style="background-color:' + COR_VERDE_OLIVA + ';padding:24px 40px;">\n'

    # Layout: nome do escritorio esquerda, ldr.com.br direita (imitando banner 3)
    html += '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">\n'
    html += '<tr>\n'

    # Coluna esquerda: nome
    html += '<td align="left" style="font-family:Arial,Helvetica,sans-serif;font-size:12px;color:' + COR_BRANCO + ';font-weight:600;letter-spacing:1.5px;">'
    html += 'LOBO DE RIZZO ADVOGADOS'
    html += '</td>\n'

    # Coluna direita: url
    html += '<td align="right" style="font-family:Arial,Helvetica,sans-serif;font-size:12px;color:' + COR_BRANCO + ';">'
    html += 'ldr.com.br'
    html += '</td>\n'

    html += '</tr>\n'
    html += '</table>\n'

    # Endereco (linha inferior)
    html += '<div style="margin-top:12px;font-family:Arial,Helvetica,sans-serif;font-size:11px;color:' + COR_BRANCO + ';opacity:0.85;">'
    html += 'Av. Brig. Faria Lima, 3900 - Itaim Bibi, Sao Paulo - SP, 04538-132'
    html += '</div>\n'

    html += '</td>\n'
    html += '</tr>\n'
    html += '</table>\n'

    html += '<!--[if mso]>\n'
    html += '</v:textbox>\n'
    html += '</v:rect>\n'
    html += '<![endif]-->\n'

    html += '</td>\n'
    html += '</tr>\n'

    return html


def renderizar_boletim(slug, nome_bonito, noticias, data_extenso):
    total = len(noticias)
    nome_completo = "Boletim Lobo de Rizzo - " + nome_bonito

    if total == 0:
        corpo_linhas = '<tr>'
        corpo_linhas += '<td bgcolor="' + COR_BRANCO + '" style="background-color:' + COR_BRANCO + ';padding:80px 40px;text-align:center;font-family:Arial,Helvetica,sans-serif;font-style:italic;color:' + COR_TEXTO_SUAVE + ';font-size:14px;">'
        corpo_linhas += 'Nenhuma noticia relevante nesta edicao.'
        corpo_linhas += '</td>'
        corpo_linhas += '</tr>'
    else:
        corpo_linhas = ''
        for i, noticia in enumerate(noticias):
            primeiro = (i == 0)
            corpo_linhas += renderizar_item(noticia, primeiro=primeiro)

        # Padding final do corpo
        corpo_linhas += '<tr><td bgcolor="' + COR_BRANCO + '" style="background-color:' + COR_BRANCO + ';padding:8px 0 0 0;font-size:0;line-height:0;">&nbsp;</td></tr>\n'

    if total == 1:
        contador = '1 destaque'
    else:
        contador = str(total) + ' destaques'

    html = '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">\n'
    html += '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" lang="pt-BR">\n'
    html += '<head>\n'
    html += '<meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />\n'
    html += '<meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
    html += '<meta name="color-scheme" content="light" />\n'
    html += '<meta name="supported-color-schemes" content="light" />\n'
    html += '<title>' + escape_html(nome_completo) + '</title>\n'
    html += '<!--[if mso]>\n'
    html += '<xml>\n'
    html += '<o:OfficeDocumentSettings>\n'
    html += '<o:AllowPNG/>\n'
    html += '<o:PixelsPerInch>96</o:PixelsPerInch>\n'
    html += '</o:OfficeDocumentSettings>\n'
    html += '</xml>\n'
    html += '<![endif]-->\n'
    html += '<style type="text/css">\n'
    html += 'body, table, td { -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%; }\n'
    html += 'body { margin:0 !important; padding:0 !important; background-color:' + COR_CINZA_FUNDO + ' !important; }\n'
    html += 'table { border-collapse:collapse; mso-table-lspace:0pt; mso-table-rspace:0pt; }\n'
    html += 'img { border:0; -ms-interpolation-mode:bicubic; }\n'
    html += 'a { color:' + COR_VERDE_ESCURO + '; }\n'
    html += '</style>\n'
    html += '</head>\n'
    html += '<body bgcolor="' + COR_CINZA_FUNDO + '" style="margin:0;padding:0;background-color:' + COR_CINZA_FUNDO + ';">\n'

    html += '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="' + COR_CINZA_FUNDO + '" style="background-color:' + COR_CINZA_FUNDO + ';">\n'
    html += '<tr>\n'
    html += '<td align="center" style="padding:24px 12px;">\n'

    html += '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="680" style="max-width:680px;width:100%;">\n'

    html += renderizar_header(nome_bonito, data_extenso, contador)
    html += corpo_linhas
    html += renderizar_footer()

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
    print("Versao 4 - Identidade visual LDR (baseada em banners)")
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
    print("Concluido. Layout inspirado nos banners oficiais LDR.")
    print("Compativel com Outlook Desktop, Web e demais clientes.")
    print("=" * 60)


if __name__ == "__main__":
    main()
