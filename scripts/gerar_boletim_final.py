"""
Gera os nove Radares finais em HTML após a revisão no portal.

Entradas:
- output/boletim.json
- output/decisoes_alice.json

Saídas:
- output/email_<slug>.html
- output/resumo_geracao_final.json

Princípios:
- mantém os nove slugs técnicos;
- não publica itens sem decisão aprovada;
- aceita edições de título, resumo, URL, fonte, data e Radares;
- ignora itens rejeitados;
- não exibe metadados técnicos de IA, filtros ou auditoria;
- não sobrescreve e-mails finais se o arquivo de decisões estiver ausente,
  inválido ou não representar uma revisão concluída;
- grava os arquivos de forma atômica.
"""

import datetime
import html
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
BOLETIM_PATH = OUTPUT_DIR / "boletim.json"
DECISOES_PATH = OUTPUT_DIR / "decisoes_alice.json"
RESUMO_PATH = OUTPUT_DIR / "resumo_geracao_final.json"

SLUGS = [
    "trabalhista-empresarial",
    "direito-tributario",
    "societario-ma",
    "mercado-capitais-fundos",
    "regulatorio-oleo-gas",
    "imobiliario-infraestrutura",
    "ambiental-esg",
    "propriedade-intelectual",
    "contencioso-civel",
]

NOMES_PADRAO = {
    "trabalhista-empresarial": "Radar Trabalhista Empresarial",
    "direito-tributario": "Radar Tributário",
    "societario-ma": "Radar Societário, Fusões e Aquisições",
    "mercado-capitais-fundos": "Radar Mercado de Capitais e Fundos de Investimento",
    "regulatorio-oleo-gas": "Radar Regulatório e Óleo e Gás",
    "imobiliario-infraestrutura": "Radar Negócios Imobiliários e Infraestrutura",
    "ambiental-esg": "Radar Ambiental e ESG",
    "propriedade-intelectual": (
        "Radar Propriedade Intelectual, Tecnologia e Privacidade"
    ),
    "contencioso-civel": "Radar Solução de Conflitos",
}

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

STATUS_APROVADOS = {
    "aprovado",
    "aprovada",
    "aprovar",
    "approved",
    "mantido",
    "mantida",
    "incluir",
    "incluido",
    "incluida",
    "publicar",
    "publicado",
    "publicada",
    "sim",
    "true",
    "1",
}

STATUS_REJEITADOS = {
    "rejeitado",
    "rejeitada",
    "rejeitar",
    "reprovado",
    "reprovada",
    "excluir",
    "excluido",
    "excluida",
    "remover",
    "descartado",
    "descartada",
    "não",
    "nao",
    "false",
    "0",
}

CAMPOS_STATUS = [
    "status",
    "decisao",
    "decisão",
    "acao",
    "ação",
    "resultado",
    "aprovado",
    "aprovada",
    "incluir",
    "publicar",
]

CAMPOS_IDENTIFICADOR = [
    "id",
    "item_id",
    "itemId",
    "id_item",
    "hash",
    "chave",
]

CAMPOS_LISTA_DECISOES = [
    "decisoes",
    "decisões",
    "itens",
    "items",
    "revisoes",
    "revisões",
]


def escapar(valor):
    if valor is None:
        return ""
    return html.escape(str(valor), quote=True)


def texto_limpo(valor):
    return " ".join(str(valor or "").split()).strip()


def normalizar_texto(valor):
    texto = texto_limpo(valor).lower()
    substituicoes = str.maketrans(
        "áàâãéêíóôõúüç",
        "aaaaeeiooouuc",
    )
    return texto.translate(substituicoes)


def slug_valido(valor):
    return texto_limpo(valor) in SLUGS


def lista_slugs(valor):
    if isinstance(valor, str):
        candidatos = re.split(r"[,;|]", valor)
    elif isinstance(valor, list):
        candidatos = valor
    else:
        candidatos = []

    vistos = set()
    resultado = []

    for candidato in candidatos:
        slug = texto_limpo(candidato)
        if slug in SLUGS and slug not in vistos:
            vistos.add(slug)
            resultado.append(slug)

    return resultado


def url_segura(valor):
    url = texto_limpo(valor)
    if not url:
        return ""

    try:
        analisada = urlparse(url)
    except ValueError:
        return ""

    if analisada.scheme not in {"http", "https"} or not analisada.netloc:
        return ""

    return url


