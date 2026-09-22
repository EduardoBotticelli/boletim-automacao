"""
Gera os nove Radares finais em HTML após a revisão no portal.

Entradas:
- output/boletim.json
- output/decisoes_alice.json
- templates/Template_Radar *.msg (templates oficiais do Marketing)
- templates/mapeamento_radares.json

Saídas:
- output/email_<slug>.eml (mensagem pronta para envio, corpo do template)
- output/email_<slug>.html (mesma edição, para conferência no navegador)
- output/recursos_radar/ (imagens dos templates)
- output/resumo_geracao_final.json

Princípios:
- mantém os nove slugs técnicos;
- não publica itens sem decisão aprovada;
- aceita edições de título, resumo, URL, fonte, data e Radares;
- publica itens adicionados manualmente no portal, que chegam com o conteúdo
  embutido na própria decisão por não existirem no boletim.json;
- ignora itens rejeitados;
- não exibe metadados técnicos de IA, filtros ou auditoria;
- usa integralmente o template oficial de cada Radar: o HTML não é recriado
  aqui, apenas preenchido (ver scripts/templates_radar.py);
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

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ajustes_templates
import templates_radar


BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
TEMPLATES_DIR = BASE_DIR / "templates"
MAPEAMENTO_PATH = TEMPLATES_DIR / "mapeamento_radares.json"
BOLETIM_PATH = OUTPUT_DIR / "boletim.json"
DECISOES_PATH = OUTPUT_DIR / "decisoes_alice.json"
RESUMO_PATH = OUTPUT_DIR / "resumo_geracao_final.json"
RECURSOS_DIRNAME = "recursos_radar"

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
    # O portal classifica como "ajustado" o item aprovado cujos Radares foram
    # alterados na curadoria. Continua sendo uma aprovação.
    "ajustado",
    "ajustada",
    "editado",
    "editada",
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

# Onde procurar o conteúdo de um item adicionado manualmente no portal.
CAMPOS_ITEM_EMBUTIDO = [
    "noticia",
    "notícia",
    "item",
    "item_manual",
    "conteudo",
    "conteúdo",
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


def escrever_bytes_atomico(caminho, dados):
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    temporario.write_bytes(dados)
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


def extrair_item_embutido(decisao):
    """Devolve o conteúdo do item carregado dentro da própria decisão."""
    for campo in CAMPOS_ITEM_EMBUTIDO:
        valor = decisao.get(campo)
        if isinstance(valor, dict):
            return valor
    return {}


def decisao_e_manual(decisao):
    return normalizar_texto(decisao.get("origem")) == "manual"


def item_de_decisao(decisao):
    """
    Reconstrói um item a partir de uma decisão sem correspondente no
    boletim.json.

    É o caso dos itens que a curadoria adiciona manualmente no portal: eles
    nunca passaram pelo pipeline de coleta, então o texto só existe dentro da
    decisão. Devolve None quando a decisão não carrega conteúdo suficiente.
    """
    base = extrair_item_embutido(decisao)

    if not base and not decisao_e_manual(decisao):
        return None

    titulo = texto_limpo(base.get("titulo") or decisao.get("titulo"))
    if not titulo:
        return None

    return {
        "fonte": texto_limpo(base.get("fonte") or decisao.get("fonte")),
        "categoria": (
            texto_limpo(base.get("categoria") or decisao.get("categoria"))
            or "Adicionado manualmente"
        ),
        "titulo": titulo,
        "resumo": texto_limpo(base.get("resumo") or decisao.get("resumo")),
        "data_publicacao": texto_limpo(
            base.get("data_publicacao") or decisao.get("data_publicacao")
        ),
        "url": url_segura(base.get("url") or decisao.get("url")),
        "boletins": lista_slugs(base.get("boletins")),
        "origem": "manual",
    }


def resumo_do_item(item, motivo=None):
    registro = {
        "fonte": item.get("fonte", ""),
        "titulo": item.get("titulo", ""),
        "url": item.get("url", ""),
    }
    if motivo:
        registro["motivo"] = motivo
    return registro


def aplicar_decisoes(itens_originais, decisoes):
    indice = defaultdict(list)

    for decisao in decisoes:
        for chave in chaves_decisao(decisao):
            indice[chave].append(decisao)

    aprovados = []
    manuais = 0
    rejeitados = 0
    sem_decisao = []
    decisoes_sem_item = set(range(len(decisoes)))
    mapa_indices = {id(decisao): posicao for posicao, decisao in enumerate(decisoes)}

    for item in itens_originais:
        decisao = localizar_decisao(item, indice)

        if decisao is None:
            sem_decisao.append(resumo_do_item(item))
            continue

        decisoes_sem_item.discard(mapa_indices[id(decisao)])
        status = obter_status(decisao)

        if status == "rejeitado":
            rejeitados += 1
            continue

        if status != "aprovado":
            sem_decisao.append(
                resumo_do_item(item, "Decisão sem status reconhecido")
            )
            continue

        atualizado = aplicar_edicoes(item, decisao)
        atualizado["boletins"] = lista_slugs(atualizado.get("boletins", []))

        if not atualizado["boletins"]:
            sem_decisao.append(
                resumo_do_item(atualizado, "Item aprovado sem Radar final")
            )
            continue

        aprovados.append(atualizado)

    # Decisões que sobraram: ou são itens adicionados manualmente no portal
    # (e trazem o próprio conteúdo), ou não têm como ser publicadas.
    decisoes_orfas = []

    for posicao in sorted(decisoes_sem_item):
        decisao = decisoes[posicao]
        status = obter_status(decisao)

        if status == "rejeitado":
            rejeitados += 1
            continue

        item_manual = item_de_decisao(decisao)

        if item_manual is None:
            decisoes_orfas.append(decisao)
            continue

        if status != "aprovado":
            sem_decisao.append(
                resumo_do_item(item_manual, "Decisão sem status reconhecido")
            )
            continue

        atualizado = aplicar_edicoes(item_manual, decisao)
        atualizado["boletins"] = lista_slugs(atualizado.get("boletins", []))

        if not atualizado["boletins"]:
            sem_decisao.append(
                resumo_do_item(atualizado, "Item manual aprovado sem Radar final")
            )
            continue

        aprovados.append(atualizado)
        manuais += 1

    return aprovados, manuais, rejeitados, sem_decisao, decisoes_orfas


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


def carregar_mapeamento():
    """Lê templates/mapeamento_radares.json."""
    dados = carregar_json(MAPEAMENTO_PATH, "mapeamento_radares.json")

    if not isinstance(dados, dict) or not isinstance(dados.get("templates"), dict):
        raise SystemExit(
            "ERRO: mapeamento_radares.json não contém o mapa 'templates'."
        )

    faltando = [slug for slug in SLUGS if slug not in dados["templates"]]
    if faltando:
        raise SystemExit(
            "ERRO: mapeamento_radares.json não mapeia os Radares: "
            + ", ".join(faltando)
        )

    return dados


def resolver_secao(fonte, slug, secoes, aliases):
    """
    Descobre em qual seção do template uma notícia deve entrar.

    O nome da fonte no boletim.json tem a forma "Órgão | Seção". O template
    usa o nome do órgão. A comparação é feita sem acento e sem pontuação, e o
    que não casa sozinho é resolvido pelo 'aliases_fonte' do mapeamento.
    """
    rotulo = texto_limpo(fonte)

    # 1. Alias explícito no mapeamento.
    for chave, destinos in aliases.items():
        if not isinstance(destinos, dict):
            continue
        if templates_radar.normalizar(chave) == templates_radar.normalizar(
            rotulo.split("|")[0]
        ) or templates_radar.normalizar(chave) == templates_radar.normalizar(rotulo):
            ancora = destinos.get(slug)
            if ancora:
                for secao in secoes:
                    if secao.ancora == ancora:
                        return secao

    orgao = templates_radar.normalizar(rotulo.split("|")[0])
    completo = templates_radar.normalizar(rotulo)

    # 2. Nome completo ou nome do órgão igual ao da seção.
    for secao in secoes:
        nome = templates_radar.normalizar(secao.nome)
        if nome and nome in (orgao, completo):
            return secao

    # 3. A seção começa com o nome do órgão, ou o contrário.
    #    Cobre "ANP" x "ANP (inclui consultas públicas...)" e
    #    "Planalto" x "Planalto (Resenha Diária)".
    for secao in secoes:
        nome = templates_radar.normalizar(secao.nome)
        if not nome or not orgao:
            continue
        if nome.startswith(orgao + " ") or orgao.startswith(nome + " "):
            return secao

    return None


def agrupar_por_secao(itens, slug, secoes, aliases, secao_padrao_manual=""):
    """
    Distribui as notícias aprovadas de um Radar entre as seções do template.

    Devolve (mapa_por_ancora, sem_secao). Uma notícia sem seção correspondente
    nunca é descartada em silêncio: ela volta em 'sem_secao' e bloqueia a
    geração, porque publicar o Radar sem ela esconderia uma decisão humana.

    'secao_padrao_manual' vale só para item adicionado à mão no portal, cuja
    fonte é texto livre e pode não existir no template. Vazio (o padrão)
    mantém o bloqueio: é melhor parar do que publicar o item sob o nome de
    uma fonte que não é a dele.
    """
    por_ancora = defaultdict(list)
    sem_secao = []

    for item in itens:
        secao = resolver_secao(item.get("fonte"), slug, secoes, aliases)

        if (
            secao is None
            and secao_padrao_manual
            and normalizar_texto(item.get("origem")) == "manual"
        ):
            secao = next(
                (alvo for alvo in secoes if alvo.ancora == secao_padrao_manual),
                None,
            )

        if secao is None:
            sem_secao.append(
                {
                    "radar": slug,
                    "fonte": item.get("fonte", ""),
                    "titulo": item.get("titulo", ""),
                    "url": item.get("url", ""),
                    "origem": item.get("origem", "scraper"),
                    "motivo": (
                        "O template oficial deste Radar não tem seção para esta "
                        "fonte. Mapeie a fonte para uma seção existente em "
                        "templates/mapeamento_radares.json (aliases_fonte), "
                        "acrescente a seção ao template, ou — para item "
                        "adicionado à mão — defina secao_padrao_item_manual."
                    ),
                }
            )
            continue

        por_ancora[secao.ancora].append(
            {
                "titulo": texto_limpo(item.get("titulo")) or "Sem título",
                "url": url_segura(item.get("url")),
                "resumo": texto_limpo(item.get("resumo")),
            }
        )

    return por_ancora, sem_secao


def gravar_recursos(recursos, destino):
    """
    Grava as imagens do template, byte a byte, para a prévia em HTML.

    Cada Radar tem a própria pasta porque os templates reaproveitam os mesmos
    nomes de arquivo para imagens diferentes: "image006.png", por exemplo, é
    um banner distinto em três Radares. Sem separar por Radar, a prévia de um
    mostraria o cabeçalho de outro. O .eml não tem esse problema, já que cada
    mensagem carrega os próprios anexos.
    """
    destino.mkdir(parents=True, exist_ok=True)
    for recurso in recursos:
        nome = recurso.content_id.split("@")[0] or recurso.nome_arquivo
        (destino / nome).write_bytes(recurso.dados)


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

    aprovados, manuais, rejeitados, sem_decisao, decisoes_orfas = aplicar_decisoes(
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
    data_curta = formatar_data_curta(data_edicao).replace("/", ".")

    mapeamento = carregar_mapeamento()
    aliases = mapeamento.get("aliases_fonte", {})
    assuntos = mapeamento.get("assuntos", {})
    padroes_manuais = mapeamento.get("secao_padrao_item_manual", {})

    # Carrega os nove templates antes de gravar qualquer coisa: se um deles
    # estiver faltando ou ilegível, nada é sobrescrito.
    config_ajustes = ajustes_templates.carregar_config()
    carregados = {}
    ajustes_aplicados = {}
    for slug in SLUGS:
        caminho_template = TEMPLATES_DIR / mapeamento["templates"][slug]
        if not caminho_template.exists():
            raise SystemExit(
                f"ERRO: template oficial não encontrado: {caminho_template}. "
                "Os e-mails finais foram preservados."
            )
        try:
            template = templates_radar.carregar_template(str(caminho_template))
            # Ajustes autorizados sobre o HTML extraído: a âncora que faz o
            # "VOLTAR AO SUMÁRIO" funcionar e as seções de fonte que o
            # template ainda não tem. O .msg não é alterado.
            template.html, ajustes = ajustes_templates.aplicar(
                template.html, slug, config_ajustes
            )
            estrutura = templates_radar.analisar(template.html)
        except Exception as erro:
            raise SystemExit(
                f"ERRO ao ler o template {caminho_template.name}: {erro} "
                "Os e-mails finais foram preservados."
            ) from erro
        carregados[slug] = (template, estrutura)
        ajustes_aplicados[slug] = ajustes

    # Distribui as notícias pelas seções antes de gravar, pelo mesmo motivo.
    distribuicao = {}
    sem_secao = []
    for slug in SLUGS:
        _, estrutura = carregados[slug]
        por_ancora, faltantes = agrupar_por_secao(
            agrupados[slug],
            slug,
            estrutura.secoes,
            aliases,
            texto_limpo(padroes_manuais.get(slug)),
        )
        distribuicao[slug] = por_ancora
        sem_secao.extend(faltantes)

    if sem_secao:
        resumo = {
            "status": "bloqueado_por_fonte_sem_secao_no_template",
            "total_itens_boletim": len(boletim["itens"]),
            "total_decisoes": len(decisoes),
            "itens_sem_secao_no_template": sem_secao,
            "arquivos_finais_preservados": True,
        }
        escrever_json_atomico(RESUMO_PATH, resumo)
        raise SystemExit(
            "ERRO: há notícias aprovadas cuja fonte não tem seção no template "
            "oficial do Radar. Consulte output/resumo_geracao_final.json. "
            "Os e-mails finais foram preservados."
        )

    recursos_dir = OUTPUT_DIR / RECURSOS_DIRNAME
    arquivos_gerados = []

    for slug in SLUGS:
        template, estrutura = carregados[slug]
        nome_radar = nomes.get(slug, NOMES_PADRAO[slug])
        por_ancora = distribuicao[slug]

        corpo = templates_radar.preencher(
            template.html,
            estrutura,
            data_curta,
            por_ancora,
        )

        assunto = f"{assuntos.get(slug, nome_radar)} | {data_extenso}"
        mensagem = templates_radar.montar_eml(assunto, corpo, template.recursos)

        caminho_eml = OUTPUT_DIR / f"email_{slug}.eml"
        escrever_bytes_atomico(caminho_eml, mensagem.as_bytes())

        gravar_recursos(template.recursos, recursos_dir / slug)
        caminho_html = OUTPUT_DIR / f"email_{slug}.html"
        escrever_texto_atomico(
            caminho_html,
            templates_radar.html_para_previa(corpo, f"{RECURSOS_DIRNAME}/{slug}"),
        )

        arquivos_gerados.append(
            {
                "slug": slug,
                "nome": nome_radar,
                "template": template.caminho.rsplit("/", 1)[-1],
                "arquivo": caminho_eml.name,
                "previa": caminho_html.name,
                "total_itens": len(agrupados[slug]),
                "secoes_publicadas": sorted(por_ancora),
            }
        )
        print(
            f"Gerado: {caminho_eml.name} ({len(agrupados[slug])} itens, "
            f"{len(por_ancora)} seções)"
        )

    resumo = {
        "status": "sucesso",
        "data_execucao": datetime.datetime.now().astimezone().isoformat(),
        "data_edicao": data_edicao,
        "total_itens_boletim": len(boletim["itens"]),
        "total_decisoes": len(decisoes),
        "total_aprovados": len(aprovados),
        "total_itens_manuais": manuais,
        "total_rejeitados": rejeitados,
        "decisoes_sem_item_correspondente": decisoes_orfas,
        "ajustes_nos_templates": ajustes_aplicados,
        "arquivos_gerados": arquivos_gerados,
    }
    escrever_json_atomico(RESUMO_PATH, resumo)

    if decisoes_orfas:
        print(
            f"Aviso: {len(decisoes_orfas)} decisão(ões) sem item correspondente "
            "no boletim.json foram ignoradas. Ver o resumo."
        )

    print("=" * 60)
    print(f"Itens aprovados: {len(aprovados)} (dos quais {manuais} manuais)")
    print(f"Itens rejeitados: {rejeitados}")
    print(f"Radares gerados: {len(arquivos_gerados)}")
    print(f"Resumo: {RESUMO_PATH}")
    print("Concluído")


if __name__ == "__main__":
    main()
