"""
Gera o painel consolidado de auditoria dos Radares.

Entradas:
- output/boletim.json
- output/log_execucao.json

Saída exclusiva:
- output/auditoria.html

O painel contém somente os 12 blocos aprovados:
1. fontes processadas;
2. fontes sem resultado;
3. fontes sem publicação;
4. erros técnicos;
5. fontes em defeso;
6. totais por Radar;
7. bloqueios do Filtro 1;
8. itens bloqueados;
9. rejeições por Radar;
10. principais palavras-chave;
11. itens sem classificação;
12. links para as nove páginas de validação.
"""

import html
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
BOLETIM_PATH = OUTPUT_DIR / "boletim.json"
LOG_PATH = OUTPUT_DIR / "log_execucao.json"
AUDITORIA_PATH = OUTPUT_DIR / "auditoria.html"

NOMES_RADARES_PADRAO = {
    "trabalhista-empresarial": "Radar Trabalhista Empresarial",
    "direito-tributario": "Radar Tributário",
    "societario-ma": "Radar Societário, Fusões e Aquisições",
    "mercado-capitais-fundos": ("Radar Mercado de Capitais e Fundos de Investimento"),
    "regulatorio-oleo-gas": "Radar Regulatório e Óleo e Gás",
    "imobiliario-infraestrutura": ("Radar Negócios Imobiliários e Infraestrutura"),
    "ambiental-esg": "Radar Ambiental e ESG",
    "propriedade-intelectual": (
        "Radar Propriedade Intelectual, Tecnologia e Privacidade"
    ),
    "contencioso-civel": "Radar Solução de Conflitos",
}

ORDEM_RADARES = list(NOMES_RADARES_PADRAO.keys())

COR_VERDE_ESCURO = "#0d3320"
COR_VERDE_MEDIO = "#1a4d2e"
COR_VERDE_VIBRANTE = "#22c55e"
COR_VERDE_CLARO = "#a8d8b9"
COR_FUNDO = "#f0f2f1"
COR_CARD = "#ffffff"
COR_LINHA = "#e5e7eb"
COR_TEXTO = "#1f2937"
COR_TEXTO_SUAVE = "#6b7280"
COR_ERRO = "#b91c1c"


def escapar(valor):
    """Escapa valores que serão renderizados no HTML."""
    if valor is None:
        return ""
    return html.escape(str(valor), quote=True)


