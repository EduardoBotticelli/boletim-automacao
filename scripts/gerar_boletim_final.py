"""
Gera os 9 Radares finais (email_*.html) a partir da revisao.

VERSAO 4.2: Nova nomenclatura dos Radares Lobo de Rizzo.
- Mantem os slugs tecnicos existentes para nao quebrar integracoes
- Atualiza os nomes visiveis para "Radar"
- Contencioso Civel passa a ser exibido como "Radar Solucao de Conflitos"
- Inclui a descricao institucional dos Radares
- Mantem identidade visual baseada nos banners oficiais do LDR
- Mantem compatibilidade com Outlook Desktop, Outlook Web e outros clientes
"""

import os
import json
import datetime
import sys


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOLETIM_PATH = os.path.join(BASE_DIR, "output", "boletim.json")
DECISOES_PATH = os.path.join(BASE_DIR, "output", "decisoes_alice.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")


# Os slugs tecnicos permanecem inalterados.
# Apenas os nomes visiveis foram atualizados para a nova nomenclatura.
NOMES_BOLETINS = {
    "trabalhista-empresarial": "Radar Trabalhista Empresarial",
    "direito-tributario": "Radar Tributário",
    "societario-ma": "Radar Societário, Fusões e Aquisições",
    "mercado-capitais-fundos": "Radar Mercado de Capitais e Fundos de Investimento",
    "regulatorio-oleo-gas": "Radar Regulatório e Óleo e Gás",
    "imobiliario-infraestrutura": "Radar Negócios Imobiliários e Infraestrutura",
    "ambiental-esg": "Radar Ambiental e ESG",
    "propriedade-intelectual": "Radar Propriedade Intelectual, Tecnologia e Privacidade",
    "contencioso-civel": "Radar Solução de Conflitos",
}


DESCRICAO_RADARES = (
    "Informativo com atualizações legislativas, regulamentações, "
    "consultas públicas e publicações de órgãos reguladores."
)


MESES_PT = [
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
]


# Paleta LDR baseada nos banners oficiais.
COR_VERDE_ESCURO = "#0d3320"
COR_VERDE_VIBRANTE = "#22c55e"
COR_VERDE_MEDIO = "#1a4d2e"
COR_VERDE_CLARO = "#a8d8b9"
COR_VERDE_OLIVA = "#6b7c6e"
COR_TEXTO_SUAVE = "#4a5d51"
COR_LINK = "#0d3320"
COR_CINZA_LINHA = "#e5e7eb"
COR_CINZA_FUNDO = "#f4f6f5"
COR_BRANCO = "#ffffff"
COR_TEXTO_PRETO = "#1a1a1a"
COR_METADADO = "#6b7280"


# Temporario. A numeracao definitiva pode ser integrada ao template oficial.
NUMERO_EDICAO = "1"


def escape_html(texto):
    """
    Escapa caracteres especiais para impedir quebra da estrutura HTML.

    A ordem e importante: o caractere & deve ser processado primeiro.
    """
    if texto is None:
        return ""

    valor = str(texto)
    valor = valor.replace("&", "&amp;")
    valor = valor.replace("<", "&lt;")
    valor = valor.replace(">", "&gt;")
    valor = valor.replace('"', "&quot;")
    valor = valor.replace("'", "&#39;")
    return valor


def formatar_data_extenso(iso):
    """
    Converte uma data ISO em formato por extenso.

    Exemplo:
    2026-08-21 -> 21 de agosto de 2026
    """
    try:
        data = datetime.date.fromisoformat(iso[:10])
        return (
            str(data.day)
            + " de "
            + MESES_PT[data.month - 1]
            + " de "
            + str(data.year)
        )
    except Exception:
        return iso or ""


def formatar_data_curta(iso):
    """
    Converte uma data ISO em dd/mm/aaaa.
    """
    try:
        data = datetime.date.fromisoformat(iso[:10])
        return data.strftime("%d/%m/%Y")
    except Exception:
        return iso or ""


def carregar_boletim_original():
    """
    Carrega o output/boletim.json gerado pelo pipeline de coleta e IA.
    """
    if not os.path.exists(BOLETIM_PATH):
        raise SystemExit(
            "ERRO: arquivo boletim.json nao encontrado em " + BOLETIM_PATH
        )

    with open(BOLETIM_PATH, "r", encoding="utf-8") as arquivo:
        return json.load(arquivo)