def carregar_json(caminho, nome):
    if not caminho.exists():
        raise SystemExit(f"ERRO: {nome} não encontrado em {caminho}")

    try:
        with caminho.open("r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
    except json.JSONDecodeError as erro:
        raise SystemExit(f"ERRO: {nome} contém JSON inválido: {erro}") from erro

    return dados


def escrever_texto_atomico(caminho, conteudo):
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    temporario.write_text(conteudo, encoding="utf-8")
    os.replace(temporario, caminho)


def escrever_json_atomico(caminho, dados):
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    temporario.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporario, caminho)


def extrair_lista_decisoes(dados):
    if isinstance(dados, list):
        return [item for item in dados if isinstance(item, dict)], {}

    if not isinstance(dados, dict):
        return [], {}

    for campo in CAMPOS_LISTA_DECISOES:
        valor = dados.get(campo)
        if isinstance(valor, list):
            return [item for item in valor if isinstance(item, dict)], dados

    # Compatibilidade com objeto indexado por ID/URL/título.
    candidatos = []
    for chave, valor in dados.items():
        if isinstance(valor, dict):
            copia = dict(valor)
            copia.setdefault("chave", chave)
            candidatos.append(copia)

    return candidatos, dados


def revisao_concluida(metadados, decisoes):
    """
    Bloqueia apenas marcações explícitas de revisão incompleta.

    Isso mantém compatibilidade com a versão antiga do portal, que pode não
    gravar um campo global de conclusão, sem permitir que um arquivo marcado
    como rascunho gere os e-mails finais.
    """
    campos = [
        "revisao_concluida",
        "revisão_concluída",
        "finalizado",
        "finalizada",
        "concluido",
        "concluida",
        "confirmado",
        "confirmada",
        "status_revisao",
        "status",
    ]

    for campo in campos:
        if campo not in metadados:
            continue

        valor = metadados.get(campo)
        if isinstance(valor, bool):
            return valor

        normalizado = normalizar_texto(valor)
        if normalizado in STATUS_APROVADOS | {
            "concluido",
            "concluida",
            "finalizado",
            "finalizada",
        }:
            return True
        if normalizado in STATUS_REJEITADOS | {
            "rascunho",
            "pendente",
            "em revisao",
            "aberto",
        }:
            return False

    return bool(decisoes)


def obter_status(decisao):
    for campo in CAMPOS_STATUS:
        if campo not in decisao:
            continue

        valor = decisao.get(campo)
        if isinstance(valor, bool):
            return "aprovado" if valor else "rejeitado"

        normalizado = normalizar_texto(valor)
        if normalizado in STATUS_APROVADOS:
            return "aprovado"
        if normalizado in STATUS_REJEITADOS:
            return "rejeitado"

    return "indefinido"


def identificador_explicito(registro):
    for campo in CAMPOS_IDENTIFICADOR:
        valor = texto_limpo(registro.get(campo))
        if valor:
            return valor
    return ""


def chaves_item(item):
    chaves = set()

    identificador = identificador_explicito(item)
    if identificador:
        chaves.add("id:" + identificador)

    url = url_segura(item.get("url") or item.get("link"))
    if url:
        chaves.add("url:" + url.rstrip("/"))

    fonte = normalizar_texto(item.get("fonte"))
    titulo = normalizar_texto(item.get("titulo"))
    if fonte or titulo:
        chaves.add("fonte_titulo:" + fonte + "||" + titulo)
    if titulo:
        chaves.add("titulo:" + titulo)

    return chaves


def chaves_decisao(decisao):
    chaves = set()

    identificador = identificador_explicito(decisao)
    if identificador:
        chaves.add("id:" + identificador)

    url = url_segura(
        decisao.get("url")
        or decisao.get("link")
        or decisao.get("url_original")
    )
    if url:
        chaves.add("url:" + url.rstrip("/"))

    fonte = normalizar_texto(
        decisao.get("fonte")
        or decisao.get("fonte_original")
    )
    titulo = normalizar_texto(
        decisao.get("titulo")
        or decisao.get("titulo_original")
    )
    if fonte or titulo:
        chaves.add("fonte_titulo:" + fonte + "||" + titulo)
    if titulo:
        chaves.add("titulo:" + titulo)

    return chaves


