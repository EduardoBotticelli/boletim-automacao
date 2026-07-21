"""
Gera os 9 boletins finais (email_*.html) a partir da revisao da Alice.

Fluxo:
1. Le output/boletim.json (dados originais do backend)
2. Le output/decisoes_alice.json (decisoes da revisao no site)
3. Aplica as decisoes: filtra apenas itens aprovados/ajustados
4. Sobrescreve os arquivos output/email_*.html com layout "boletim final"

Layout: limpo, pronto pra advogado ler no e-mail.
Sem metadados internos (palavras-chave, boletins rejeitados, motivo da IA).
"""
import os
import json
import datetime
import sys

# Configuracao de paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOLETIM_PATH = os.path.join(BASE_DIR, "output", "boletim.json")
DECISOES_PATH = os.path.join(BASE_DIR, "output", "decisoes_alice.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# Slugs -> nomes bonitos
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


def escape_html(texto):
    """Escapa caracteres HTML perigosos."""
    if texto is None:
        return ""
    s = str(texto)
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    s = s.replace('"', "&quot;")
    return s


def formatar_data_extenso(iso):
    """Converte '2026-07-15' em '15 de julho de 2026'."""
    try:
        d = datetime.date.fromisoformat(iso[:10])
        return str(d.day) + " de " + MESES_PT[d.month - 1] + " de " + str(d.year)
    except Exception:
        return iso or ""


def formatar_data_curta(iso):
    """Converte '2026-07-15' em '15/07/2026'."""
    try:
        d = datetime.date.fromisoformat(iso[:10])
        return d.strftime("%d/%m/%Y")
    except Exception:
        return iso or ""


def carregar_boletim_original():
    """Carrega o boletim.json original."""
    if not os.path.exists(BOLETIM_PATH):
        raise SystemExit("ERRO: " + BOLETIM_PATH + " nao encontrado")
    with open(BOLETIM_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def carregar_decisoes():
    """Carrega as decisoes da Alice. Retorna None se arquivo nao existe."""
    if not os.path.exists(DECISOES_PATH):
        print("AVISO: " + DECISOES_PATH + " nao encontrado.")
        print("Sem decisoes da Alice - nenhum boletim final sera gerado.")
        return None
    with open(DECISOES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def aplicar_decisoes(itens_originais, decisoes):
    """
    Aplica as decisoes aos itens.
    Retorna lista de itens efetivos com boletins finais atualizados.

    Cada item do site tem id no formato "real-N" (index no boletim.json)
    ou "manual-timestamp" (adicionado manualmente pela Alice).
    """
    # Constroi mapa id -> decisao
    mapa_decisoes = {}
    itens_manuais_payload = {}

    for dec in decisoes.get("itens", []):
        id_dec = dec.get("id", "")
        mapa_decisoes[id_dec] = dec
        # Se decisao inclui payload (item manual), guarda
        if "noticia" in dec:
            itens_manuais_payload[id_dec] = dec["noticia"]

    resultado = []

    # Processa itens do backend (formato "real-N")
    for indice, item_original in enumerate(itens_originais):
        id_item = "real-" + str(indice)
        decisao = mapa_decisoes.get(id_item)

        if decisao is None:
            # Sem decisao registrada = item pendente que Alice nao mexeu
            # Se tem boletins originais (nao era orfa), ainda aparece
            # Se era orfa, cai fora (comportamento consistente com o site)
            boletins_originais = item_original.get("boletins", [])
            if boletins_originais:
                resultado.append({
                    "noticia": item_original,
                    "boletins_finais": list(boletins_originais),
                })
            continue

        status = decisao.get("status", "")
        boletins = decisao.get("boletins", [])

        # Filtra: so entra se aprovado/ajustado E com pelo menos 1 boletim
        if status in ("aprovado", "ajustado") and boletins:
            resultado.append({
                "noticia": item_original,
                "boletins_finais": list(boletins),
            })

    # Processa itens manuais (formato "manual-timestamp")
    for id_dec, decisao in mapa_decisoes.items():
        if not id_dec.startswith("manual-"):
            continue

        status = decisao.get("status", "")
        boletins = decisao.get("boletins", [])

        if status not in ("aprovado", "ajustado") or not boletins:
            continue

        # Item manual precisa vir com payload da noticia junto
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
    """
    Agrupa itens por boletim. Um item que vai pra multiplos boletins aparece em cada um.
    Retorna dict: slug_boletim -> lista de noticias.
    """
    agrupados = {slug: [] for slug in NOMES_BOLETINS.keys()}
    for item in itens:
        for slug in item["boletins_finais"]:
            if slug in agrupados:
                agrupados[slug].append(item["noticia"])
    return agrupados


def renderizar_item(noticia):
    """Renderiza uma noticia individual dentro do boletim final."""
    titulo = escape_html(noticia.get("titulo", ""))
    resumo = escape_html(noticia.get("resumo", ""))
    fonte = escape_html(noticia.get("fonte", ""))
    data_pub = escape_html(formatar_data_curta(noticia.get("data_publicacao", "")))
    url = escape_html(noticia.get("url", ""))

    html = '<article style="margin: 0 0 28px 0; padding: 0 0 24px 0; border-bottom: 1px solid #e5e7eb;">'

    # Titulo
    html += '<h3 style="margin: 0 0 10px 0; font-size: 17px; font-weight: 600; line-height: 1.4; color: #0d3320;">'
    html += titulo
    html += '</h3>'

    # Resumo
    html += '<p style="margin: 0 0 14px 0; font-size: 14.5px; line-height: 1.6; color: #333;">'
    html += resumo
    html += '</p>'

    # Rodape do item: fonte, data, link
    html += '<div style="font-size: 12.5px; color: #666;">'
    html += '<span style="font-weight: 500;">' + fonte + '</span>'
    if data_pub:
        html += ' &nbsp;&middot;&nbsp; ' + data_pub
    if url:
        html += ' &nbsp;&middot;&nbsp; '
        html += '<a href="' + url + '" style="color: #1a4d2e; text-decoration: none; font-weight: 500;" target="_blank" rel="noopener">Ler noticia completa &rarr;</a>'
    html += '</div>'

    html += '</article>'
    return html


def renderizar_boletim(slug, nome_bonito, noticias, data_extenso):
    """Gera o HTML completo de um boletim."""
    total = len(noticias)

    # Corpo do boletim
    if total == 0:
        corpo = '<div style="padding: 40px 0; text-align: center; color: #999; font-style: italic;">'
        corpo += 'Nenhuma noticia relevante nesta edicao.'
        corpo += '</div>'
    else:
        corpo = ''
        for noticia in noticias:
            corpo += renderizar_item(noticia)

    # Monta HTML final
    html = '<!DOCTYPE html>\n'
    html += '<html lang="pt-BR">\n'
    html += '<head>\n'
    html += '  <meta charset="UTF-8">\n'
    html += '  <title>Boletim ' + escape_html(nome_bonito) + '</title>\n'
    html += '</head>\n'
    html += '<body style="margin: 0; padding: 0; background: #f5f7f5; font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, Arial, sans-serif; color: #1a1a1a;">\n'
    html += '\n'

    # Container centralizado
    html += '<div style="max-width: 680px; margin: 0 auto; background: #ffffff;">\n'

    # Header verde LDR
    html += '  <div style="background: linear-gradient(135deg, #0d3320 0%, #1a4d2e 50%, #2d8659 100%); padding: 32px 32px 28px 32px; color: #ffffff;">\n'
    html += '    <div style="font-size: 11px; letter-spacing: 3px; color: #a8d8b9; text-transform: uppercase; margin-bottom: 6px;">Boletim Diario</div>\n'
    html += '    <h1 style="margin: 0; font-size: 26px; font-weight: 400; letter-spacing: -0.3px; color: #ffffff;">' + escape_html(nome_bonito) + '</h1>\n'
    html += '    <div style="margin-top: 14px; font-size: 13.5px; color: #d4e6d9;">' + escape_html(data_extenso) + '</div>\n'
    html += '  </div>\n'

    # Corpo
    html += '  <div style="padding: 32px 32px 24px 32px;">\n'
    html += corpo + '\n'
    html += '  </div>\n'

    # Rodape verde LDR
    html += '  <div style="background: #0d3320; padding: 24px 32px; color: #a8d8b9; text-align: center; font-size: 11.5px;">\n'
    html += '    <div style="font-weight: 500; letter-spacing: 1px; margin-bottom: 4px;">LOBO DE RIZZO ADVOGADOS</div>\n'
    html += '    <div style="font-style: italic; opacity: 0.85;">Curadoria automatizada com revisao editorial</div>\n'
    html += '  </div>\n'

    html += '</div>\n'
    html += '\n'
    html += '</body>\n'
    html += '</html>\n'

    return html


def salvar_boletim(slug, conteudo_html):
    """Salva o HTML do boletim final, sobrescrevendo o arquivo original."""
    path = os.path.join(OUTPUT_DIR, "email_" + slug + ".html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(conteudo_html)
    return path


def main():
    print("=" * 60)
    print("Gerador de Boletins Finais (pos-revisao Alice)")
    print("=" * 60)

    # 1. Carrega dados
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

    # 2. Aplica decisoes
    print("\nAplicando decisoes...")
    itens_finais = aplicar_decisoes(itens_originais, decisoes)
    print("  " + str(len(itens_finais)) + " itens efetivos (aprovados+ajustados)")

    # 3. Agrupa por boletim
    print("\nAgrupando por boletim...")
    agrupados = agrupar_por_boletim(itens_finais)
    for slug, noticias in agrupados.items():
        print("  " + slug + ": " + str(len(noticias)) + " noticias")

    # 4. Data extenso pro cabecalho
    data_execucao = boletim.get("data_execucao", "")
    data_extenso = formatar_data_extenso(data_execucao) if data_execucao else formatar_data_extenso(str(datetime.date.today()))

    # 5. Renderiza e salva os 9 boletins
    print("\nGerando arquivos HTML...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for slug, nome_bonito in NOMES_BOLETINS.items():
        noticias = agrupados.get(slug, [])
        html = renderizar_boletim(slug, nome_bonito, noticias, data_extenso)
        path = salvar_boletim(slug, html)
        print("  " + os.path.basename(path) + " (" + str(len(noticias)) + " noticias)")

    print("\n" + "=" * 60)
    print("Concluido. 9 arquivos email_*.html sobrescritos em output/")
    print("=" * 60)


if __name__ == "__main__":
    main()