def carregar_decisoes():
    """
    Carrega as decisoes confirmadas no portal de curadoria.
    """
    if not os.path.exists(DECISOES_PATH):
        print("AVISO: " + DECISOES_PATH + " nao encontrado.")
        print("Nenhum Radar final sera gerado sem uma revisao confirmada.")
        return None

    with open(DECISOES_PATH, "r", encoding="utf-8") as arquivo:
        return json.load(arquivo)


def aplicar_decisoes(itens_originais, decisoes):
    """
    Aplica as decisoes registradas no portal.

    Regras:
    - aprovado ou ajustado com boletim definido: entra no Radar final;
    - rejeitado: nao entra;
    - pendente: nao entra;
    - item manual: precisa conter o payload completo da noticia;
    - item original sem decisao explicita usa os boletins originais.
    """
    mapa_decisoes = {}
    itens_manuais_payload = {}

    for decisao in decisoes.get("itens", []):
        id_decisao = decisao.get("id", "")
        mapa_decisoes[id_decisao] = decisao

        if "noticia" in decisao:
            itens_manuais_payload[id_decisao] = decisao["noticia"]

    resultado = []

    # Processar itens vindos do backend.
    for indice, item_original in enumerate(itens_originais):
        id_item = "real-" + str(indice)
        decisao = mapa_decisoes.get(id_item)

        if decisao is None:
            boletins_originais = item_original.get("boletins", [])

            if boletins_originais:
                resultado.append(
                    {
                        "noticia": item_original,
                        "boletins_finais": list(boletins_originais),
                    }
                )

            continue

        status = decisao.get("status", "")
        boletins = decisao.get("boletins", [])

        if status in ("aprovado", "ajustado") and boletins:
            resultado.append(
                {
                    "noticia": item_original,
                    "boletins_finais": list(boletins),
                }
            )

    # Processar itens adicionados manualmente no portal.
    for id_decisao, decisao in mapa_decisoes.items():
        if not id_decisao.startswith("manual-"):
            continue

        status = decisao.get("status", "")
        boletins = decisao.get("boletins", [])

        if status not in ("aprovado", "ajustado") or not boletins:
            continue

        noticia_manual = itens_manuais_payload.get(id_decisao)

        if noticia_manual is None:
            print(
                "AVISO: item manual "
                + id_decisao
                + " sem payload completo. Item ignorado."
            )
            continue

        resultado.append(
            {
                "noticia": noticia_manual,
                "boletins_finais": list(boletins),
            }
        )

    return resultado


def agrupar_por_boletim(itens):
    """
    Agrupa as noticias pelos slugs tecnicos dos Radares.

    Uma noticia pode aparecer em mais de um Radar.
    """
    agrupados = {
        slug: []
        for slug in NOMES_BOLETINS.keys()
    }

    for item in itens:
        for slug in item["boletins_finais"]:
            if slug in agrupados:
                agrupados[slug].append(item["noticia"])

    return agrupados


def renderizar_item(noticia, primeiro=False):
    """
    Renderiza uma noticia dentro do HTML final.

    Usa tabelas e CSS inline para melhorar a compatibilidade com Outlook.
    """
    titulo = escape_html(noticia.get("titulo", ""))
    resumo = escape_html(noticia.get("resumo", ""))
    fonte = escape_html(noticia.get("fonte", ""))
    data_publicacao = escape_html(
        formatar_data_curta(noticia.get("data_publicacao", ""))
    )
    url = escape_html(noticia.get("url", ""))

    padding_top = "0" if primeiro else "24"

    html = "<tr>"

    html += (
        '<td bgcolor="'
        + COR_BRANCO
        + '" style="background-color:'
        + COR_BRANCO
        + ";padding:"
        + padding_top
        + 'px 40px 24px 40px;">'
    )

    # Linha decorativa entre as noticias.
    if not primeiro:
        html += (
            '<table role="presentation" cellpadding="0" cellspacing="0" '
            'border="0" style="margin:0 0 20px 0;">'
        )

        html += (
            '<tr><td bgcolor="'
            + COR_VERDE_VIBRANTE
            + '" style="background-color:'
            + COR_VERDE_VIBRANTE
            + ';width:32px;height:3px;font-size:0;line-height:0;">'
            "&nbsp;</td></tr>"
        )

        html += "</table>"

    # Fonte e data.
    html += (
        '<div style="font-family:Arial,Helvetica,sans-serif;'
        "font-size:11px;color:"
        + COR_METADADO
        + ';margin-bottom:10px;letter-spacing:0.3px;">'
    )

    html += (
        '<span style="font-weight:600;color:'
        + COR_VERDE_MEDIO
        + ';text-transform:uppercase;">'
        + fonte
        + "</span>"
    )

    if data_publicacao:
        html += " &nbsp;&middot;&nbsp; " + data_publicacao

    html += "</div>"

    # Titulo.
    html += (
        '<div style="margin:0 0 12px 0;'
        "font-family:Arial,Helvetica,sans-serif;"
        "font-size:18px;font-weight:700;line-height:1.35;color:"
        + COR_VERDE_ESCURO
        + ';">'
    )

    html += titulo
    html += "</div>"

    # Resumo.
    html += (
        '<div style="margin:0 0 16px 0;'
        "font-family:Arial,Helvetica,sans-serif;"
        "font-size:14px;line-height:1.65;color:"
        + COR_TEXTO_PRETO
        + ';">'
    )

    html += resumo
    html += "</div>"

    # Link para a publicacao original.
    if url:
        html += (
            '<table role="presentation" cellpadding="0" cellspacing="0" '
            'border="0">'
        )

        html += '<tr><td style="padding-top:4px;">'

        html += (
            ''
            + url
            + ''
        )

        html += "Ler notícia completa &rarr;"
        html += "</a>"
        html += "</td></tr>"
        html += "</table>"

    html += "</td>"
    html += "</tr>"

    return html


