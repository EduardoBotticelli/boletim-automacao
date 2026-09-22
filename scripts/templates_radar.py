"""
Leitura e preenchimento dos templates oficiais dos Radares (.msg do Marketing).

Princípio central: o HTML do template nunca é reconstruído.

O corpo dos .msg é HTML encapsulado em RTF (MS-OXRTFEX). Depois de
desencapsular, temos de volta exatamente o HTML que o Marketing escreveu, com
os estilos, as tabelas, os comentários condicionais do Word e as referências
"cid:" às imagens. Este módulo localiza trechos desse HTML por deslocamento de
bytes e monta a edição final concatenando fatias do original. Nenhum
serializador de HTML é usado: qualquer byte que não seja explicitamente
substituído chega intacto ao arquivo final.

Nunca use BeautifulSoup/lxml para gerar a saída: os dois reordenam atributos e
alteram os comentários condicionais do Word, o que quebraria o template.
"""

import html as _html
import re
import unicodedata
from dataclasses import dataclass, field

import compressed_rtf
import olefile
from RTFDE.deencapsulate import DeEncapsulator


# Propriedades MAPI usadas (MS-OXPROPS / MS-OXMSG).
_PROP_RTF_COMPRIMIDO = "__substg1.0_10090102"
_PROP_ASSUNTO = "0037"
_PROP_ANEXO_CONTENT_ID = "3712"
_PROP_ANEXO_NOME_LONGO = "3707"
_PROP_ANEXO_NOME = "3704"
_PROP_ANEXO_MIME = "370E"
_PROP_ANEXO_DADOS = "__substg1.0_37010102"

TEXTO_SEM_NOTICIAS = (
    "Não foram identificadas atualizações para este Radar no período analisado."
)

_PLACEHOLDER_DATA = "00.00.2026"
_PLACEHOLDER_TITULO = "Título | "
_PLACEHOLDER_LINK = "Acesse a matéria"
_PLACEHOLDER_DESCRICAO = "Descrição"


# ---------------------------------------------------------------------------
# Leitura do .msg
# ---------------------------------------------------------------------------


@dataclass
class Recurso:
    """Imagem embutida do template, copiada byte a byte do .msg."""

    content_id: str
    nome_arquivo: str
    mime: str
    dados: bytes


@dataclass
class Template:
    caminho: str
    assunto: str
    html: str
    recursos: list = field(default_factory=list)


def _ler_propriedade_texto(ole, base, tag):
    """Lê uma propriedade MAPI de texto, testando Unicode e depois ANSI."""
    for sufixo, codificacao in (("001F", "utf-16-le"), ("001E", "latin-1")):
        caminho = f"{base}/__substg1.0_{tag}{sufixo}" if base else f"__substg1.0_{tag}{sufixo}"
        if ole.exists(caminho):
            return ole.openstream(caminho).read().decode(codificacao, "replace")
    return ""


def carregar_template(caminho_msg):
    """
    Abre um .msg e devolve o HTML original do corpo mais as imagens embutidas.

    O corpo sai de PR_RTF_COMPRESSED: o Outlook grava o HTML encapsulado em
    RTF, e a desencapsulação devolve o HTML original sem perda.
    """
    ole = olefile.OleFileIO(caminho_msg)
    try:
        if not ole.exists(_PROP_RTF_COMPRIMIDO):
            raise ValueError(
                f"{caminho_msg}: não contém corpo RTF (PR_RTF_COMPRESSED)."
            )

        rtf = compressed_rtf.decompress(ole.openstream(_PROP_RTF_COMPRIMIDO).read())

        desencapsulador = DeEncapsulator(rtf)
        desencapsulador.deencapsulate()

        if desencapsulador.get_content_type() != "html":
            raise ValueError(
                f"{caminho_msg}: o corpo RTF não encapsula HTML "
                f"(tipo: {desencapsulador.get_content_type()})."
            )

        corpo = desencapsulador.html
        if isinstance(corpo, bytes):
            corpo = corpo.decode("utf-8", "replace")

        assunto = _ler_propriedade_texto(ole, "", _PROP_ASSUNTO)

        recursos = []
        storages = {
            entrada[0]
            for entrada in ole.listdir(streams=True, storages=True)
            if entrada[0].startswith("__attach")
        }

        for storage in sorted(storages):
            caminho_dados = f"{storage}/{_PROP_ANEXO_DADOS}"
            if not ole.exists(caminho_dados):
                continue

            content_id = _ler_propriedade_texto(ole, storage, _PROP_ANEXO_CONTENT_ID)
            if not content_id:
                continue

            recursos.append(
                Recurso(
                    content_id=content_id,
                    nome_arquivo=(
                        _ler_propriedade_texto(ole, storage, _PROP_ANEXO_NOME_LONGO)
                        or _ler_propriedade_texto(ole, storage, _PROP_ANEXO_NOME)
                        or content_id.split("@")[0]
                    ),
                    mime=(
                        _ler_propriedade_texto(ole, storage, _PROP_ANEXO_MIME)
                        or "application/octet-stream"
                    ),
                    dados=ole.openstream(caminho_dados).read(),
                )
            )

        return Template(
            caminho=caminho_msg,
            assunto=assunto,
            html=corpo,
            recursos=recursos,
        )
    finally:
        ole.close()