def localizar_decisao(item, indice):
    candidatos = []

    for chave in chaves_item(item):
        candidatos.extend(indice.get(chave, []))

    unicos = []
    vistos = set()

    for candidato in candidatos:
        marcador = id(candidato)
        if marcador not in vistos:
            vistos.add(marcador)
            unicos.append(candidato)

    if len(unicos) == 1:
        return unicos[0]

    # Em caso de colisão de títulos, prioriza URL, depois fonte+título.
    url_item = url_segura(item.get("url") or item.get("link")).rstrip("/")
    if url_item:
        correspondencias = [
            decisao
            for decisao in unicos
            if url_segura(
                decisao.get("url")
                or decisao.get("link")
                or decisao.get("url_original")
            ).rstrip("/")
            == url_item
        ]
        if len(correspondencias) == 1:
            return correspondencias[0]

    fonte = normalizar_texto(item.get("fonte"))
    titulo = normalizar_texto(item.get("titulo"))
    correspondencias = [
        decisao
        for decisao in unicos
        if normalizar_texto(
            decisao.get("fonte") or decisao.get("fonte_original")
        )
        == fonte
        and normalizar_texto(
            decisao.get("titulo") or decisao.get("titulo_original")
        )
        == titulo
    ]

    return correspondencias[0] if len(correspondencias) == 1 else None


def primeiro_valor(registro, campos):
    for campo in campos:
        valor = registro.get(campo)
        if valor not in (None, "", []):
            return valor
    return None


def aplicar_edicoes(item, decisao):
    atualizado = dict(item)

    mapeamentos = {
        "titulo": ["titulo_editado", "titulo_final", "novo_titulo", "titulo"],
        "resumo": ["resumo_editado", "resumo_final", "novo_resumo", "resumo"],
        "fonte": ["fonte_editada", "fonte_final", "fonte"],
        "url": ["url_editada", "url_final", "link", "url"],
        "data_publicacao": [
            "data_publicacao_editada",
            "data_publicacao_final",
            "data_publicacao",
            "data",
        ],
    }

    for destino, campos in mapeamentos.items():
        valor = primeiro_valor(decisao, campos)
        if valor is None:
            continue

        if destino == "url":
            valor = url_segura(valor)
            if not valor:
                continue
        else:
            valor = texto_limpo(valor)

        atualizado[destino] = valor

    radares = primeiro_valor(
        decisao,
        [
            "boletins_finais",
            "radares_finais",
            "boletins",
            "radares",
            "radar_final",
            "boletim_final",
        ],
    )
    radares_normalizados = lista_slugs(radares)

    if radares is not None:
        atualizado["boletins"] = radares_normalizados

    return atualizado


def aplicar_decisoes(itens_originais, decisoes):
    indice = defaultdict(list)

    for decisao in decisoes:
        for chave in chaves_decisao(decisao):
            indice[chave].append(decisao)

    aprovados = []
    rejeitados = 0
    sem_decisao = []
    decisoes_sem_item = set(range(len(decisoes)))
    mapa_indices = {id(decisao): indice for indice, decisao in enumerate(decisoes)}

    for item in itens_originais:
        decisao = localizar_decisao(item, indice)

        if decisao is None:
            sem_decisao.append(
                {
                    "fonte": item.get("fonte", ""),
                    "titulo": item.get("titulo", ""),
                    "url": item.get("url", ""),
                }
            )
            continue

        decisoes_sem_item.discard(mapa_indices[id(decisao)])
        status = obter_status(decisao)

        if status == "rejeitado":
            rejeitados += 1
            continue

        if status != "aprovado":
            sem_decisao.append(
                {
                    "fonte": item.get("fonte", ""),
                    "titulo": item.get("titulo", ""),
                    "url": item.get("url", ""),
                    "motivo": "Decisão sem status reconhecido",
                }
            )
            continue

        atualizado = aplicar_edicoes(item, decisao)
        atualizado["boletins"] = lista_slugs(atualizado.get("boletins", []))

        if not atualizado["boletins"]:
            sem_decisao.append(
                {
                    "fonte": atualizado.get("fonte", ""),
                    "titulo": atualizado.get("titulo", ""),
                    "url": atualizado.get("url", ""),
                    "motivo": "Item aprovado sem Radar final",
                }
            )
            continue

        aprovados.append(atualizado)

    decisoes_orfas = [decisoes[indice] for indice in sorted(decisoes_sem_item)]

    return aprovados, rejeitados, sem_decisao, decisoes_orfas