def renderizar_header(nome_radar, data_extenso, contador):
    """
    Renderiza o cabeçalho institucional do Radar.
    """
    html = "<tr>"

    html += (
        '<td bgcolor="'
        + COR_VERDE_ESCURO
        + '" style="background-color:'
        + COR_VERDE_ESCURO
        + ';padding:0;">'
    )

    html += (
        '<table role="presentation" cellpadding="0" cellspacing="0" '
        'border="0" width="100%" bgcolor="'
        + COR_VERDE_ESCURO
        + '" style="background-color:'
        + COR_VERDE_ESCURO
        + ';">'
    )

    html += "<tr>"

    html += (
        '<td bgcolor="'
        + COR_VERDE_ESCURO
        + '" style="background-color:'
        + COR_VERDE_ESCURO
        + ';padding:40px 40px 36px 40px;">'
    )

    # Identificacao institucional e edicao.
    html += (
        '<div style="font-family:Arial,Helvetica,sans-serif;'
        "font-size:11px;letter-spacing:2px;color:"
        + COR_VERDE_CLARO
        + ";text-transform:uppercase;font-weight:600;"
        'margin-bottom:24px;mso-line-height-rule:exactly;">'
    )

    html += (
        "Radares Lobo de Rizzo"
        " &nbsp;&middot;&nbsp; "
        "Edição "
        + NUMERO_EDICAO
    )

    html += "</div>"

    # Nome do Radar.
    html += (
        '<div style="margin:0;'
        "font-family:Arial,Helvetica,sans-serif;"
        "font-size:32px;font-weight:700;color:"
        + COR_BRANCO
        + ";line-height:1.15;letter-spacing:-0.5px;"
        'mso-line-height-rule:exactly;">'
    )

    html += escape_html(nome_radar)
    html += "</div>"

    # Descricao institucional.
    html += (
        '<div style="margin-top:14px;'
        "font-family:Arial,Helvetica,sans-serif;"
        "font-size:13px;line-height:1.55;color:"
        + COR_VERDE_CLARO
        + ';mso-line-height-rule:exactly;">'
    )

    html += escape_html(DESCRICAO_RADARES)
    html += "</div>"

    # Linha decorativa.
    html += (
        '<table role="presentation" cellpadding="0" cellspacing="0" '
        'border="0" style="margin-top:24px;">'
    )

    html += (
        '<tr><td bgcolor="'
        + COR_VERDE_VIBRANTE
        + '" style="background-color:'
        + COR_VERDE_VIBRANTE
        + ';width:64px;height:4px;font-size:0;line-height:0;">'
        "&nbsp;</td></tr>"
    )

    html += "</table>"

    # Data e contador.
    html += (
        '<div style="margin-top:20px;'
        "font-family:Arial,Helvetica,sans-serif;"
        "font-size:13px;color:"
        + COR_VERDE_CLARO
        + ';mso-line-height-rule:exactly;">'
    )

    html += escape_html(data_extenso)
    html += " &nbsp;&middot;&nbsp; "
    html += escape_html(contador)
    html += "</div>"

    html += "</td>"
    html += "</tr>"
    html += "</table>"
    html += "</td>"
    html += "</tr>"

    return html