# ---------------------------------------------------------------------------
# Varredura do HTML por deslocamento
# ---------------------------------------------------------------------------


@dataclass
class Tag:
    nome: str
    inicio: int
    fim: int
    fechamento: bool


def _varrer_tags(texto):
    """
    Percorre o HTML e devolve as tags com seus deslocamentos.

    Trata os casos que aparecem no HTML do Word:
    - comentários "<!-- ... -->", que podem conter tags dentro (os blocos
      condicionais "[if !supportLists]") e por isso são pulados inteiros;
    - declarações "<![if !vml]>", que não são comentários;
    - aspas dentro de atributos, para que um ">" dentro de um style não
      encerre a tag por engano.
    """
    tags = []
    posicao = 0
    tamanho = len(texto)

    while posicao < tamanho:
        abertura = texto.find("<", posicao)
        if abertura == -1:
            break

        if texto.startswith("<!--", abertura):
            fim = texto.find("-->", abertura)
            posicao = tamanho if fim == -1 else fim + 3
            continue

        if texto.startswith("<!", abertura) or texto.startswith("<?", abertura):
            fim = texto.find(">", abertura)
            posicao = tamanho if fim == -1 else fim + 1
            continue

        cursor = abertura + 1
        fechamento = texto.startswith("/", cursor)
        if fechamento:
            cursor += 1

        inicio_nome = cursor
        while cursor < tamanho and (texto[cursor].isalnum() or texto[cursor] in ":-_"):
            cursor += 1
        nome = texto[inicio_nome:cursor].lower()

        if not nome:
            posicao = abertura + 1
            continue

        aspas = None
        while cursor < tamanho:
            caractere = texto[cursor]
            if aspas:
                if caractere == aspas:
                    aspas = None
            elif caractere in "\"'":
                aspas = caractere
            elif caractere == ">":
                break
            cursor += 1

        tags.append(Tag(nome=nome, inicio=abertura, fim=cursor + 1, fechamento=fechamento))
        posicao = cursor + 1

    return tags


def _elementos_de_topo(texto, tags, nome_alvo, nome_container, indice_container=0):
    """
    Devolve os (início, fim) dos elementos `nome_alvo` que estão no primeiro
    nível de aninhamento dentro da n-ésima ocorrência de `nome_container`.

    Usado para pegar as linhas (<tr>) da tabela principal sem capturar as
    linhas de tabelas aninhadas.
    """
    profundidade_container = 0
    ocorrencia = -1
    dentro = False
    profundidade_alvo = 0
    inicio_atual = None
    resultado = []

    for tag in tags:
        if tag.nome == nome_container:
            if not tag.fechamento:
                if profundidade_container == 0:
                    ocorrencia += 1
                    dentro = ocorrencia == indice_container
                profundidade_container += 1
            else:
                profundidade_container -= 1
                if profundidade_container == 0:
                    dentro = False
            continue

        if not dentro or tag.nome != nome_alvo:
            continue

        if not tag.fechamento:
            if profundidade_alvo == 0:
                inicio_atual = tag.inicio
            profundidade_alvo += 1
        else:
            profundidade_alvo -= 1
            if profundidade_alvo == 0 and inicio_atual is not None:
                resultado.append((inicio_atual, tag.fim))
                inicio_atual = None

    return resultado


def _filhos_diretos(texto, nome_alvo, inicio, fim):
    """Devolve os (início, fim) dos elementos `nome_alvo` filhos diretos do trecho."""
    trecho = texto[inicio:fim]
    tags = _varrer_tags(trecho)

    profundidade = 0
    inicio_atual = None
    resultado = []

    # Ignora a própria tag externa do trecho.
    for tag in tags[1:]:
        if tag.nome != nome_alvo:
            continue
        if not tag.fechamento:
            if profundidade == 0:
                inicio_atual = tag.inicio
            profundidade += 1
        else:
            profundidade -= 1
            if profundidade == 0 and inicio_atual is not None:
                resultado.append((inicio + inicio_atual, inicio + tag.fim))
                inicio_atual = None

    return resultado


