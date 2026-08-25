"""Gera a auditoria HTML dos Radares com métricas de cobertura consistentes."""

from collections import Counter
from html import escape
import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
BOLETIM_PATH = OUTPUT_DIR / "boletim.json"
LOG_PATH = OUTPUT_DIR / "log_execucao.json"
AUDITORIA_PATH = OUTPUT_DIR / "auditoria.html"


def escapar(valor):
    """Escapa HTML preservando valores válidos como 0 e False."""
    if valor is None:
        return ""
    return escape(str(valor), quote=True)


def sim_nao(valor):
    if valor is True:
        return "Sim"
    if valor is False:
        return "Não"
    return ""


def carregar_json(caminho):
    with caminho.open("r", encoding="utf-8") as arquivo:
        return json.load(arquivo)


def tabela(cabecalhos, linhas):
    if not linhas:
        return '<p class="empty">Nenhum registro.</p>'

    cabecalho = "".join(f"<th>{escapar(item)}</th>" for item in cabecalhos)
    corpo = []

    for linha in linhas:
        celulas = "".join(f"<td>{celula}</td>" for celula in linha)
        corpo.append(f"<tr>{celulas}</tr>")

    return (
        '<div class="table-wrap">'
        "<table>"
        f"<thead><tr>{cabecalho}</tr></thead>"
        f"<tbody>{''.join(corpo)}</tbody>"
        "</table>"
        "</div>"
    )


def secao(numero, titulo, conteudo, subtitulo=""):
    complemento = f"<small>{escapar(subtitulo)}</small>" if subtitulo else ""
    return (
        "<section>"
        "<header>"
        f"<b>{numero:02d}</b>"
        "<div>"
        f"<h2>{escapar(titulo)}</h2>"
        f"{complemento}"
        "</div>"
        "</header>"
        f'<div class="body">{conteudo}</div>'
        "</section>"
    )


def linhas_fontes_com_motivo(boletim, chave):
    linhas = []

    for registro in boletim.get(chave, []):
        if not isinstance(registro, dict):
            continue

        linhas.append(
            [
                escapar(registro.get("fonte")),
                escapar(registro.get("motivo")),
            ]
        )

    return linhas