def renderizar_footer():
    """
    Renderiza o aviso de circulacao interna e o rodape institucional.
    """
    html = ""

    # Aviso de circulacao interna.
    html += "<tr>"

    html += (
        '<td bgcolor="'
        + COR_BRANCO
        + '" style="background-color:'
        + COR_BRANCO
        + ";padding:32px 40px;border-top:1px solid "
        + COR_CINZA_LINHA
        + ';">'
    )

    html += (
        '<div style="font-family:Arial,Helvetica,sans-serif;'
        "font-size:11px;color:"
        + COR_METADADO
        + ";font-style:italic;text-align:center;"
        'line-height:1.5;">'
    )

    html += "Este Radar é somente para circulação interna.<br />"
    html += "A distribuição das informações aqui contidas é proibida."

    html += "</div>"
    html += "</td>"
    html += "</tr>"

    # Rodape institucional.
    html += "<tr>"

    html += (
        '<td bgcolor="'
        + COR_VERDE_OLIVA
        + '" style="background-color:'
        + COR_VERDE_OLIVA
        + ';padding:0;">'
    )

    html += (
        '<table role="presentation" cellpadding="0" cellspacing="0" '
        'border="0" width="100%" bgcolor="'
        + COR_VERDE_OLIVA
        + '" style="background-color:'
        + COR_VERDE_OLIVA
        + ';">'
    )

    html += "<tr>"

    html += (
        '<td bgcolor="'
        + COR_VERDE_OLIVA
        + '" style="background-color:'
        + COR_VERDE_OLIVA
        + ';padding:24px 40px;">'
    )

    html += (
        '<table role="presentation" cellpadding="0" cellspacing="0" '
        'border="0" width="100%">'
    )

    html += "<tr>"

    html += (
        '<td align="left" style="'
        "font-family:Arial,Helvetica,sans-serif;"
        "font-size:12px;color:"
        + COR_BRANCO
        + ';font-weight:600;letter-spacing:1.5px;">'
    )

    html += "LOBO DE RIZZO ADVOGADOS"
    html += "</td>"

    html += (
        '<td align="right" style="'
        "font-family:Arial,Helvetica,sans-serif;"
        "font-size:12px;color:"
        + COR_BRANCO
        + ';">'
    )

    html += "ldr.com.br"
    html += "</td>"

    html += "</tr>"
    html += "</table>"

    html += (
        '<div style="margin-top:12px;'
        "font-family:Arial,Helvetica,sans-serif;"
        "font-size:11px;color:"
        + COR_BRANCO
        + ';opacity:0.85;">'
    )

    html += (
        "Av. Brig. Faria Lima, 3900 - "
        "Itaim Bibi, São Paulo - SP, 04538-132"
    )

    html += "</div>"
    html += "</td>"
    html += "</tr>"
    html += "</table>"
    html += "</td>"
    html += "</tr>"

    return html