def _texto_visivel(fragmento):
    """Texto legível de um fragmento de HTML, para casar nomes de fontes."""
    sem_comentario = re.sub(r"<!--.*?-->", " ", fragmento, flags=re.S)
    sem_tag = re.sub(r"<[^>]*>", " ", sem_comentario)
    return " ".join(_html.unescape(sem_tag).split())


def _ancora_de_secao(fragmento):
    """
    A âncora que identifica uma seção de fonte dentro de uma linha.

    Só conta âncora que envolve conteúdo: no template, a faixa verde da fonte
    é sempre <a name=X>NOME DA FONTE</a>. Âncora vazia (<a name=X></a>) é
    ponto de destino de link, como a do "VOLTAR AO SUMÁRIO", e não delimita
    seção nenhuma.
    """
    for encontrada in re.finditer(
        r"<a[^>]*\bname=[\"']?([A-Za-z0-9_.-]+)[\"']?[^>]*>", fragmento
    ):
        if fragmento[encontrada.end() :].lstrip().startswith("</a>"):
            continue
        return encontrada

    return None


def normalizar(valor):
    """Minúsculas, sem acento e sem pontuação, para comparar nomes de fontes."""
    texto = "".join(
        caractere
        for caractere in unicodedata.normalize("NFD", str(valor or ""))
        if unicodedata.category(caractere) != "Mn"
    )
    texto = texto.lower().replace("&", " e ")
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return " ".join(texto.split())


# ---------------------------------------------------------------------------
# Estrutura do template
# ---------------------------------------------------------------------------


@dataclass
class Secao:
    """Uma fonte do Radar: a faixa verde com o nome e a linha das notícias."""

    ancora: str
    nome: str
    inicio_cabecalho: int
    fim_cabecalho: int
    inicio_corpo: int
    fim_corpo: int


@dataclass
class CelulaSumario:
    ancora: str
    nome: str
    inicio: int
    fim: int
    indice_linha: int


@dataclass
class Estrutura:
    linhas: list
    secoes: list
    celulas_sumario: list
    linhas_sumario: dict
    posicao_data: int


def analisar(html_template):
    """Localiza no HTML do template a data, o sumário e as seções de fontes."""
    tags = _varrer_tags(html_template)
    linhas = _elementos_de_topo(html_template, tags, "tr", "table", 0)

    if not linhas:
        raise ValueError("Template sem tabela principal reconhecível.")

    posicao_data = html_template.find(_PLACEHOLDER_DATA)

    secoes = []
    indices_cabecalho = []

    for indice, (inicio, fim) in enumerate(linhas):
        encontrada = _ancora_de_secao(html_template[inicio:fim])
        if not encontrada:
            continue

        if indice + 1 >= len(linhas):
            raise ValueError(
                f"Seção '{encontrada.group(1)}' sem linha de notícias no template."
            )

        inicio_corpo, fim_corpo = linhas[indice + 1]
        secoes.append(
            Secao(
                ancora=encontrada.group(1),
                nome=_texto_visivel(html_template[inicio:fim]),
                inicio_cabecalho=inicio,
                fim_cabecalho=fim,
                inicio_corpo=inicio_corpo,
                fim_corpo=fim_corpo,
            )
        )
        indices_cabecalho.append(indice)

    if not secoes:
        raise ValueError("Template sem seções de fonte (nenhuma âncora encontrada).")

    # O sumário é tudo que vem antes da primeira seção. Só entram no mapa as
    # células que correspondem a uma seção de fonte: as demais linhas dessa
    # faixa (data da edição, banner, rótulos) nunca podem ser removidas.
    primeiro_cabecalho = indices_cabecalho[0]
    ancoras_validas = {secao.ancora for secao in secoes}
    nomes_validos = {normalizar(secao.nome): secao.ancora for secao in secoes}

    celulas = []
    linhas_sumario = {}

    for indice in range(primeiro_cabecalho):
        inicio, fim = linhas[indice]
        identificadas = []

        for inicio_celula, fim_celula in _filhos_diretos(
            html_template, "td", inicio, fim
        ):
            fragmento = html_template[inicio_celula:fim_celula]
            encontrada = re.search(r"href=[\"']?#([A-Za-z0-9_.-]+)", fragmento)
            nome = _texto_visivel(fragmento)

            if encontrada and encontrada.group(1) in ancoras_validas:
                ancora = encontrada.group(1)
            elif normalizar(nome) in nomes_validos:
                # Entrada do sumário sem link interno: casa pelo nome da fonte.
                ancora = nomes_validos[normalizar(nome)]
            else:
                continue

            identificadas.append(
                CelulaSumario(
                    ancora=ancora,
                    nome=nome,
                    inicio=inicio_celula,
                    fim=fim_celula,
                    indice_linha=indice,
                )
            )

        if identificadas:
            celulas.extend(identificadas)
            linhas_sumario[indice] = (inicio, fim, len(identificadas))

    return Estrutura(
        linhas=linhas,
        secoes=secoes,
        celulas_sumario=celulas,
        linhas_sumario=linhas_sumario,
        posicao_data=posicao_data,
    )


