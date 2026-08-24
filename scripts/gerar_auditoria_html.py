"""
Gera um painel HTML consolidado de auditoria dos Radares.

Entradas:
- output/boletim.json
- output/log_execucao.json

Saida exclusiva:
- output/auditoria.html

O painel contem somente:
1. fontes processadas;
2. fontes sem resultado;
3. fontes sem publicacao;
4. erros tecnicos;
5. fontes em defeso;
6. totais por Radar;
7. bloqueios do Filtro 1;
8. itens bloqueados;
9. rejeicoes por Radar;
10. principais palavras-chave;
11. itens sem classificacao;
12. links para as nove paginas de validacao.
"""

import datetime
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
    "mercado-capitais-fundos": "Radar Mercado de Capitais e Fundos de Investimento",
    "regulatorio-oleo-gas": "Radar Regulatório e Óleo e Gás",
    "imobiliario-infraestrutura": "Radar Negócios Imobiliários e Infraestrutura",
    "ambiental-esg": "Radar Ambiental e ESG",
    "propriedade-intelectual": "Radar Propriedade Intelectual, Tecnologia e Privacidade",
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
COR_ALERTA = "#d97706"
COR_ERRO = "#b91c1c"
COR_INFO = "#2563eb"


def escapar(valor):
    if valor is None:
        return ""
    return html.escape(str(valor), quote=True)


def carregar_json(caminho, nome):
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


def normalizar_lista_fontes(valor, motivo_padrao=""):
    resultado = []
    if not isinstance(valor, list):
        return resultado
    for item in valor:
        if isinstance(item, dict):
            fonte = str(item.get("fonte", "")).strip()
            motivo = str(item.get("motivo", motivo_padrao)).strip()
        elif isinstance(item, str):
            fonte = item.strip()
            motivo = motivo_padrao
        else:
            continue
        if fonte:
            resultado.append({"fonte": fonte, "motivo": motivo})
    return resultado


def formatar_data(valor):
    try:
        data = datetime.date.fromisoformat(str(valor)[:10])
        return data.strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(valor or "")


def nome_radar(slug, nomes):
    return nomes.get(slug, NOMES_RADARES_PADRAO.get(slug, slug))


def bloco_vazio(mensagem):
    return (
        '<div class="vazio">'
        + escapar(mensagem)
        + "</div>"
    )


def renderizar_tabela(cabecalhos, linhas, classes_colunas=None):
    if not linhas:
        return bloco_vazio("Nenhum registro nesta categoria.")
    classes_colunas = classes_colunas or [""] * len(cabecalhos)
    cabecalho = "".join(
        f'<th class="{escapar(classes_colunas[i])}">{escapar(titulo)}</th>'
        for i, titulo in enumerate(cabecalhos)
    )
    corpo = []
    for linha in linhas:
        celulas = "".join(
            f'<td class="{escapar(classes_colunas[i])}">{valor}</td>'
            for i, valor in enumerate(linha)
        )
        corpo.append(f"<tr>{celulas}</tr>")
    return (
        '<div class="tabela-wrap"><table><thead><tr>'
        + cabecalho
        + "</tr></thead><tbody>"
        + "".join(corpo)
        + "</tbody></table></div>"
    )


