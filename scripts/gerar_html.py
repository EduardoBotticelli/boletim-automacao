"""
Gera 9 HTMLs de validacao dos Radares a partir de output/boletim.json.

Uso: executar depois de scripts/gerar_boletim.py no workflow principal.
Saida: output/validacao_<slug>.html

Este script nao grava email_<slug>.html. Esses arquivos ficam reservados ao
scripts/gerar_boletim_final.py, executado depois da revisao humana.
"""

import datetime
import html
import json
import os


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_PATH = os.path.join(BASE_DIR, "output", "boletim.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

NOMES_RADARES_PADRAO = {
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

DESCRICAO_PADRAO = (
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

COR_VERDE_ESCURO = "#0d3320"
COR_VERDE_MEDIO = "#1a4d2e"
COR_VERDE_VIBRANTE = "#22c55e"
COR_VERDE_CLARO = "#a8d8b9"
COR_CINZA_FUNDO = "#f0f2f1"
COR_CINZA_LINHA = "#e5e7eb"
COR_TEXTO = "#1f2937"
COR_TEXTO_SUAVE = "#6b7280"
COR_AVISO_FUNDO = "#fff8e6"
COR_AVISO_BORDA = "#d89b24"
COR_ERRO_FUNDO = "#fef2f2"
COR_ERRO_BORDA = "#dc2626"
COR_BRANCO = "#ffffff"


def escapar(valor):
    if valor is None:
        return ""
    return html.escape(str(valor), quote=True)


def formatar_data_extenso(valor):
    try:
        data = datetime.date.fromisoformat(str(valor)[:10])
        return f"{data.day} de {MESES_PT[data.month - 1]} de {data.year}"
    except (TypeError, ValueError):
        return str(valor or "")


def formatar_data_curta(valor):
    try:
        data = datetime.date.fromisoformat(str(valor)[:10])
        return data.strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(valor or "Data não identificada")


def carregar_boletim():
    if not os.path.exists(INPUT_PATH):
        raise SystemExit("ERRO: boletim.json não encontrado em " + INPUT_PATH)

    with open(INPUT_PATH, "r", encoding="utf-8") as arquivo:
        dados = json.load(arquivo)

    if not isinstance(dados, dict):
        raise SystemExit("ERRO: boletim.json não contém um objeto JSON válido.")

    if not isinstance(dados.get("itens"), list):
        raise SystemExit("ERRO: boletim.json não contém uma lista válida em 'itens'.")

    if dados.get("erro"):
        raise SystemExit(
            "ERRO: boletim.json registra falha na geração: " + str(dados.get("erro"))
        )

    return dados


def nomes_fontes(lista):
    resultado = []
    vistos = set()
    if not isinstance(lista, list):
        return resultado

    for item in lista:
        if isinstance(item, dict):
            nome = str(item.get("fonte", "")).strip()
        elif isinstance(item, str):
            nome = item.strip()
        else:
            continue

        if nome and nome not in vistos:
            vistos.add(nome)
            resultado.append(nome)

    return resultado


def fontes_do_radar(mapeamento, slug):
    fontes = []
    if not isinstance(mapeamento, dict):
        return fontes

    for fonte, radares in mapeamento.items():
        if isinstance(radares, list) and slug in radares:
            fontes.append(str(fonte))

    return fontes


def agrupar_itens_por_fonte(itens):
    agrupados = {}
    ordem = []

    for item in itens:
        fonte = str(item.get("fonte", "Fonte não identificada"))
        if fonte not in agrupados:
            agrupados[fonte] = []
            ordem.append(fonte)
        agrupados[fonte].append(item)

    return [(fonte, agrupados[fonte]) for fonte in ordem]


def renderizar_lista_nomes(titulo, nomes, cor_fundo, cor_borda):
    if not nomes:
        return ""

    nomes_html = ", ".join(escapar(nome) for nome in nomes)
    return f"""
    <tr>
      <td bgcolor="{cor_fundo}" style="background-color:{cor_fundo};border-left:4px solid {cor_borda};padding:14px 22px;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.55;color:{COR_TEXTO};">
        <strong>{escapar(titulo)}:</strong> {nomes_html}
      </td>
    </tr>
    """


def renderizar_item(item, primeiro):
    titulo = escapar(item.get("titulo", "Sem título"))
    resumo = escapar(item.get("resumo", ""))
    fonte = escapar(item.get("fonte", "Fonte não identificada"))
    data_publicacao = escapar(formatar_data_curta(item.get("data_publicacao", "")))
    motivo = escapar(item.get("motivo_filtragem", ""))
    url = escapar(item.get("url", ""))
    palavras = item.get("palavras_chave_detectadas", [])
    palavras = palavras if isinstance(palavras, list) else []
    palavras_html = ", ".join(escapar(p) for p in palavras if isinstance(p, str))
    borda_superior = "" if primeiro else f"border-top:1px solid {COR_CINZA_LINHA};"

    link_html = ""
    if url:
        link_html = f"""
        <table role="presentation" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td style="padding-top:4px;">
              <a href="{url}" style="font-family:Arial,Helvetica,sans-serif;font-size:12px;font-weight:700;color:{COR_VERDE_ESCURO};text-decoration:none;border-bottom:2px solid {COR_VERDE_VIBRANTE};padding-bottom:3px;">
                Acessar publicação &rarr;
              </a>
            </td>
          </tr>
        </table>
        """

    palavras_bloco = ""
    if palavras_html:
        palavras_bloco = f"""
        <div style="margin-top:9px;font-family:Arial,Helvetica,sans-serif;font-size:11px;line-height:1.5;color:{COR_TEXTO_SUAVE};">
          <strong>Termos detectados:</strong> {palavras_html}
        </div>
        """

    motivo_bloco = ""
    if motivo:
        motivo_bloco = f"""
        <div style="margin-top:9px;font-family:Arial,Helvetica,sans-serif;font-size:11px;line-height:1.5;color:{COR_TEXTO_SUAVE};font-style:italic;">
          <strong>Motivo da classificação:</strong> {motivo}
        </div>
        """

    return f"""
    <tr>
      <td bgcolor="{COR_BRANCO}" style="background-color:{COR_BRANCO};padding:22px 34px;{borda_superior}">
        <div style="font-family:Arial,Helvetica,sans-serif;font-size:11px;letter-spacing:0.3px;color:{COR_TEXTO_SUAVE};margin-bottom:9px;">
          <span style="font-weight:700;color:{COR_VERDE_MEDIO};text-transform:uppercase;">{fonte}</span>
          &nbsp;&middot;&nbsp; {data_publicacao}
        </div>
        <div style="font-family:Arial,Helvetica,sans-serif;font-size:17px;font-weight:700;line-height:1.38;color:{COR_VERDE_ESCURO};margin-bottom:10px;">
          {titulo}
        </div>
        <div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:1.65;color:{COR_TEXTO};margin-bottom:13px;">
          {resumo}
        </div>
        {link_html}
        {palavras_bloco}
        {motivo_bloco}
      </td>
    </tr>
    """


def renderizar_grupo_fonte(fonte, itens):
    itens_html = "".join(
        renderizar_item(item, primeiro=(indice == 0))
        for indice, item in enumerate(itens)
    )

    return f"""
    <tr>
      <td bgcolor="#f5f8f6" style="background-color:#f5f8f6;padding:14px 34px;border-top:1px solid {COR_CINZA_LINHA};border-bottom:1px solid {COR_CINZA_LINHA};font-family:Arial,Helvetica,sans-serif;font-size:12px;font-weight:700;color:{COR_VERDE_MEDIO};text-transform:uppercase;letter-spacing:0.5px;">
        {escapar(fonte)} ({len(itens)})
      </td>
    </tr>
    {itens_html}
    """


def renderizar_html(
    slug,
    nome_radar,
    descricao,
    data_extenso,
    janela,
    itens,
    fontes_configuradas,
    fontes_email,
    fontes_defeso,
    modelo_gemini,
    clusters,
):
    total = len(itens)
    contador = "1 item" if total == 1 else f"{total} itens"
    clusters_texto = ", ".join(escapar(c) for c in clusters) if clusters else "Não informado"
    modelo_texto = escapar(modelo_gemini or "Não informado")
    janela_inicio = escapar(janela.get("inicio", ""))
    janela_fim = escapar(janela.get("fim", ""))

    if itens:
        corpo = "".join(
            renderizar_grupo_fonte(fonte, itens_fonte)
            for fonte, itens_fonte in agrupar_itens_por_fonte(itens)
        )
    else:
        corpo = f"""
        <tr>
          <td bgcolor="{COR_BRANCO}" style="background-color:{COR_BRANCO};padding:64px 34px;text-align:center;font-family:Arial,Helvetica,sans-serif;color:{COR_TEXTO_SUAVE};">
            <div style="font-size:15px;font-weight:700;color:{COR_VERDE_ESCURO};margin-bottom:8px;">Nenhum item classificado neste Radar</div>
            <div style="font-size:12px;line-height:1.55;">A página de validação permanece disponível para conferência das fontes e da janela analisada.</div>
          </td>
        </tr>
        """

    fontes_texto = ", ".join(escapar(f) for f in fontes_configuradas) or "Nenhuma fonte configurada"

    return f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" lang="pt-BR">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{escapar(nome_radar)} - Validação</title>
  <style type="text/css">
    body, table, td {{ -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%; }}
    table {{ border-collapse:collapse; mso-table-lspace:0pt; mso-table-rspace:0pt; }}
    body {{ margin:0 !important; padding:0 !important; background-color:{COR_CINZA_FUNDO} !important; }}
    a {{ color:{COR_VERDE_ESCURO}; }}
  </style>
</head>
<body bgcolor="{COR_CINZA_FUNDO}" style="margin:0;padding:0;background-color:{COR_CINZA_FUNDO};">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="{COR_CINZA_FUNDO}" style="background-color:{COR_CINZA_FUNDO};">
    <tr>
      <td align="center" style="padding:24px 12px;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="720" style="width:100%;max-width:720px;">
          <tr>
            <td bgcolor="{COR_VERDE_ESCURO}" style="background-color:{COR_VERDE_ESCURO};padding:36px 34px 32px 34px;">
              <div style="font-family:Arial,Helvetica,sans-serif;font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:{COR_VERDE_CLARO};margin-bottom:18px;">Validação da curadoria automatizada</div>
              <div style="font-family:Arial,Helvetica,sans-serif;font-size:30px;font-weight:700;line-height:1.18;color:{COR_BRANCO};">{escapar(nome_radar)}</div>
              <div style="margin-top:14px;font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:1.55;color:{COR_VERDE_CLARO};">{escapar(descricao)}</div>
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-top:20px;"><tr><td bgcolor="{COR_VERDE_VIBRANTE}" style="background-color:{COR_VERDE_VIBRANTE};width:58px;height:4px;font-size:0;line-height:0;">&nbsp;</td></tr></table>
              <div style="margin-top:18px;font-family:Arial,Helvetica,sans-serif;font-size:12px;color:{COR_VERDE_CLARO};">{escapar(data_extenso)} &nbsp;&middot;&nbsp; {contador}</div>
            </td>
          </tr>
          <tr>
            <td bgcolor="{COR_BRANCO}" style="background-color:{COR_BRANCO};padding:22px 34px;border-bottom:1px solid {COR_CINZA_LINHA};font-family:Arial,Helvetica,sans-serif;color:{COR_TEXTO};">
              <div style="font-size:14px;font-weight:700;color:{COR_VERDE_ESCURO};margin-bottom:8px;">Orientação para validação</div>
              <div style="font-size:12px;line-height:1.65;">Confira se os itens possuem aderência temática ao Radar, se alguma publicação importante ficou de fora e se os termos reconhecidos representam adequadamente a área. Esta página é apenas para validação interna e não é o e-mail final destinado aos advogados.</div>
            </td>
          </tr>
          <tr>
            <td bgcolor="#f5f8f6" style="background-color:#f5f8f6;padding:16px 34px;border-bottom:1px solid {COR_CINZA_LINHA};font-family:Arial,Helvetica,sans-serif;font-size:11px;line-height:1.6;color:{COR_TEXTO_SUAVE};">
              <div><strong style="color:{COR_VERDE_MEDIO};">Clusters:</strong> {clusters_texto}</div>
              <div><strong style="color:{COR_VERDE_MEDIO};">Modelo Gemini:</strong> {modelo_texto}</div>
              <div><strong style="color:{COR_VERDE_MEDIO};">Fontes configuradas ({len(fontes_configuradas)}):</strong> {fontes_texto}</div>
            </td>
          </tr>
          {renderizar_lista_nomes("Fontes por e-mail ainda não integradas", fontes_email, COR_AVISO_FUNDO, COR_AVISO_BORDA)}
          {renderizar_lista_nomes("Fontes temporariamente em defeso", fontes_defeso, COR_ERRO_FUNDO, COR_ERRO_BORDA)}
          {corpo}
          <tr>
            <td bgcolor="#f5f8f6" style="background-color:#f5f8f6;padding:16px 34px;border-top:1px solid {COR_CINZA_LINHA};font-family:Arial,Helvetica,sans-serif;font-size:11px;line-height:1.6;color:{COR_TEXTO_SUAVE};">
              <div><strong>Janela analisada:</strong> {janela_inicio} até {janela_fim}</div>
              <div><strong>Arquivo técnico:</strong> validacao_{escapar(slug)}.html</div>
            </td>
          </tr>
          <tr>
            <td bgcolor="{COR_VERDE_ESCURO}" style="background-color:{COR_VERDE_ESCURO};padding:18px 34px;text-align:center;font-family:Arial,Helvetica,sans-serif;font-size:10px;letter-spacing:1px;color:{COR_VERDE_CLARO};">RADARES LOBO DE RIZZO &nbsp;&middot;&nbsp; VALIDAÇÃO INTERNA</td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def main():
    boletim = carregar_boletim()
    config = boletim.get("boletins_config", {})
    config = config if isinstance(config, dict) else {}

    itens = boletim.get("itens", [])
    janela = boletim.get("janela_aplicada", {})
    janela = janela if isinstance(janela, dict) else {}
    data_extenso = formatar_data_extenso(boletim.get("data_execucao", ""))
    modelo_gemini = boletim.get("modelo_gemini_utilizado", "")

    slugs = config.get("boletins_disponiveis", list(NOMES_RADARES_PADRAO.keys()))
    slugs = slugs if isinstance(slugs, list) else list(NOMES_RADARES_PADRAO.keys())
    nomes_radares = config.get("nomes_radares", {})
    nomes_radares = nomes_radares if isinstance(nomes_radares, dict) else {}
    descricao = config.get("descricao", DESCRICAO_PADRAO) or DESCRICAO_PADRAO
    clusters_por_boletim = config.get("clusters_por_boletim", {})
    clusters_por_boletim = clusters_por_boletim if isinstance(clusters_por_boletim, dict) else {}
    fontes_email_pendentes = config.get("fontes_email_pendentes", {})
    fontes_email_pendentes = fontes_email_pendentes if isinstance(fontes_email_pendentes, dict) else {}
    mapeamento = config.get("mapeamento_fonte_boletim", {})
    mapeamento = mapeamento if isinstance(mapeamento, dict) else {}
    fontes_defeso_gerais = nomes_fontes(config.get("fontes_em_defeso", []))

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    resumo = {}

    for slug in slugs:
        if slug not in NOMES_RADARES_PADRAO:
            print("AVISO: slug desconhecido ignorado: " + str(slug))
            continue

        itens_radar = [
            item
            for item in itens
            if isinstance(item, dict) and slug in item.get("boletins", [])
        ]
        fontes_configuradas = fontes_do_radar(mapeamento, slug)
        fontes_email = nomes_fontes(fontes_email_pendentes.get(slug, []))
        fontes_defeso = [
            fonte for fonte in fontes_defeso_gerais if fonte in fontes_configuradas
        ]
        clusters = clusters_por_boletim.get(slug, [])
        clusters = clusters if isinstance(clusters, list) else []
        nome_radar = nomes_radares.get(slug, NOMES_RADARES_PADRAO[slug])

        conteudo = renderizar_html(
            slug=slug,
            nome_radar=nome_radar,
            descricao=descricao,
            data_extenso=data_extenso,
            janela=janela,
            itens=itens_radar,
            fontes_configuradas=fontes_configuradas,
            fontes_email=fontes_email,
            fontes_defeso=fontes_defeso,
            modelo_gemini=modelo_gemini,
            clusters=clusters,
        )

        caminho = os.path.join(OUTPUT_DIR, "validacao_" + slug + ".html")
        with open(caminho, "w", encoding="utf-8") as arquivo:
            arquivo.write(conteudo)

        resumo[slug] = len(itens_radar)
        print("Validação " + slug + ": " + str(len(itens_radar)) + " itens")

    print("")
    print("Concluído: " + str(len(resumo)) + " páginas de validação geradas.")
    print("Os arquivos email_<slug>.html não foram alterados.")


if __name__ == "__main__":
    main()