# ---------------------------------------------------------------------------
# Preenchimento
# ---------------------------------------------------------------------------


def _escapar(valor):
    return _html.escape(str(valor or ""), quote=True)


def _unidades_de_noticia(html_template, secao):
    """Os parágrafos de notícia dentro da linha de corpo de uma seção."""
    return _filhos_diretos(
        html_template, "p", secao.inicio_corpo, secao.fim_corpo
    )


def _preencher_unidade(modelo, noticia):
    """
    Preenche uma cópia do parágrafo de notícia do template.

    Só três trechos de texto são trocados. Todo o resto do parágrafo (estilos,
    marcador da lista, quebras) vem intacto do template.
    """
    preenchido = modelo

    titulo = _escapar(noticia["titulo"])
    preenchido = preenchido.replace(_PLACEHOLDER_TITULO, titulo + " | ", 1)

    url = noticia.get("url") or ""
    if url:
        ancora = (
            f'<a href="{_escapar(url)}" target="_blank" rel="noopener noreferrer">'
            f"{_PLACEHOLDER_LINK}</a>"
        )
        preenchido = preenchido.replace(_PLACEHOLDER_LINK, ancora, 1)

    preenchido = preenchido.replace(
        _PLACEHOLDER_DESCRICAO, _escapar(noticia.get("resumo", "")), 1
    )

    return preenchido


def _unidade_sem_noticias(modelo, mensagem):
    """
    Monta, a partir do parágrafo de notícia do template, a linha usada quando
    o Radar não tem nada no período.

    Mantém o parágrafo e seus estilos; apenas escreve a mensagem no lugar do
    título e remove os trechos do link e da descrição.
    """
    resultado = modelo.replace(_PLACEHOLDER_TITULO, _escapar(mensagem), 1)
    resultado = resultado.replace(_PLACEHOLDER_LINK, "", 1)
    resultado = resultado.replace(_PLACEHOLDER_DESCRICAO, "", 1)
    return resultado


def _corpo_preenchido(html_template, secao, noticias, mensagem_vazio=None):
    """Reescreve a linha de notícias de uma seção mantendo a linha original."""
    unidades = _unidades_de_noticia(html_template, secao)
    if not unidades:
        raise ValueError(
            f"Seção '{secao.ancora}': linha de notícias sem parágrafo de modelo."
        )

    modelo = html_template[unidades[0][0] : unidades[0][1]]

    if mensagem_vazio is not None:
        conteudo = _unidade_sem_noticias(modelo, mensagem_vazio)
    else:
        # Regra: duplicar a estrutura já existente e descartar as sobras.
        conteudo = "".join(_preencher_unidade(modelo, item) for item in noticias)

    antes = html_template[secao.inicio_corpo : unidades[0][0]]
    depois = html_template[unidades[-1][1] : secao.fim_corpo]

    return antes + conteudo + depois