def carregar_json(caminho, nome):
    """Carrega e valida um objeto JSON."""
    if not caminho.exists():
        raise SystemExit(f"ERRO: {nome} não encontrado em {caminho}")

    try:
        with caminho.open("r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
    except json.JSONDecodeError as erro:
        raise SystemExit(f"ERRO: {nome} contém JSON inválido: {erro}") from erro

    if not isinstance(dados, dict):
        raise SystemExit(f"ERRO: {nome} deve conter um objeto JSON.")

    return dados


def normalizar_fontes(valor):
    """Normaliza fontes em strings ou objetos para uma estrutura única."""
    resultado = []

    if not isinstance(valor, list):
        return resultado

    for item in valor:
        if isinstance(item, dict):
            fonte = str(item.get("fonte", "")).strip()
            motivo = str(item.get("motivo", "")).strip()
            reativar_em = str(item.get("reativar_em", "")).strip()
        elif isinstance(item, str):
            fonte = item.strip()
            motivo = ""
            reativar_em = ""
        else:
            continue

        if fonte:
            resultado.append(
                {
                    "fonte": fonte,
                    "motivo": motivo,
                    "reativar_em": reativar_em,
                }
            )

    return resultado


def nome_radar(slug, nomes_configurados):
    """Obtém o nome visível do Radar."""
    return nomes_configurados.get(
        slug,
        NOMES_RADARES_PADRAO.get(slug, slug),
    )


def bloco_vazio(mensagem="Nenhum registro nesta categoria."):
    """Renderiza o estado vazio de uma seção."""
    return f'<div class="vazio">{escapar(mensagem)}</div>'


def renderizar_tabela(cabecalhos, linhas, classes_colunas=None):
    """Renderiza uma tabela HTML responsiva."""
    if not linhas:
        return bloco_vazio()

    classes_colunas = classes_colunas or [""] * len(cabecalhos)

    cabecalho_html = "".join(
        (f'<th class="{escapar(classes_colunas[indice])}">' f"{escapar(titulo)}</th>")
        for indice, titulo in enumerate(cabecalhos)
    )

    linhas_html = []
    for linha in linhas:
        celulas = "".join(
            (f'<td class="{escapar(classes_colunas[indice])}">' f"{valor}</td>")
            for indice, valor in enumerate(linha)
        )
        linhas_html.append(f"<tr>{celulas}</tr>")

    return (
        '<div class="tabela-wrap">'
        "<table>"
        f"<thead><tr>{cabecalho_html}</tr></thead>"
        f"<tbody>{''.join(linhas_html)}</tbody>"
        "</table>"
        "</div>"
    )


def renderizar_secao(numero, titulo, conteudo, resumo=""):
    """Renderiza uma seção numerada do painel."""
    resumo_html = f'<div class="secao-resumo">{escapar(resumo)}</div>' if resumo else ""

    return f"""
    <section class="secao" id="secao-{numero}">
      <div class="secao-cabecalho">
        <span class="numero">{numero:02d}</span>
        <div>
          <h2>{escapar(titulo)}</h2>
          {resumo_html}
        </div>
      </div>
      <div class="secao-conteudo">
        {conteudo}
      </div>
    </section>
    """


def renderizar_fontes_processadas(log):
    registros = log.get("fontes_processadas", [])
    linhas = []

    if isinstance(registros, list):
        for registro in registros:
            if not isinstance(registro, dict):
                continue

            linhas.append(
                [
                    escapar(registro.get("fonte", "")),
                    escapar(registro.get("status", "")),
                    escapar(registro.get("tamanho_chars", "")),
                ]
            )

    return (
        renderizar_tabela(
            ["Fonte", "Status", "Caracteres"],
            linhas,
            ["", "curta", "numero-coluna"],
        ),
        len(linhas),
    )


def renderizar_fontes_com_motivo(boletim, chave):
    registros = normalizar_fontes(boletim.get(chave, []))
    linhas = [[escapar(item["fonte"]), escapar(item["motivo"])] for item in registros]

    return renderizar_tabela(["Fonte", "Motivo"], linhas), len(linhas)


def renderizar_fontes_em_defeso(boletim, log):
    config = boletim.get("boletins_config", {})
    config = config if isinstance(config, dict) else {}

    registros = normalizar_fontes(config.get("fontes_em_defeso", []))

    if not registros:
        registros = normalizar_fontes(log.get("fontes_suspensas", []))

    linhas = [
        [
            escapar(item["fonte"]),
            escapar(item["motivo"]),
            escapar(item["reativar_em"]),
        ]
        for item in registros
    ]

    return (
        renderizar_tabela(
            ["Fonte", "Motivo", "Retomada"],
            linhas,
            ["", "", "curta"],
        ),
        len(linhas),
    )


def renderizar_totais_por_radar(boletim, nomes):
    estatisticas = boletim.get("estatisticas_por_boletim", {})
    estatisticas = estatisticas if isinstance(estatisticas, dict) else {}

    linhas = []
    for slug in ORDEM_RADARES:
        dados = estatisticas.get(slug, {})
        total = dados.get("total", 0) if isinstance(dados, dict) else 0
        linhas.append(
            [
                escapar(nome_radar(slug, nomes)),
                escapar(total),
            ]
        )

    return renderizar_tabela(
        ["Radar", "Total"],
        linhas,
        ["", "numero-coluna"],
    )


def renderizar_bloqueios_filtro_1(boletim, log, nomes):
    auditoria = boletim.get("auditoria", {})
    auditoria = auditoria if isinstance(auditoria, dict) else {}

    resultado = log.get("resultado", {})
    resultado = resultado if isinstance(resultado, dict) else {}

    bloqueios = resultado.get("filtro1_bloqueios", {})
    bloqueios = bloqueios if isinstance(bloqueios, dict) else {}

    linhas = []
    for slug in ORDEM_RADARES:
        quantidade = bloqueios.get(slug, 0)
        if quantidade:
            linhas.append(
                [
                    escapar(nome_radar(slug, nomes)),
                    escapar(quantidade),
                ]
            )

    total = auditoria.get("itens_com_bloqueio_f1", 0)

    return (
        renderizar_tabela(
            ["Radar bloqueado", "Quantidade"],
            linhas,
            ["", "numero-coluna"],
        ),
        total,
    )


def renderizar_itens_bloqueados(log, nomes):
    detalhes = log.get("filtro1_bloqueios_detalhe", {})
    detalhes = detalhes if isinstance(detalhes, dict) else {}

    linhas = []
    for slug in ORDEM_RADARES:
        titulos = detalhes.get(slug, [])
        if not isinstance(titulos, list):
            continue

        for titulo in titulos:
            linhas.append(
                [
                    escapar(nome_radar(slug, nomes)),
                    escapar(titulo),
                ]
            )

    return renderizar_tabela(["Radar bloqueado", "Item"], linhas), len(linhas)


def renderizar_rejeicoes_por_radar(boletim, nomes):
    auditoria = boletim.get("auditoria", {})
    auditoria = auditoria if isinstance(auditoria, dict) else {}

    rejeicoes = auditoria.get("rejeicoes_por_boletim", {})
    rejeicoes = rejeicoes if isinstance(rejeicoes, dict) else {}

    linhas = [
        [
            escapar(nome_radar(slug, nomes)),
            escapar(rejeicoes.get(slug, 0)),
        ]
        for slug in ORDEM_RADARES
    ]

    return renderizar_tabela(
        ["Radar", "Rejeições"],
        linhas,
        ["", "numero-coluna"],
    )


def renderizar_principais_palavras_chave(boletim):
    auditoria = boletim.get("auditoria", {})
    auditoria = auditoria if isinstance(auditoria, dict) else {}

    palavras = auditoria.get("top_palavras_chave_detectadas", [])
    linhas = []

    if isinstance(palavras, list):
        for item in palavras:
            if not isinstance(item, dict):
                continue

            linhas.append(
                [
                    escapar(item.get("palavra", "")),
                    escapar(item.get("ocorrencias", 0)),
                ]
            )

    return (
        renderizar_tabela(
            ["Palavra-chave", "Ocorrências"],
            linhas,
            ["", "numero-coluna"],
        ),
        len(linhas),
    )


def renderizar_itens_sem_classificacao(boletim):
    itens = boletim.get("itens", [])
    linhas = []

    if isinstance(itens, list):
        for item in itens:
            if not isinstance(item, dict):
                continue

            boletins = item.get("boletins", [])
            if not isinstance(boletins, list) or not boletins:
                linhas.append(
                    [
                        escapar(item.get("fonte", "")),
                        escapar(item.get("titulo", "")),
                        escapar(item.get("data_publicacao", "")),
                    ]
                )

    return (
        renderizar_tabela(
            ["Fonte", "Item", "Data"],
            linhas,
            ["", "", "curta"],
        ),
        len(linhas),
    )


def renderizar_links_validacao(nomes):
    links = []

    for slug in ORDEM_RADARES:
        arquivo = f"validacao_{slug}.html"
        caminho = OUTPUT_DIR / arquivo
        status = "Disponível" if caminho.exists() else "Arquivo não encontrado"
        classe = "link-ok" if caminho.exists() else "link-ausente"

        links.append(f"""
            <a class="link-validacao {classe}" href="{escapar(arquivo)}">
              <span>{escapar(nome_radar(slug, nomes))}</span>
              <small>{escapar(status)}</small>
            </a>
            """)

    return '<div class="grade-links">' + "".join(links) + "</div>"


def montar_html(boletim, log):
    config = boletim.get("boletins_config", {})
    config = config if isinstance(config, dict) else {}

    nomes = config.get("nomes_radares", {})
    nomes = nomes if isinstance(nomes, dict) else {}

    fontes_processadas, total_processadas = renderizar_fontes_processadas(log)
    fontes_sem_resultado, total_sem_resultado = renderizar_fontes_com_motivo(
        boletim,
        "fontes_sem_resultado",
    )
    fontes_sem_publicacao, total_sem_publicacao = renderizar_fontes_com_motivo(
        boletim,
        "fontes_sem_publicacao_hoje",
    )
    erros_tecnicos, total_erros = renderizar_fontes_com_motivo(
        boletim,
        "fontes_com_erro_tecnico",
    )
    fontes_defeso, total_defeso = renderizar_fontes_em_defeso(boletim, log)
    bloqueios, total_bloqueios = renderizar_bloqueios_filtro_1(
        boletim,
        log,
        nomes,
    )
    itens_bloqueados, total_itens_bloqueados = renderizar_itens_bloqueados(
        log,
        nomes,
    )
    palavras_chave, total_palavras = renderizar_principais_palavras_chave(boletim)
    itens_sem_classificacao, total_sem_classificacao = (
        renderizar_itens_sem_classificacao(boletim)
    )

    secoes = "".join(
        [
            renderizar_secao(
                1,
                "Fontes processadas",
                fontes_processadas,
                f"{total_processadas} fontes",
            ),
            renderizar_secao(
                2,
                "Fontes sem resultado",
                fontes_sem_resultado,
                f"{total_sem_resultado} fontes",
            ),
            renderizar_secao(
                3,
                "Fontes sem publicação",
                fontes_sem_publicacao,
                f"{total_sem_publicacao} fontes",
            ),
            renderizar_secao(
                4,
                "Erros técnicos",
                erros_tecnicos,
                f"{total_erros} fontes",
            ),
            renderizar_secao(
                5,
                "Fontes em defeso",
                fontes_defeso,
                f"{total_defeso} fontes",
            ),
            renderizar_secao(
                6,
                "Totais por Radar",
                renderizar_totais_por_radar(boletim, nomes),
            ),
            renderizar_secao(
                7,
                "Bloqueios do Filtro 1",
                bloqueios,
                f"{total_bloqueios} itens com bloqueio",
            ),
            renderizar_secao(
                8,
                "Itens bloqueados",
                itens_bloqueados,
                f"{total_itens_bloqueados} registros",
            ),
            renderizar_secao(
                9,
                "Rejeições por Radar",
                renderizar_rejeicoes_por_radar(boletim, nomes),
            ),
            renderizar_secao(
                10,
                "Principais palavras-chave",
                palavras_chave,
                f"{total_palavras} palavras ou expressões",
            ),
            renderizar_secao(
                11,
                "Itens sem classificação",
                itens_sem_classificacao,
                f"{total_sem_classificacao} itens",
            ),
            renderizar_secao(
                12,
                "Páginas de validação",
                renderizar_links_validacao(nomes),
                "9 páginas",
            ),
        ]
    )

    indice_titulos = [
        "Fontes processadas",
        "Fontes sem resultado",
        "Fontes sem publicação",
        "Erros técnicos",
        "Fontes em defeso",
        "Totais por Radar",
        "Bloqueios do Filtro 1",
        "Itens bloqueados",
        "Rejeições por Radar",
        "Principais palavras-chave",
        "Itens sem classificação",
        "Páginas de validação",
    ]

    indice = "".join(
        (f'<a href="#secao-{numero}">' f"{numero:02d}. {escapar(titulo)}</a>")
        for numero, titulo in enumerate(indice_titulos, 1)
    )

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Auditoria dos Radares</title>
  <style>
    :root {{
      --verde-escuro: {COR_VERDE_ESCURO};
      --verde-medio: {COR_VERDE_MEDIO};
      --verde-vibrante: {COR_VERDE_VIBRANTE};
      --verde-claro: {COR_VERDE_CLARO};
      --fundo: {COR_FUNDO};
      --card: {COR_CARD};
      --linha: {COR_LINHA};
      --texto: {COR_TEXTO};
      --texto-suave: {COR_TEXTO_SUAVE};
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--fundo);
      color: var(--texto);
      font-family: Arial, Helvetica, sans-serif;
    }}
    .pagina {{
      width: min(1180px, calc(100% - 32px));
      margin: 28px auto 52px;
    }}
    .cabecalho {{
      background: var(--verde-escuro);
      color: #ffffff;
      padding: 34px 38px;
      border-radius: 12px;
      box-shadow: 0 8px 24px rgba(13, 51, 32, 0.14);
    }}
    .cabecalho .rotulo {{
      color: var(--verde-claro);
      text-transform: uppercase;
      letter-spacing: 2px;
      font-size: 11px;
      font-weight: 700;
    }}
    .cabecalho h1 {{
      margin: 12px 0 10px;
      font-size: 32px;
      line-height: 1.15;
    }}
    .cabecalho p {{
      margin: 0;
      color: var(--verde-claro);
      font-size: 13px;
      line-height: 1.6;
    }}
    .barra {{
      width: 62px;
      height: 4px;
      margin-top: 20px;
      background: var(--verde-vibrante);
    }}
    .indice {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 9px;
      margin: 20px 0;
    }}
    .indice a {{
      display: block;
      padding: 11px 13px;
      color: var(--verde-escuro);
      background: #ffffff;
      border: 1px solid var(--linha);
      border-radius: 8px;
      font-size: 12px;
      font-weight: 700;
      text-decoration: none;
    }}
    .secao {{
      margin: 16px 0;
      overflow: hidden;
      background: var(--card);
      border: 1px solid var(--linha);
      border-radius: 10px;
      box-shadow: 0 2px 8px rgba(31, 41, 55, 0.04);
    }}
    .secao-cabecalho {{
      display: flex;
      gap: 14px;
      align-items: flex-start;
      padding: 19px 22px;
      background: #f8faf9;
      border-bottom: 1px solid var(--linha);
    }}
    .numero {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 38px;
      height: 30px;
      color: #ffffff;
      background: var(--verde-escuro);
      border-radius: 6px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 1px;
    }}
    .secao h2 {{
      margin: 0;
      color: var(--verde-escuro);
      font-size: 18px;
    }}
    .secao-resumo {{
      margin-top: 5px;
      color: var(--texto-suave);
      font-size: 11px;
    }}
    .secao-conteudo {{ padding: 18px 22px; }}
    .tabela-wrap {{ overflow-x: auto; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }}
    th {{
      padding: 10px;
      color: var(--verde-medio);
      background: #f5f8f6;
      border-bottom: 2px solid var(--verde-claro);
      text-align: left;
      white-space: nowrap;
    }}
    td {{
      padding: 10px;
      border-bottom: 1px solid var(--linha);
      line-height: 1.45;
      vertical-align: top;
    }}
    tbody tr:last-child td {{ border-bottom: 0; }}
    .curta {{ width: 150px; }}
    .numero-coluna {{ width: 110px; text-align: right; }}
    .vazio {{
      padding: 18px;
      color: var(--texto-suave);
      font-size: 12px;
      font-style: italic;
      text-align: center;
    }}
    .grade-links {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
      gap: 10px;
    }}
    .link-validacao {{
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding: 14px;
      color: var(--verde-escuro);
      background: #ffffff;
      border: 1px solid var(--linha);
      border-left: 4px solid var(--verde-vibrante);
      border-radius: 8px;
      text-decoration: none;
    }}
    .link-validacao span {{
      font-size: 12px;
      font-weight: 700;
      line-height: 1.35;
    }}
    .link-validacao small {{
      color: var(--texto-suave);
      font-size: 10px;
    }}
    .link-ausente {{
      border-left-color: {COR_ERRO};
      opacity: 0.72;
    }}
    .rodape {{
      margin-top: 24px;
      color: var(--texto-suave);
      font-size: 10px;
      letter-spacing: 0.5px;
      text-align: center;
    }}
  </style>
