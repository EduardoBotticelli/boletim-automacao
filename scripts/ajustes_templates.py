"""
Ajustes aplicados ao HTML extraído dos templates oficiais.

Os arquivos .msg do Marketing não são alterados: eles continuam sendo a
fonte, somente leitura (ver docs/templates-oficiais.md). Os ajustes abaixo
são aplicados ao HTML já desencapsulado, na hora de gerar a edição, e estão
declarados em templates/ajustes_templates.json para ficarem auditáveis.

São três, todos autorizados:

1. Âncora de destino do "VOLTAR AO SUMÁRIO". O link aponta para "#Sumario" e
   essa âncora não existe em nenhum dos nove templates. A âncora é um
   elemento vazio, invisível, inserido no bloco do sumário.

2. Seções de fontes que o Filtro 1 permite mas que o template não tem. Cada
   seção nova é uma cópia literal de uma seção existente do mesmo template:
   a mesma linha de cabeçalho e a mesma linha de notícias, trocando só a
   âncora e o nome da fonte. A entrada no sumário também é cópia de uma
   entrada existente, aproveitando as células vazias que a grade já reserva.

3. A faixa "Outras publicações", criada nos nove templates pelo mesmo
   processo de cópia do item 2. É o destino de qualquer notícia aprovada
   cuja fonte não tenha faixa própria naquele Radar, venha ela de uma fonte
   fora da matriz do Filtro 1, de um Radar escolhido à mão no portal ou de
   um item adicionado à mão com a fonte digitada. A procedência real da
   notícia continua visível: quem entra nessa faixa é publicado com o nome
   da própria fonte no começo do título.

Nada além disso é tocado: cabeçalho, data, imagens, avaliação, rodapé,
links institucionais e as seções que já existiam ficam como vieram.
"""

import json
import re
from pathlib import Path

import templates_radar


BASE_DIR = Path(__file__).resolve().parent.parent
AJUSTES_PATH = BASE_DIR / "templates" / "ajustes_templates.json"