def remover_duplicados(itens):
    resultado = []
    vistos = set()

    for item in itens:
        url = url_segura(item.get("url")).rstrip("/")
        titulo = normalizar_texto(item.get("titulo"))
        fonte = normalizar_texto(item.get("fonte"))
        chave = url or (fonte + "||" + titulo)

        if not chave or chave in vistos:
            continue

        vistos.add(chave)
        resultado.append(item)

    return resultado


def agrupar_por_radar(itens):
    agrupados = {slug: [] for slug in SLUGS}

    for item in itens:
        for slug in lista_slugs(item.get("boletins", [])):
            agrupados[slug].append(item)

    for slug in SLUGS:
        agrupados[slug] = remover_duplicados(agrupados[slug])
        agrupados[slug].sort(
            key=lambda item: (
                str(item.get("data_publicacao", "")),
                normalizar_texto(item.get("fonte", "")),
                normalizar_texto(item.get("titulo", "")),
            ),
            reverse=True,
        )

    return agrupados


def formatar_data_curta(valor):
    try:
        data = datetime.date.fromisoformat(str(valor)[:10])
        return data.strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return texto_limpo(valor)


def formatar_data_extenso(valor):
    try:
        data = datetime.date.fromisoformat(str(valor)[:10])
        return f"{data.day} de {MESES_PT[data.month - 1]} de {data.year}"
    except (TypeError, ValueError):
        return texto_limpo(valor)


def renderizar_item(item):
    titulo = escapar(texto_limpo(item.get("titulo")) or "Sem título")
    resumo = escapar(texto_limpo(item.get("resumo")))
    fonte = escapar(texto_limpo(item.get("fonte")) or "Fonte não informada")
    data = escapar(formatar_data_curta(item.get("data_publicacao")))
    url = url_segura(item.get("url"))

    if url:
        link = (
            f'<a href="{escapar(url)}" '
            'style="color:#0d3320;text-decoration:none;font-weight:600;">'
            "Acessar publicação &raquo;</a>"
        )
    else:
        link = '<span style="color:#6b7280;">Link não informado</span>'

    resumo_html = (
        f'<p style="margin:8px 0 12px;color:#4a4a4a;font-size:14px;'
        f'line-height:1.55;">{resumo}</p>'
        if resumo
        else ""
    )

    return f"""
    <tr>
      <td style="padding:0 24px 14px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
               style="border-collapse:collapse;background:#ffffff;border-left:4px solid #1a4d2e;">
          <tr>
            <td style="padding:16px 18px;border:1px solid #e5e7eb;border-left:0;">
              <div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;">
                {fonte}
              </div>
              <h2 style="margin:7px 0 0;color:#1a1a1a;font-size:16px;line-height:1.35;font-weight:600;">
                {titulo}
              </h2>
              {resumo_html}
              <div style="padding-top:9px;border-top:1px solid #eeeeee;font-size:12px;color:#6b7280;">
                <strong>Publicado:</strong> {data or "Data não informada"}
                &nbsp;&nbsp; {link}
              </div>
            </td>
          </tr>
        </table>
      </td>
    </tr>
    """