</head>
<body>
  <main class="pagina">
    <header class="cabecalho">
      <div class="rotulo">Auditoria consolidada</div>
      <h1>Auditoria dos Radares</h1>
      <p>Painel técnico da execução da curadoria automatizada.</p>
      <div class="barra"></div>
    </header>

    <nav class="indice" aria-label="Índice da auditoria">
      {indice}
    </nav>

    {secoes}

    <footer class="rodape">
      RADARES LOBO DE RIZZO &middot; AUDITORIA INTERNA
    </footer>
  </main>
</body>
</html>
"""


def salvar_atomico(caminho, conteudo):
    """Salva o HTML sem expor arquivo parcialmente gravado."""
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    temporario.write_text(conteudo, encoding="utf-8")
    os.replace(temporario, caminho)


def main():
    boletim = carregar_json(BOLETIM_PATH, "boletim.json")
    log = carregar_json(LOG_PATH, "log_execucao.json")

    if boletim.get("erro"):
        raise SystemExit(
            "ERRO: boletim.json registra falha de geração e não será auditado."
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    conteudo = montar_html(boletim, log)
    salvar_atomico(AUDITORIA_PATH, conteudo)

    print("Auditoria consolidada salva em: " + str(AUDITORIA_PATH))
    print("Nenhum arquivo email_<slug>.html foi criado ou alterado.")


if __name__ == "__main__":
    main()