def renderizar_secao(numero, titulo, conteudo, resumo=""):
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
      <div class="secao-conteudo">{conteudo}</div>
    </section>
    """


def fontes_processadas(log):
    registros = log.get("fontes_processadas", [])
    linhas = []
    if isinstance(registros, list):
        for registro in registros:
            if not isinstance(registro, dict):
                continue
            fonte = escapar(registro.get("fonte", ""))
            status = escapar(registro.get("status", ""))
            tamanho = registro.get("tamanho_chars", "")
            tamanho_html = escapar(tamanho) if tamanho != "" else ""
            linhas.append([fonte, status, tamanho_html])
    return renderizar_tabela(
        ["Fonte", "Status", "Caracteres"],
        linhas,
        ["", "curta", "numero-coluna"],
    ), len(linhas)


def fontes_com_motivo(boletim, chave, motivo_padrao):
    registros = normalizar_lista_fontes(boletim.get(chave, []), motivo_padrao)
    linhas = [[escapar(r["fonte"]), escapar(r["motivo"])] for r in registros]
    return renderizar_tabela(["Fonte", "Motivo"], linhas), len(linhas)


def fontes_em_defeso(boletim, log):
    config = boletim.get("boletins_config", {})
    config = config if isinstance(config, dict) else {}
    origens = config.get("fontes_em_defeso", [])
    if not origens:
        origens = log.get("fontes_inativas_defeso", [])
    registros = normalizar_lista_fontes(origens)
    linhas = [[escapar(r["fonte"])] for r in registros]
    return renderizar_tabela(["Fonte"], linhas), len(linhas)


def totais_por_radar(boletim, nomes):
    estatisticas = boletim.get("estatisticas_por_boletim", {})
    estatisticas = estatisticas if isinstance(estatisticas, dict) else {}
    linhas = []
    for slug in ORDEM_RADARES:
        dados = estatisticas.get(slug, {})
        if isinstance(dados, dict):
            total = dados.get("total", 0)
        else:
            total = dados if isinstance(dados, int) else 0
        linhas.append([escapar(nome_radar(slug, nomes)), escapar(total)])
    return renderizar_tabela(["Radar", "Total"], linhas, ["", "numero-coluna"])


def bloqueios_filtro_1(boletim, log, nomes):
    auditoria = boletim.get("auditoria", {})
    auditoria = auditoria if isinstance(auditoria, dict) else {}
    total = auditoria.get("itens_com_bloqueio_f1", 0)
    por_radar = log.get("resultado", {}).get("filtro1_bloqueios", {})
    por_radar = por_radar if isinstance(por_radar, dict) else {}
    linhas = []
    for slug in ORDEM_RADARES:
        qtd = por_radar.get(slug, 0)
        if qtd:
            linhas.append([escapar(nome_radar(slug, nomes)), escapar(qtd)])
    conteudo = renderizar_tabela(["Radar bloqueado", "Quantidade"], linhas, ["", "numero-coluna"])
    return conteudo, total


def itens_bloqueados(log, nomes):
    detalhes = log.get("filtro1_bloqueios_detalhe", {})
    detalhes = detalhes if isinstance(detalhes, dict) else {}
    linhas = []
    for slug in ORDEM_RADARES:
        titulos = detalhes.get(slug, [])
        if not isinstance(titulos, list):
            continue
        for titulo in titulos:
            linhas.append([escapar(nome_radar(slug, nomes)), escapar(titulo)])
    return renderizar_tabela(["Radar bloqueado", "Item"], linhas), len(linhas)


def rejeicoes_por_radar(boletim, nomes):
    auditoria = boletim.get("auditoria", {})
    auditoria = auditoria if isinstance(auditoria, dict) else {}
    rejeicoes = auditoria.get("rejeicoes_por_boletim", {})
    rejeicoes = rejeicoes if isinstance(rejeicoes, dict) else {}
    linhas = []
    for slug in ORDEM_RADARES:
        qtd = rejeicoes.get(slug, 0)
        linhas.append([escapar(nome_radar(slug, nomes)), escapar(qtd)])
    return renderizar_tabela(["Radar", "Rejeições"], linhas, ["", "numero-coluna"])


def principais_palavras_chave(boletim):
    auditoria = boletim.get("auditoria", {})
    auditoria = auditoria if isinstance(auditoria, dict) else {}
    palavras = auditoria.get("top_palavras_chave_detectadas", [])
    linhas = []
    if isinstance(palavras, list):
        for item in palavras:
            if not isinstance(item, dict):
                continue
            linhas.append([
                escapar(item.get("palavra", "")),
                escapar(item.get("ocorrencias", 0)),
            ])
    return renderizar_tabela(["Palavra-chave", "Ocorrências"], linhas, ["", "numero-coluna"]), len(linhas)


def itens_sem_classificacao(boletim):
    itens = boletim.get("itens", [])
    linhas = []
    if isinstance(itens, list):
        for item in itens:
            if not isinstance(item, dict):
                continue
            boletins = item.get("boletins", [])
            if not isinstance(boletins, list) or not boletins:
                linhas.append([
                    escapar(item.get("fonte", "")),
                    escapar(item.get("titulo", "")),
                    escapar(formatar_data(item.get("data_publicacao", ""))),
                ])
    return renderizar_tabela(["Fonte", "Item", "Data"], linhas, ["", "", "curta"]), len(linhas)


def links_validacao(nomes):
    cards = []
    for slug in ORDEM_RADARES:
        arquivo = f"validacao_{slug}.html"
        caminho = OUTPUT_DIR / arquivo
        estado = "Disponível" if caminho.exists() else "Arquivo não encontrado"
        classe = "link-ok" if caminho.exists() else "link-ausente"
        cards.append(f"""
        <a class="link-validacao {classe}" href="{escapar(arquivo)}">
          <span>{escapar(nome_radar(slug, nomes))}</span>
          <small>{escapar(estado)}</small>
        </a>
        """)
    return '<div class="grade-links">' + "".join(cards) + "</div>"


def montar_html(boletim, log):
    config = boletim.get("boletins_config", {})
    config = config if isinstance(config, dict) else {}
    nomes = config.get("nomes_radares", {})
    nomes = nomes if isinstance(nomes, dict) else {}

    secao_1, total_processadas = fontes_processadas(log)
    secao_2, total_sem_resultado = fontes_com_motivo(
        boletim,
        "fontes_sem_resultado",
        "A página foi acessada, mas não foi possível identificar conteúdo utilizável.",
    )
    secao_3, total_sem_publicacao = fontes_com_motivo(
        boletim,
        "fontes_sem_publicacao_hoje",
        "Nenhuma publicação foi identificada dentro da janela.",
    )
    secao_4, total_erros = fontes_com_motivo(
        boletim,
        "fontes_com_erro_tecnico",
        "Erro técnico informado durante a coleta.",
    )
    secao_5, total_defeso = fontes_em_defeso(boletim, log)
    secao_7, total_bloqueios = bloqueios_filtro_1(boletim, log, nomes)
    secao_8, total_itens_bloqueados = itens_bloqueados(log, nomes)
    secao_10, total_palavras = principais_palavras_chave(boletim)
    secao_11, total_sem_classificacao = itens_sem_classificacao(boletim)

    secoes = "".join([
        renderizar_secao(1, "Fontes processadas", secao_1, f"{total_processadas} fontes"),
        renderizar_secao(2, "Fontes sem resultado", secao_2, f"{total_sem_resultado} fontes"),
        renderizar_secao(3, "Fontes sem publicação", secao_3, f"{total_sem_publicacao} fontes"),
        renderizar_secao(4, "Erros técnicos", secao_4, f"{total_erros} fontes"),
        renderizar_secao(5, "Fontes em defeso", secao_5, f"{total_defeso} fontes"),
        renderizar_secao(6, "Totais por Radar", totais_por_radar(boletim, nomes)),
        renderizar_secao(7, "Bloqueios do Filtro 1", secao_7, f"{total_bloqueios} itens com bloqueio"),
        renderizar_secao(8, "Itens bloqueados", secao_8, f"{total_itens_bloqueados} registros"),
        renderizar_secao(9, "Rejeições por Radar", rejeicoes_por_radar(boletim, nomes)),
        renderizar_secao(10, "Principais palavras-chave", secao_10, f"{total_palavras} palavras ou expressões"),
        renderizar_secao(11, "Itens sem classificação", secao_11, f"{total_sem_classificacao} itens"),
        renderizar_secao(12, "Páginas de validação", links_validacao(nomes), "9 páginas"),
    ])

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
    body {{ margin:0; background:var(--fundo); color:var(--texto); font-family:Arial,Helvetica,sans-serif; }}
    .pagina {{ width:min(1180px, calc(100% - 32px)); margin:28px auto 52px; }}
    .cabecalho {{ background:var(--verde-escuro); color:#fff; padding:34px 38px; border-radius:12px; box-shadow:0 8px 24px rgba(13,51,32,.14); }}
    .cabecalho .rotulo {{ color:var(--verde-claro); text-transform:uppercase; letter-spacing:2px; font-size:11px; font-weight:700; }}
    .cabecalho h1 {{ margin:12px 0 10px; font-size:32px; line-height:1.15; }}
    .cabecalho p {{ margin:0; max-width:760px; color:var(--verde-claro); font-size:13px; line-height:1.6; }}
    .barra {{ width:62px; height:4px; background:var(--verde-vibrante); margin-top:20px; }}
    .indice {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:9px; margin:20px 0; }}
    .indice a {{ display:block; background:#fff; border:1px solid var(--linha); border-radius:8px; padding:11px 13px; color:var(--verde-escuro); text-decoration:none; font-size:12px; font-weight:700; }}
    .indice a:hover {{ border-color:var(--verde-vibrante); }}
    .secao {{ background:var(--card); border:1px solid var(--linha); border-radius:10px; margin:16px 0; overflow:hidden; box-shadow:0 2px 8px rgba(31,41,55,.04); }}
    .secao-cabecalho {{ display:flex; gap:14px; align-items:flex-start; padding:19px 22px; border-bottom:1px solid var(--linha); background:#f8faf9; }}
    .numero {{ display:inline-flex; align-items:center; justify-content:center; min-width:38px; height:30px; border-radius:6px; background:var(--verde-escuro); color:#fff; font-size:11px; font-weight:700; letter-spacing:1px; }}
    .secao h2 {{ margin:0; color:var(--verde-escuro); font-size:18px; }}
    .secao-resumo {{ margin-top:5px; color:var(--texto-suave); font-size:11px; }}
    .secao-conteudo {{ padding:18px 22px; }}
    .tabela-wrap {{ overflow-x:auto; }}
    table {{ width:100%; border-collapse:collapse; font-size:12px; }}
    th {{ text-align:left; color:var(--verde-medio); background:#f5f8f6; border-bottom:2px solid var(--verde-claro); padding:10px; white-space:nowrap; }}
    td {{ padding:10px; border-bottom:1px solid var(--linha); vertical-align:top; line-height:1.45; }}
    tbody tr:last-child td {{ border-bottom:0; }}
    .curta {{ width:150px; }}
    .numero-coluna {{ width:110px; text-align:right; }}
    .vazio {{ color:var(--texto-suave); text-align:center; padding:18px; font-size:12px; font-style:italic; }}
    .grade-links {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:10px; }}
    .link-validacao {{ display:flex; flex-direction:column; gap:6px; border:1px solid var(--linha); border-left:4px solid var(--verde-vibrante); border-radius:8px; padding:14px; color:var(--verde-escuro); text-decoration:none; background:#fff; }}
    .link-validacao span {{ font-size:12px; font-weight:700; line-height:1.35; }}
    .link-validacao small {{ color:var(--texto-suave); font-size:10px; }}
    .link-ausente {{ border-left-color:{COR_ERRO}; opacity:.72; }}
    .rodape {{ text-align:center; color:var(--texto-suave); font-size:10px; letter-spacing:.5px; margin-top:24px; }}
    @media (max-width:700px) {{
      .pagina {{ width:min(100% - 18px, 1180px); margin-top:10px; }}
      .cabecalho {{ padding:25px 22px; border-radius:8px; }}
      .cabecalho h1 {{ font-size:25px; }}
      .secao-cabecalho, .secao-conteudo {{ padding:15px; }}
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
      {''.join(f'<a href="#secao-{n}">{n:02d}. {escapar(t)}</a>' for n, t in enumerate([
          'Fontes processadas', 'Fontes sem resultado', 'Fontes sem publicação',
          'Erros técnicos', 'Fontes em defeso', 'Totais por Radar',
          'Bloqueios do Filtro 1', 'Itens bloqueados', 'Rejeições por Radar',
          'Principais palavras-chave', 'Itens sem classificação',
          'Páginas de validação'
      ], 1))}
    </nav>
    {secoes}
    <footer class="rodape">RADARES LOBO DE RIZZO &middot; AUDITORIA INTERNA</footer>
  </main>
</body>
</html>
"""


def salvar_atomico(caminho, conteudo):
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    temporario.write_text(conteudo, encoding="utf-8")
    os.replace(temporario, caminho)


def main():
    boletim = carregar_json(BOLETIM_PATH, "boletim.json")
    log = carregar_json(LOG_PATH, "log_execucao.json")
    if boletim.get("erro"):
        raise SystemExit("ERRO: boletim.json registra falha de geração e não será auditado.")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    conteudo = montar_html(boletim, log)
    salvar_atomico(AUDITORIA_PATH, conteudo)
    print("Auditoria consolidada salva em: " + str(AUDITORIA_PATH))
    print("Nenhum arquivo email_<slug>.html foi criado ou alterado.")


if __name__ == "__main__":
    main()