def renderizar_html(nome_radar, data_extenso, itens):
    itens_html = "".join(renderizar_item(item) for item in itens)

    if not itens_html:
        itens_html = """
        <tr>
          <td style="padding:40px 24px;text-align:center;color:#6b7280;font-size:14px;">
            Nenhum item aprovado para este Radar nesta edição.
          </td>
        </tr>
        """

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escapar(nome_radar)} - Lobo de Rizzo Advogados</title>
</head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:Segoe UI,Arial,sans-serif;color:#2c3e50;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
         style="border-collapse:collapse;background:#f0f2f5;">
    <tr>
      <td align="center" style="padding:20px 8px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
               style="max-width:780px;border-collapse:collapse;background:#ffffff;">
          <tr>
            <td style="padding:32px 28px;background:#0d3320;color:#ffffff;">
              <div style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#a8d8b9;">
                Radares Lobo de Rizzo
              </div>
              <h1 style="margin:8px 0 7px;font-size:28px;line-height:1.2;font-weight:300;">
                {escapar(nome_radar)}
              </h1>
              <div style="font-size:13px;color:#a8d8b9;">{escapar(data_extenso)}</div>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 24px 8px;color:#4a4a4a;font-size:14px;line-height:1.55;">
              Confira as atualizações selecionadas para esta edição.
            </td>
          </tr>
          {itens_html}
          <tr>
            <td style="padding:18px 24px;background:#0d3320;color:#a8d8b9;text-align:center;font-size:11px;">
              RADARES LOBO DE RIZZO
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def main():
    print("=" * 60)
    print("Gerador dos Radares finais pós-curadoria")
    print("=" * 60)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    boletim = carregar_json(BOLETIM_PATH, "boletim.json")
    decisoes_brutas = carregar_json(DECISOES_PATH, "decisoes_alice.json")

    if not isinstance(boletim, dict) or not isinstance(boletim.get("itens"), list):
        raise SystemExit("ERRO: boletim.json não contém a lista válida de itens.")

    decisoes, metadados = extrair_lista_decisoes(decisoes_brutas)

    if not decisoes:
        raise SystemExit(
            "ERRO: decisoes_alice.json não contém decisões reconhecíveis. "
            "Os e-mails finais foram preservados."
        )

    if not revisao_concluida(metadados, decisoes):
        raise SystemExit(
            "ERRO: a revisão está marcada como pendente ou incompleta. "
            "Os e-mails finais foram preservados."
        )

    aprovados, rejeitados, sem_decisao, decisoes_orfas = aplicar_decisoes(
        boletim["itens"],
        decisoes,
    )

    if sem_decisao:
        resumo = {
            "status": "bloqueado_por_itens_sem_decisao",
            "total_itens_boletim": len(boletim["itens"]),
            "total_decisoes": len(decisoes),
            "itens_sem_decisao": sem_decisao,
            "decisoes_sem_item_correspondente": decisoes_orfas,
            "arquivos_finais_preservados": True,
        }
        escrever_json_atomico(RESUMO_PATH, resumo)
        raise SystemExit(
            "ERRO: há itens sem decisão final reconhecida. "
            "Consulte output/resumo_geracao_final.json. "
            "Os e-mails finais foram preservados."
        )

    agrupados = agrupar_por_radar(aprovados)
    config = boletim.get("boletins_config", {})
    nomes = config.get("nomes_radares", {}) if isinstance(config, dict) else {}
    nomes = {**NOMES_PADRAO, **nomes}
    data_edicao = boletim.get("data_execucao") or datetime.date.today().isoformat()
    data_extenso = formatar_data_extenso(data_edicao)

    arquivos_gerados = []

    for slug in SLUGS:
        nome_radar = nomes.get(slug, NOMES_PADRAO[slug])
        conteudo = renderizar_html(
            nome_radar,
            data_extenso,
            agrupados[slug],
        )
        caminho = OUTPUT_DIR / f"email_{slug}.html"
        escrever_texto_atomico(caminho, conteudo)
        arquivos_gerados.append(
            {
                "slug": slug,
                "nome": nome_radar,
                "arquivo": caminho.name,
                "total_itens": len(agrupados[slug]),
            }
        )
        print(f"Gerado: {caminho.name} ({len(agrupados[slug])} itens)")

    resumo = {
        "status": "sucesso",
        "data_execucao": datetime.datetime.now().astimezone().isoformat(),
        "data_edicao": data_edicao,
        "total_itens_boletim": len(boletim["itens"]),
        "total_decisoes": len(decisoes),
        "total_aprovados": len(aprovados),
        "total_rejeitados": rejeitados,
        "decisoes_sem_item_correspondente": decisoes_orfas,
        "arquivos_gerados": arquivos_gerados,
    }
    escrever_json_atomico(RESUMO_PATH, resumo)

    print("=" * 60)
    print(f"Itens aprovados: {len(aprovados)}")
    print(f"Itens rejeitados: {rejeitados}")
    print(f"Radares gerados: {len(arquivos_gerados)}")
    print(f"Resumo: {RESUMO_PATH}")
    print("Concluído")


if __name__ == "__main__":
    main()