def renderizar_boletim(slug, nome_radar, noticias, data_extenso):
    """
    Monta o documento HTML completo de um Radar.
    """
    total = len(noticias)
    nome_completo = nome_radar + " - Lobo de Rizzo Advogados"

    if total == 0:
        corpo_linhas = "<tr>"

        corpo_linhas += (
            '<td bgcolor="'
            + COR_BRANCO
            + '" style="background-color:'
            + COR_BRANCO
            + ";padding:80px 40px;text-align:center;"
            "font-family:Arial,Helvetica,sans-serif;"
            "font-style:italic;color:"
            + COR_TEXTO_SUAVE
            + ';font-size:14px;">'
        )

        corpo_linhas += "Nenhuma atualização relevante nesta edição."
        corpo_linhas += "</td>"
        corpo_linhas += "</tr>"

    else:
        corpo_linhas = ""

        for indice, noticia in enumerate(noticias):
            primeiro = indice == 0
            corpo_linhas += renderizar_item(
                noticia,
                primeiro=primeiro,
            )

        corpo_linhas += (
            '<tr><td bgcolor="'
            + COR_BRANCO
            + '" style="background-color:'
            + COR_BRANCO
            + ';padding:8px 0 0 0;font-size:0;line-height:0;">'
            "&nbsp;</td></tr>"
        )

    if total == 1:
        contador = "1 destaque"
    else:
        contador = str(total) + " destaques"

    html = (
        '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" '
        '"http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">'
    )

    html += (
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:v="urn:schemas-microsoft-com:vml" '
        'xmlns:o="urn:schemas-microsoft-com:office:office" '
        'lang="pt-BR">'
    )

    html += "<head>"
    html += '<meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />'
    html += '<meta name="viewport" content="width=device-width, initial-scale=1.0" />'
    html += '<meta name="color-scheme" content="light dark" />'
    html += '<meta name="supported-color-schemes" content="light dark" />'
    html += "<title>" + escape_html(nome_completo) + "</title>"

    html += "<!--[if mso]>"
    html += "<xml>"
    html += "<o:OfficeDocumentSettings>"
    html += "<o:AllowPNG/>"
    html += "<o:PixelsPerInch>96</o:PixelsPerInch>"
    html += "</o:OfficeDocumentSettings>"
    html += "</xml>"
    html += "<![endif]-->"

    html += '<style type="text/css">'

    html += (
        "body, table, td { "
        "-webkit-text-size-adjust:100%; "
        "-ms-text-size-adjust:100%; "
        "}"
    )

    html += (
        "body { "
        "margin:0 !important; "
        "padding:0 !important; "
        "background-color:"
        + COR_CINZA_FUNDO
        + " !important; "
        "}"
    )

    html += (
        "table { "
        "border-collapse:collapse; "
        "mso-table-lspace:0pt; "
        "mso-table-rspace:0pt; "
        "}"
    )

    html += "img { border:0; -ms-interpolation-mode:bicubic; }"
    html += "a { color:" + COR_VERDE_ESCURO + "; }"

    html += "@media (prefers-color-scheme: dark) {"
    html += "a { color:" + COR_VERDE_VIBRANTE + " !important; }"
    html += "}"

    html += "</style>"
    html += "</head>"

    html += (
        '<body bgcolor="'
        + COR_CINZA_FUNDO
        + '" style="margin:0;padding:0;background-color:'
        + COR_CINZA_FUNDO
        + ';">'
    )

    html += (
        '<table role="presentation" cellpadding="0" cellspacing="0" '
        'border="0" width="100%" bgcolor="'
        + COR_CINZA_FUNDO
        + '" style="background-color:'
        + COR_CINZA_FUNDO
        + ';">'
    )

    html += "<tr>"
    html += '<td align="center" style="padding:24px 12px;">'

    html += (
        '<table role="presentation" cellpadding="0" cellspacing="0" '
        'border="0" width="680" style="max-width:680px;width:100%;">'
    )

    html += renderizar_header(
        nome_radar,
        data_extenso,
        contador,
    )

    html += corpo_linhas
    html += renderizar_footer()

    html += "</table>"
    html += "</td>"
    html += "</tr>"
    html += "</table>"
    html += "</body>"
    html += "</html>"

    return html


def salvar_boletim(slug, conteudo_html):
    """
    Salva o HTML mantendo o nome tecnico usado pelo Power Automate.
    """
    caminho = os.path.join(
        OUTPUT_DIR,
        "email_" + slug + ".html",
    )

    with open(caminho, "w", encoding="utf-8") as arquivo:
        arquivo.write(conteudo_html)

    return caminho


def main():
    print("=" * 60)
    print("Gerador de Radares Finais (pos-revisao)")
    print("Versao 4.2 - Nova nomenclatura dos Radares LDR")
    print("=" * 60)

    print("\nCarregando boletim original...")

    boletim = carregar_boletim_original()
    itens_originais = boletim.get("itens", [])

    print(
        "  "
        + str(len(itens_originais))
        + " itens no boletim original"
    )

    print("\nCarregando decisoes da revisao...")

    decisoes = carregar_decisoes()

    if decisoes is None:
        sys.exit(0)

    total_decisoes = len(decisoes.get("itens", []))
    confirmado_em = decisoes.get(
        "confirmadoEm",
        "desconhecido",
    )

    print(
        "  "
        + str(total_decisoes)
        + " decisoes registradas"
    )

    print(
        "  Revisao confirmada em: "
        + confirmado_em
    )

    print("\nAplicando decisoes...")

    itens_finais = aplicar_decisoes(
        itens_originais,
        decisoes,
    )

    print(
        "  "
        + str(len(itens_finais))
        + " itens efetivos (aprovados e ajustados)"
    )

    print("\nAgrupando por Radar...")

    agrupados = agrupar_por_boletim(itens_finais)

    for slug, noticias in agrupados.items():
        print(
            "  "
            + slug
            + ": "
            + str(len(noticias))
            + " noticias"
        )

    data_execucao = boletim.get(
        "data_execucao",
        "",
    )

    if data_execucao:
        data_extenso = formatar_data_extenso(
            data_execucao
        )
    else:
        data_extenso = formatar_data