def carregar_config(caminho=None):
    caminho = Path(caminho) if caminho else AJUSTES_PATH
    if not caminho.exists():
        return {}
    return json.loads(caminho.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. Âncora do "VOLTAR AO SUMÁRIO"
# ---------------------------------------------------------------------------


def _linha_rotulo_sumario(html, estrutura):
    """
    A linha do rótulo do sumário ("navegue pelas fontes").

    É a última linha antes da primeira seção que tem texto visível, não é a
    linha da data e não faz parte da grade de fontes.
    """
    limite = estrutura.secoes[0].inicio_cabecalho
    indices_grade = set(estrutura.linhas_sumario)
    escolhida = None

    for indice, (inicio, fim) in enumerate(estrutura.linhas):
        if inicio >= limite:
            break
        if indice in indices_grade:
            continue
        texto = templates_radar._texto_visivel(html[inicio:fim])
        if not texto or re.fullmatch(r"[\d.]+", texto):
            continue
        escolhida = (inicio, fim)

    return escolhida


def inserir_ancora_sumario(html, estrutura, nome_ancora):
    """
    Insere a âncora de destino do "VOLTAR AO SUMÁRIO" no bloco do sumário.

    A âncora é um <a name> vazio: não ocupa espaço, não muda texto, cor,
    fonte, espaçamento nem estrutura. Vai dentro do primeiro parágrafo da
    linha do rótulo, que é a primeira coisa do sumário e sobrevive mesmo na
    edição vazia (onde a grade de fontes é removida inteira).
    """
    if f"name={nome_ancora}" in html or f'name="{nome_ancora}"' in html:
        return html, False

    linha = _linha_rotulo_sumario(html, estrutura)
    if linha is None:
        return html, False

    inicio, fim = linha

    # Ponto de inserção: logo depois da abertura do primeiro <p> da linha.
    abertura = re.search(r"<p\b[^>]*>", html[inicio:fim])
    if not abertura:
        return html, False

    posicao = inicio + abertura.end()
    marcacao = f'<a name="{nome_ancora}"></a>'

    return html[:posicao] + marcacao + html[posicao:], True


# ---------------------------------------------------------------------------
# 2. Seções novas
# ---------------------------------------------------------------------------


def _trocar_identidade(fragmento, ancora_antiga, nome_antigo, ancora_nova, nome_novo):
    """
    Copia um fragmento de seção trocando só a âncora e o nome visível.

    Qualquer outro byte (cores, fontes, espaçamentos, alturas, marcação do
    Word) vem intacto do fragmento de origem.
    """
    resultado = re.sub(
        r"(\bname=)([\"']?)" + re.escape(ancora_antiga) + r"\2",
        lambda encontrada: f'{encontrada.group(1)}"{ancora_nova}"',
        fragmento,
        count=1,
    )

    alvo = f">{nome_antigo}<"
    if resultado.count(alvo) != 1:
        raise ValueError(
            f"A seção modelo '{ancora_antiga}' não tem o nome '{nome_antigo}' "
            "em um único trecho de texto; escolha outra seção como modelo."
        )
    resultado = resultado.replace(alvo, f">{nome_novo}<", 1)

    return resultado


def _celulas_do_sumario(html, estrutura):
    """
    Todas as células da grade do sumário, em ordem, com o texto visível.

    A grade sempre tem três células por linha; quando sobram posições, o
    template as mantém vazias. São essas que recebem as fontes novas.
    """
    celulas = []
    for indice in sorted(estrutura.linhas_sumario):
        inicio, fim, _ = estrutura.linhas_sumario[indice]
        for inicio_celula, fim_celula in templates_radar._filhos_diretos(
            html, "td", inicio, fim
        ):
            celulas.append(
                {
                    "linha": indice,
                    "inicio": inicio_celula,
                    "fim": fim_celula,
                    "texto": templates_radar._texto_visivel(
                        html[inicio_celula:fim_celula]
                    ),
                }
            )
    return celulas


def _conteudo_da_celula(html, celula):
    """
    O intervalo de conteúdo de uma célula do sumário.

    Célula preenchida tem um <p> dentro; célula livre aparece de duas formas
    nos templates, com um <p> de espaço em branco ou completamente vazia
    (<td ...></td>). Nos dois casos devolvemos o que há entre a abertura e o
    fechamento da célula, que é o que vai ser trocado — o <td> em si, com
    largura, bordas e fundo, nunca é tocado.
    """
    paragrafos = templates_radar._filhos_diretos(
        html, "p", celula["inicio"], celula["fim"]
    )
    if paragrafos:
        return paragrafos[0]

    abertura = re.match(r"<td\b[^>]*>", html[celula["inicio"] : celula["fim"]])
    if not abertura:
        raise ValueError("Célula do sumário sem abertura reconhecível.")

    inicio = celula["inicio"] + abertura.end()
    fim = html.rfind("</td>", inicio, celula["fim"])
    if fim == -1:
        raise ValueError("Célula do sumário sem fechamento reconhecível.")

    return inicio, fim


def _conteudo_preenchido(html, celula_modelo, ancora, nome):
    """
    O conteúdo de uma célula do sumário para uma fonte nova, copiado de uma
    célula já preenchida trocando só o link interno e o nome.
    """
    ini_modelo, fim_modelo = _conteudo_da_celula(html, celula_modelo)
    modelo = html[ini_modelo:fim_modelo]

    ancora_modelo = re.search(r'href="#([A-Za-z0-9_.-]+)"', modelo)
    if not ancora_modelo:
        raise ValueError("Célula modelo do sumário sem link interno.")

    novo = modelo.replace(
        f'href="#{ancora_modelo.group(1)}"', f'href="#{ancora}"', 1
    )

    texto_modelo = templates_radar._texto_visivel(modelo)
    alvo = f">{texto_modelo}<"
    if novo.count(alvo) != 1:
        raise ValueError(
            "Célula modelo do sumário com texto em mais de um trecho; "
            "escolha outra célula como modelo."
        )

    return novo.replace(alvo, f">{nome}<", 1)


def _preencher_celula_sumario(html, celula_vazia, conteudo):
    """
    Escreve uma fonte em uma célula livre da grade.

    Só o conteúdo de dentro é trocado. O <td> continua com a largura, as
    bordas e o fundo originais, então a grade não se altera.
    """
    ini_vazia, fim_vazia = _conteudo_da_celula(html, celula_vazia)
    return html[:ini_vazia] + conteudo + html[fim_vazia:]


def _modelo_celula_vazia(html, estrutura):
    """
    Como o template escreve uma célula livre da grade.

    Aparece de duas formas: um parágrafo com espaço em branco, ou a célula
    sem conteúdo nenhum. Quando não há célula livre para copiar (a grade
    está cheia), usamos a segunda forma, que também é do template.
    """
    for indice in sorted(estrutura.linhas_sumario):
        inicio, fim, _ = estrutura.linhas_sumario[indice]
        for a, b in templates_radar._filhos_diretos(html, "td", inicio, fim):
            if templates_radar._texto_visivel(html[a:b]):
                continue
            ini, fim_conteudo = _conteudo_da_celula(html, {"inicio": a, "fim": b})
            return html[ini:fim_conteudo]
    return ""


def _linha_extra_do_sumario(html, estrutura, conteudo_vazio, conteudo_primeiro):
    """
    Uma linha nova da grade, copiada da última linha do sumário.

    A primeira célula recebe a fonte nova e as demais ficam livres, que é
    como o template já trata uma última linha incompleta. A linha é cópia da
    existente, então larguras, bordas e fundo são os mesmos.
    """
    indice = max(estrutura.linhas_sumario)
    inicio, fim, _ = estrutura.linhas_sumario[indice]
    linha = html[inicio:fim]

    celulas = templates_radar._filhos_diretos(html, "td", inicio, fim)

    # Reescreve as células da cópia, da última para a primeira, para os
    # deslocamentos não se moverem durante a substituição.
    nova = linha
    for posicao, (a, b) in reversed(list(enumerate(celulas))):
        ini_celula, fim_celula = _conteudo_da_celula(html, {"inicio": a, "fim": b})
        conteudo = conteudo_primeiro if posicao == 0 else conteudo_vazio
        nova = (
            nova[: ini_celula - inicio]
            + conteudo
            + nova[fim_celula - inicio :]
        )

    return nova, fim


def _acrescentar_secao(html, slug, definicao, conteudo_vazio):
    """
    Acrescenta ao template uma seção copiada de outra seção do mesmo template.

    A cópia é literal: a mesma linha de cabeçalho e a mesma linha de notícias
    do modelo, trocando só a âncora e o nome visível. A seção entra depois da
    última existente e ganha a entrada correspondente no sumário.

    Devolve (html, detalhe). O detalhe é None quando a seção já existia.
    """
    estrutura = templates_radar.analisar(html)

    ancora = definicao["ancora"]
    nome = definicao["nome"]
    modelo_ancora = definicao["modelo"]

    if any(secao.ancora == ancora for secao in estrutura.secoes):
        return html, None

    modelo = next(
        (s for s in estrutura.secoes if s.ancora == modelo_ancora), None
    )
    if modelo is None:
        raise ValueError(
            f"{slug}: a seção modelo '{modelo_ancora}' não existe no template."
        )

    cabecalho = _trocar_identidade(
        html[modelo.inicio_cabecalho : modelo.fim_cabecalho],
        modelo.ancora,
        modelo.nome,
        ancora,
        nome,
    )
    corpo = html[modelo.inicio_corpo : modelo.fim_corpo]

    conferencia = templates_radar._texto_visivel(cabecalho)
    if conferencia != nome:
        raise ValueError(
            f"{slug}: o cabeçalho copiado ficou com o texto {conferencia!r} "
            f"em vez de {nome!r}."
        )

    # A seção nova entra depois da última existente.
    ultima = max(estrutura.secoes, key=lambda s: s.fim_corpo)
    posicao = ultima.fim_corpo
    html = html[:posicao] + cabecalho + corpo + html[posicao:]

    # Entrada no sumário, na primeira posição livre da grade.
    estrutura = templates_radar.analisar(html)
    celulas = _celulas_do_sumario(html, estrutura)
    preenchidas = [c for c in celulas if c["texto"]]
    livres = [c for c in celulas if not c["texto"]]

    conteudo = _conteudo_preenchido(
        html, preenchidas[-1], ancora, definicao["nome_sumario"]
    )

    if livres:
        html = _preencher_celula_sumario(html, livres[0], conteudo)
        linha_usada = livres[0]["linha"]
    else:
        nova_linha, fim_ultima = _linha_extra_do_sumario(
            html, estrutura, conteudo_vazio, conteudo
        )
        html = html[:fim_ultima] + nova_linha + html[fim_ultima:]
        linha_usada = max(estrutura.linhas_sumario) + 1

    detalhe = {
        "radar": slug,
        "ancora": ancora,
        "nome": nome,
        "copiada_de": modelo_ancora,
        "linha_sumario": linha_usada,
    }

    return html, detalhe


def aplicar_secoes_novas(html, slug, secoes_novas, conteudo_vazio=None):
    """
    Acrescenta ao template as seções de fonte que faltam.

    Devolve (html, relatório).
    """
    if conteudo_vazio is None:
        conteudo_vazio = _modelo_celula_vazia(html, templates_radar.analisar(html))

    relatorio = []
    for definicao in secoes_novas:
        html, detalhe = _acrescentar_secao(html, slug, definicao, conteudo_vazio)
        if detalhe is not None:
            relatorio.append(detalhe)

    return html, relatorio


# ---------------------------------------------------------------------------
# 3. Faixa "Outras publicações"
# ---------------------------------------------------------------------------


def ancora_generica(config):
    """
    A âncora da faixa "Outras publicações", ou "" se ela não for declarada.

    É o que o gerador consulta para saber onde publicar uma notícia cuja
    fonte não tem faixa própria no Radar. Sem a declaração, o gerador volta a
    bloquear: nenhuma notícia aprovada some em silêncio.
    """
    generica = config.get("secao_outras_publicacoes") or {}
    return generica.get("ancora") or ""


def aplicar_secao_generica(html, slug, config_generica, conteudo_vazio=None):
    """
    Cria no template do Radar a faixa que recebe as fontes sem faixa própria.

    A faixa é criada pelo mesmo processo das demais: cópia literal de uma
    seção existente do próprio template, declarada em 'modelo'. Só o nome e a
    âncora mudam.

    Devolve (html, detalhe).
    """
    modelos = config_generica.get("modelo") or {}
    modelo_ancora = modelos.get(slug)
    if not modelo_ancora:
        raise ValueError(
            f"{slug}: a faixa genérica não diz de qual seção copiar. Preencha "
            "'secao_outras_publicacoes.modelo' em "
            "templates/ajustes_templates.json."
        )

    if conteudo_vazio is None:
        conteudo_vazio = _modelo_celula_vazia(html, templates_radar.analisar(html))

    definicao = {
        "ancora": config_generica["ancora"],
        "nome": config_generica["nome"],
        "nome_sumario": config_generica.get("nome_sumario")
        or config_generica["nome"],
        "modelo": modelo_ancora,
    }

    return _acrescentar_secao(html, slug, definicao, conteudo_vazio)


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------


def aplicar(html, slug, config):
    """
    Aplica ao HTML do template os ajustes declarados para o Radar.

    Devolve (html, relatório) com o que foi efetivamente alterado.
    """
    relatorio = {
        "ancora_sumario": False,
        "secoes_novas": [],
        "secao_generica": None,
    }

    nome_ancora = config.get("ancora_voltar_sumario")
    if nome_ancora:
        estrutura = templates_radar.analisar(html)
        html, inseriu = inserir_ancora_sumario(html, estrutura, nome_ancora)
        relatorio["ancora_sumario"] = inseriu

    # O modelo de célula livre da grade é capturado uma vez só, antes de
    # qualquer preenchimento: depois de ocupar as posições que sobravam, não
    # haveria mais de onde copiar.
    conteudo_vazio = _modelo_celula_vazia(html, templates_radar.analisar(html))

    secoes_novas = (config.get("secoes_novas") or {}).get(slug) or []
    if secoes_novas:
        html, detalhes = aplicar_secoes_novas(
            html, slug, secoes_novas, conteudo_vazio
        )
        relatorio["secoes_novas"] = detalhes

    # A faixa genérica entra por último, depois de todas as fontes: é para
    # onde vai quem não tem faixa própria, então é a última do Radar.
    generica = config.get("secao_outras_publicacoes") or {}
    if generica.get("ancora"):
        html, detalhe = aplicar_secao_generica(
            html, slug, generica, conteudo_vazio
        )
        relatorio["secao_generica"] = detalhe

    return html, relatorio