def preencher(html_template, estrutura, data_edicao, noticias_por_ancora):
    """
    Devolve o HTML da edição final.

    `noticias_por_ancora` mapeia a âncora da seção para a lista de notícias
    aprovadas. Seções ausentes do mapa (ou com lista vazia) são removidas,
    junto com a entrada correspondente no sumário.

    Quando nenhuma seção tem notícia, o template é preservado e uma única
    seção exibe a mensagem padrão.
    """
    com_noticias = [
        secao
        for secao in estrutura.secoes
        if noticias_por_ancora.get(secao.ancora)
    ]
    radar_vazio = not com_noticias

    ancoras_mantidas = {secao.ancora for secao in com_noticias}

    # Sumário: remove as células das fontes sem notícia. Uma linha que perde
    # todas as células é removida inteira, para não deixar faixa vazia.
    celulas_removidas = {
        (celula.inicio, celula.fim)
        for celula in estrutura.celulas_sumario
        if celula.ancora not in ancoras_mantidas
    }

    linhas_esvaziadas = set()
    for indice, (_, _, total) in estrutura.linhas_sumario.items():
        removidas = sum(
            1
            for celula in estrutura.celulas_sumario
            if celula.indice_linha == indice
            and (celula.inicio, celula.fim) in celulas_removidas
        )
        if removidas == total:
            linhas_esvaziadas.add(indice)

    # Monta a saída concatenando fatias do template original.
    partes = []
    cursor = 0

    def emitir_ate(posicao):
        nonlocal cursor
        if posicao > cursor:
            partes.append(html_template[cursor:posicao])
        cursor = max(cursor, posicao)

    # 1. Data da edição.
    if estrutura.posicao_data != -1:
        emitir_ate(estrutura.posicao_data)
        partes.append(_escapar(data_edicao))
        cursor = estrutura.posicao_data + len(_PLACEHOLDER_DATA)

    # 2. Sumário.
    for indice in sorted(estrutura.linhas_sumario):
        inicio_linha, fim_linha, _ = estrutura.linhas_sumario[indice]
        if indice in linhas_esvaziadas:
            emitir_ate(inicio_linha)
            cursor = fim_linha
            continue
        for celula in estrutura.celulas_sumario:
            if celula.indice_linha != indice:
                continue
            if (celula.inicio, celula.fim) in celulas_removidas:
                emitir_ate(celula.inicio)
                cursor = celula.fim

    # 3. Seções.
    for posicao, secao in enumerate(estrutura.secoes):
        noticias = noticias_por_ancora.get(secao.ancora) or []

        if radar_vazio and posicao == 0:
            # Radar sem nada no período: some a faixa verde com o nome da
            # fonte (não há notícia dela) e fica só a linha com a mensagem,
            # montada a partir do parágrafo do próprio template.
            emitir_ate(secao.inicio_cabecalho)
            partes.append(
                _corpo_preenchido(
                    html_template, secao, [], mensagem_vazio=TEXTO_SEM_NOTICIAS
                )
            )
            cursor = secao.fim_corpo
            continue

        if not noticias:
            # Remove a faixa da fonte e a linha de notícias dela.
            emitir_ate(secao.inicio_cabecalho)
            cursor = secao.fim_corpo
            continue

        emitir_ate(secao.inicio_corpo)
        partes.append(_corpo_preenchido(html_template, secao, noticias))
        cursor = secao.fim_corpo

    partes.append(html_template[cursor:])
    return "".join(partes)


# ---------------------------------------------------------------------------
# Artefatos de saída
# ---------------------------------------------------------------------------


def montar_eml(assunto, html_corpo, recursos, data_cabecalho=None):
    """
    Monta a mensagem final como .eml (RFC 5322), pronta para envio.

    O corpo vai exatamente como saiu do template e as imagens entram como
    partes relacionadas com o mesmo Content-ID que o HTML referencia em
    "cid:", que é o que mantém as imagens embutidas na mensagem.

    Usa apenas a biblioteca padrão: roda em qualquer Linux, inclusive no
    runner do GitHub Actions.
    """
    from email.message import EmailMessage
    from email.utils import formatdate

    mensagem = EmailMessage()
    mensagem["Subject"] = assunto
    mensagem["Date"] = data_cabecalho or formatdate(localtime=True)
    mensagem["MIME-Version"] = "1.0"

    # Alternativa em texto puro para clientes que não renderizam HTML.
    mensagem.set_content(
        _texto_visivel(html_corpo) or assunto,
        subtype="plain",
        charset="utf-8",
    )
    mensagem.add_alternative(html_corpo, subtype="html", charset="utf-8")

    parte_html = mensagem.get_payload()[-1]

    for recurso in recursos:
        tipo, _, subtipo = recurso.mime.partition("/")
        parte_html.add_related(
            recurso.dados,
            maintype=tipo or "application",
            subtype=subtipo or "octet-stream",
            cid=f"<{recurso.content_id}>",
            filename=recurso.nome_arquivo,
        )

    return mensagem


def html_para_previa(html_corpo, pasta_recursos):
    """
    Versão do HTML em que as referências "cid:" apontam para os arquivos de
    imagem gravados em disco, para conferir a edição no navegador.

    É uma troca mecânica do atributo src. O corpo, os estilos e a estrutura
    continuam sendo os do template; o .eml é que carrega o corpo original.
    """

    def trocar(encontrada):
        content_id = encontrada.group(1)
        nome = content_id.split("@")[0]
        return f'src="{pasta_recursos}/{nome}"'

    return re.sub(r'src="cid:([^"]+)"', trocar, html_corpo)