def main():
    boletim = carregar_json(BOLETIM_PATH)
    log = carregar_json(LOG_PATH)

    config = boletim.get("boletins_config", {})
    nomes_radares = config.get("nomes_radares", {})
    itens = boletim.get("itens", [])
    validacoes = {
        registro.get("fonte"): registro
        for registro in boletim.get("validacao_fontes", [])
        if isinstance(registro, dict) and registro.get("fonte")
    }

    # Publicações confirmadas são itens identificados na janela, mesmo que depois
    # tenham sido rejeitados ou excluídos editorialmente.
    confirmadas_por_fonte = Counter(
        item.get("fonte", "")
        for item in itens
        if isinstance(item, dict) and item.get("fonte")
    )

    # Publicações aprovadas são apenas as que permaneceram em pelo menos um Radar.
    aprovadas_por_fonte = Counter(
        item.get("fonte", "")
        for item in itens
        if isinstance(item, dict)
        and item.get("fonte")
        and isinstance(item.get("boletins"), list)
        and len(item.get("boletins")) > 0
    )

    cobertura = []

    for registro in log.get("fontes_processadas", []):
        fonte = registro.get("fonte", "")
        validacao = validacoes.get(fonte, {})

        resultados_busca = validacao.get(
            "publicacoes_localizadas",
            registro.get("publicacoes_localizadas", 0),
        )

        cobertura.append(
            [
                escapar(fonte),
                escapar(registro.get("status")),
                escapar(registro.get("tamanho_chars", 0)),
                escapar(resultados_busca),
                escapar(confirmadas_por_fonte.get(fonte, 0)),
                escapar(aprovadas_por_fonte.get(fonte, 0)),
                escapar(validacao.get("status_editorial")),
                escapar(sim_nao(validacao.get("conteudo_truncado", False))),
            ]
        )

    fontes_suspensas = []
    for registro in config.get("fontes_em_defeso", []):
        if not isinstance(registro, dict):
            continue
        fontes_suspensas.append(
            [
                escapar(registro.get("fonte")),
                escapar(registro.get("motivo")),
                escapar(registro.get("reativar_em")),
            ]
        )

    totais_radares = []
    for slug, dados in boletim.get("estatisticas_por_boletim", {}).items():
        total = dados.get("total", 0) if isinstance(dados, dict) else dados
        totais_radares.append(
            [
                escapar(nomes_radares.get(slug, slug)),
                escapar(total),
            ]
        )

    bloqueios_por_radar = []
    for slug, quantidade in log.get("resultado", {}).get(
        "filtro1_bloqueios",
        {},
    ).items():
        bloqueios_por_radar.append(
            [
                escapar(nomes_radares.get(slug, slug)),
                escapar(quantidade),
            ]
        )

    itens_bloqueados = []
    for slug, titulos in log.get("filtro1_bloqueios_detalhe", {}).items():
        for titulo in titulos:
            itens_bloqueados.append(
                [
                    escapar(nomes_radares.get(slug, slug)),
                    escapar(titulo),
                ]
            )

    rejeicoes = []
    for slug, quantidade in boletim.get("auditoria", {}).get(
        "rejeicoes_por_boletim",
        {},
    ).items():
        rejeicoes.append(
            [
                escapar(nomes_radares.get(slug, slug)),
                escapar(quantidade),
            ]
        )

    palavras_chave = []
    for registro in boletim.get("auditoria", {}).get(
        "top_palavras_chave_detectadas",
        [],
    ):
        palavras_chave.append(
            [
                escapar(registro.get("palavra")),
                escapar(registro.get("ocorrencias", 0)),
            ]
        )

    sem_classificacao = []
    for item in itens:
        if not isinstance(item, dict) or item.get("boletins"):
            continue

        sem_classificacao.append(
            [
                escapar(item.get("fonte")),
                escapar(item.get("titulo")),
                escapar(item.get("exclusao_editorial_automatica")),
            ]
        )

    links = []
    for slug in config.get("boletins_disponiveis", []):
        nome = nomes_radares.get(slug, slug)
        links.append(
            f'<a href="validacao_{escapar(slug)}.html">{escapar(nome)}</a>'
        )

    secoes = [
        secao(
            1,
            "Cobertura por fonte",
            tabela(
                [
                    "Fonte",
                    "Coleta",
                    "Caracteres",
                    "Resultados da busca",
                    "Confirmadas na janela",
                    "Aprovadas nos Radares",
                    "Situação editorial",
                    "Truncada",
                ],
                cobertura,
            ),
            f"{len(cobertura)} fontes processadas",
        ),
        secao(
            2,
            "Fontes sem resultado",
            tabela(
                ["Fonte", "Motivo"],
                linhas_fontes_com_motivo(boletim, "fontes_sem_resultado"),
            ),
        ),
        secao(
            3,
            "Fontes sem publicação",
            tabela(
                ["Fonte", "Motivo"],
                linhas_fontes_com_motivo(
                    boletim,
                    "fontes_sem_publicacao_hoje",
                ),
            ),
        ),
        secao(
            4,
            "Erros técnicos",
            tabela(
                ["Fonte", "Motivo"],
                linhas_fontes_com_motivo(
                    boletim,
                    "fontes_com_erro_tecnico",
                ),
            ),
        ),
        secao(
            5,
            "Fontes em defeso",
            tabela(["Fonte", "Motivo", "Retomada"], fontes_suspensas),
        ),
        secao(
            6,
            "Totais por Radar",
            tabela(["Radar", "Total"], totais_radares),
        ),
        secao(
            7,
            "Bloqueios por Radar",
            tabela(["Radar", "Quantidade"], bloqueios_por_radar),
        ),
        secao(
            8,
            "Itens bloqueados",
            tabela(["Radar", "Item"], itens_bloqueados),
        ),
        secao(
            9,
            "Rejeições por Radar",
            tabela(["Radar", "Quantidade"], rejeicoes),
        ),
        secao(
            10,
            "Palavras-chave",
            tabela(["Palavra", "Ocorrências"], palavras_chave),
        ),
        secao(
            11,
            "Itens sem classificação",
            tabela(
                ["Fonte", "Item", "Exclusão automática"],
                sem_classificacao,
            ),
        ),
        secao(
            12,
            "Páginas de validação",
            f'<div class="links">{"".join(links)}</div>',
        ),
    ]

    estilos = """
        body {
            margin: 0;
            background: #f0f2f1;
            color: #1f2937;
            font-family: Arial, sans-serif;
        }
        main {
            max-width: 1280px;
            margin: 28px auto;
            padding: 0 16px;
        }
        .top {
            background: #0d3320;
            color: #ffffff;
            padding: 30px;
            border-radius: 10px;
        }
        section {
            background: #ffffff;
            margin: 16px 0;
            border: 1px solid #dddddd;
            border-radius: 9px;
            overflow: hidden;
        }
        section header {
            display: flex;
            gap: 12px;
            align-items: center;
            padding: 14px 20px;
            background: #f8faf9;
        }
        section header b {
            background: #0d3320;
            color: #ffffff;
            padding: 8px;
            border-radius: 5px;
        }
        h2 {
            margin: 0;
            font-size: 18px;
        }
        small {
            color: #6b7280;
        }
        .body {
            padding: 18px;
        }
        .table-wrap {
            overflow-x: auto;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
        }
        th,
        td {
            text-align: left;
            padding: 9px;
            border-bottom: 1px solid #e5e7eb;
            vertical-align: top;
        }
        th {
            color: #1a4d2e;
            background: #f5f8f6;
            white-space: nowrap;
        }
        .links {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 8px;
        }
        .links a {
            padding: 12px;
            border-left: 4px solid #22c55e;
            color: #0d3320;
            text-decoration: none;
            background: #f8faf9;
        }
        .empty {
            color: #6b7280;
            text-align: center;
        }
    """

    documento = f"""<!doctype html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width">
    <title>Auditoria dos Radares</title>
    <style>{estilos}</style>
</head>
<body>
    <main>
        <div class="top">
            <h1>Auditoria dos Radares</h1>
            <p>Cobertura, coleta e classificação editorial.</p>
        </div>
        {''.join(secoes)}
    </main>
</body>
</html>
"""

    AUDITORIA_PATH.write_text(documento, encoding="utf-8")
    print(f"Auditoria gerada em: {AUDITORIA_PATH}")


if __name__ == "__main__":
    main()
