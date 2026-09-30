"""
Testa a montagem do dossier, a classificacao em lotes e o resgate por
escassez do scripts/gerar_boletim.py.

Nao acessa rede nem usa chave: o cliente do Gemini e falso e o conteudo das
paginas e sintetico. O que estes testes protegem:

- o bloco da busca complementar sobrevive ao limite de caracteres, inclusive
  quando a pagina sozinha ja encheria MAX_CHARS (era o defeito que descartava
  65% do que a busca encontrava);
- um lote que falha nao derruba os outros, e as fontes dele nao somem;
- o resgate por escassez respeita o Filtro 1, o piso e a exclusao
  institucional, e identifica o item para a curadoria;
- o 503 espera e repete no mesmo modelo, o 429 desce na hora e a mensagem
  dele fica inteira no log;
- a busca complementar e paga uma vez por escopo e cada publicacao entra uma
  vez no dossier, na fonte certa;
- o dossier guardado em disco refaz exatamente o mesmo dossier.

Uso: python scripts/testar_coleta.py
"""

import json
import sys
import tempfile
import types
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))


def _stub(nome, **atributos):
    modulo = types.ModuleType(nome)
    for chave, valor in atributos.items():
        setattr(modulo, chave, valor)
    sys.modules[nome] = modulo
    return modulo


# O modulo importa firecrawl e google.genai no topo. Nenhum dos dois e usado
# pelas funcoes testadas aqui, entao entram como stub para o teste rodar sem
# as dependencias de coleta instaladas.
_stub("firecrawl", Firecrawl=object)
_stub("google")
_stub("google.genai", Client=object)
_stub("google.genai.types", GenerateContentConfig=lambda **opcoes: opcoes)
sys.modules["google"].genai = sys.modules["google.genai"]
sys.modules["google.genai"].types = sys.modules["google.genai.types"]

import gerar_boletim as gb  # noqa: E402


# ---------------------------------------------------------------------------
# P1 - a busca complementar precisa caber no dossier
# ---------------------------------------------------------------------------


def descobertas_falsas(quantidade):
    return [
        {
            "titulo": f"Publicacao {i}",
            "url": f"https://exemplo.invalido/noticia-{i}",
            "descricao": "Resumo da publicacao " + str(i),
        }
        for i in range(quantidade)
    ]


def teste_busca_sobrevive_em_pagina_grande():
    """
    O caso que o diagnostico encontrou: pagina maior que MAX_CHARS.

    Antes, o bloco da busca era concatenado e cortado fora inteiro. Agora ele
    entra e a pagina ocupa o que sobra.
    """
    bruto = "x" * 80000
    descobertas = descobertas_falsas(30)

    conteudo, chars_busca, truncado = gb.montar_conteudo(bruto, descobertas)

    assert len(conteudo) <= gb.MAX_CHARS, len(conteudo)
    assert chars_busca > 0, "o bloco da busca nao entrou"
    assert truncado, "a pagina era maior que o espaco e deveria constar cortada"

    for item in descobertas:
        assert item["url"] in conteudo, f"{item['url']} ficou de fora do dossier"

    # E a pagina continua presente: a busca nao pode engolir o conteudo.
    assert conteudo.startswith("x" * 1000)


def teste_sem_busca_o_comportamento_nao_muda():
    bruto = "y" * 80000
    conteudo, chars_busca, truncado = gb.montar_conteudo(bruto, [])
    assert conteudo == bruto[: gb.MAX_CHARS]
    assert chars_busca == 0
    assert truncado


def teste_pagina_pequena_cabe_inteira():
    bruto = "z" * 1200
    descobertas = descobertas_falsas(3)
    conteudo, chars_busca, truncado = gb.montar_conteudo(bruto, descobertas)
    assert bruto in conteudo, "a pagina pequena deveria caber inteira"
    assert chars_busca > 0
    assert not truncado


def teste_bloco_da_busca_tem_teto():
    """Busca com muitos resultados nao pode ocupar o dossier inteiro."""
    bruto = "w" * 80000
    descobertas = [
        {
            "titulo": "T" * 400,
            "url": f"https://exemplo.invalido/{i}",
            "descricao": "D" * 800,
        }
        for i in range(60)
    ]
    conteudo, chars_busca, _ = gb.montar_conteudo(bruto, descobertas)

    assert chars_busca <= gb.LIMITE_BUSCA_CHARS, chars_busca
    assert len(conteudo) <= gb.MAX_CHARS
    sobrou_de_pagina = len(conteudo) - chars_busca
    assert sobrou_de_pagina >= gb.MAX_CHARS // 2, (
        f"a pagina ficou com apenas {sobrou_de_pagina} caracteres"
    )


# ---------------------------------------------------------------------------
# P2 - classificacao em lotes
# ---------------------------------------------------------------------------


def dossier_falso(quantidade):
    return [
        {"fonte": f"Fonte {i}", "categoria": "Teste", "url": f"https://exemplo.invalido/{i}", "conteudo": "conteudo"}
        for i in range(quantidade)
    ]


def teste_lotes_cobrem_todas_as_fontes():
    dossier = dossier_falso(14)
    chamadas = []

    def falso_gemini(cliente, prompt, orcamento=None):
        chamadas.append(prompt)
        # Devolve um item por fonte citada no prompt.
        itens = [
            {"fonte": d["fonte"], "titulo": f"Item de {d['fonte']}", "boletins_confirmados": []}
            for d in dossier
            if f'"{d["fonte"]}"' in prompt
        ]
        return {"itens": itens}, "gemini-3.7-flash", [{"status": "sucesso"}]

    original, gb.gemini = gb.gemini, falso_gemini
    original_intervalo, gb.INTERVALO_LOTES = gb.INTERVALO_LOTES, 0
    try:
        unido, modelos, registro, falharam = gb.classificar(None, "PROMPT", "\nCTX\n", dossier)
    finally:
        gb.gemini = original
        gb.INTERVALO_LOTES = original_intervalo

    esperado = -(-len(dossier) // gb.LOTE_FONTES)
    assert len(chamadas) == esperado, f"{len(chamadas)} chamadas, esperava {esperado}"
    assert len(registro) == esperado
    assert not falharam
    assert len(unido["itens"]) == len(dossier), unido["itens"]
    assert set(modelos) == {"gemini-3.7-flash"}

    vistos = {i["fonte"] for i in unido["itens"]}
    assert vistos == {d["fonte"] for d in dossier}, "alguma fonte ficou sem classificacao"


def teste_lote_que_falha_nao_derruba_os_outros():
    dossier = dossier_falso(12)

    def falso_gemini(cliente, prompt, orcamento=None):
        if '"Fonte 0"' in prompt:
            return None, "", [{"status": "erro", "erro": "429"}]
        itens = [
            {"fonte": d["fonte"], "titulo": "x", "boletins_confirmados": []}
            for d in dossier
            if f'"{d["fonte"]}"' in prompt
        ]
        return {"itens": itens}, "gemini-3.6-flash", [{"status": "sucesso"}]

    original, gb.gemini = gb.gemini, falso_gemini
    original_intervalo, gb.INTERVALO_LOTES = gb.INTERVALO_LOTES, 0
    try:
        unido, modelos, registro, falharam = gb.classificar(None, "P", "\nC\n", dossier)
    finally:
        gb.gemini = original
        gb.INTERVALO_LOTES = original_intervalo

    assert unido is not None, "o lote bom deveria ter sobrevivido"
    assert len(falharam) == gb.LOTE_FONTES, falharam
    assert "Fonte 0" in falharam
    assert all(i["fonte"] not in falharam for i in unido["itens"])
    assert len(unido["itens"]) == len(dossier) - gb.LOTE_FONTES


def teste_todos_os_lotes_falhando_devolve_nada():
    def falso_gemini(cliente, prompt, orcamento=None):
        return None, "", [{"status": "erro"}]

    original, gb.gemini = gb.gemini, falso_gemini
    original_intervalo, gb.INTERVALO_LOTES = gb.INTERVALO_LOTES, 0
    try:
        unido, modelos, registro, falharam = gb.classificar(None, "P", "\nC\n", dossier_falso(6))
    finally:
        gb.gemini = original
        gb.INTERVALO_LOTES = original_intervalo

    assert unido is None
    assert len(falharam) == 6


# ---------------------------------------------------------------------------
# Resgate por escassez
# ---------------------------------------------------------------------------


def item(fonte, titulo, boletins, rejeitados, **extras):
    registro = {
        "fonte": fonte,
        "titulo": titulo,
        "boletins": list(boletins),
        "boletins_rejeitados": [dict(r) for r in rejeitados],
        "motivo_filtragem": "Motivo original.",
    }
    registro.update(extras)
    return registro


def teste_resgate_preenche_ate_o_piso():
    """
    Radar abaixo do piso recebe os recusados pela IA, na ordem, ate o piso.
    """
    itens = [
        item(
            "SENACON | Notícias",
            f"Publicacao {i}",
            ["regulatorio-oleo-gas"],
            [{"boletim": "contencioso-civel", "motivo": "Possivel, mas insuficiente."}],
        )
        for i in range(8)
    ]

    resgates = gb.resgatar_por_escassez(itens, 5)

    promovidos = [i for i in itens if "contencioso-civel" in i["boletins"]]
    assert len(promovidos) == 5, f"promoveu {len(promovidos)}, esperava 5"
    assert len([r for r in resgates if r["boletim"] == "contencioso-civel"]) == 5

    # A recusa sai da lista de rejeitados de quem foi promovido.
    for registro in promovidos:
        assert not any(
            r.get("boletim") == "contencioso-civel" for r in registro["boletins_rejeitados"]
        )

    # E quem nao foi promovido continua recusado.
    for registro in itens:
        if "contencioso-civel" not in registro["boletins"]:
            assert any(
                r.get("boletim") == "contencioso-civel" for r in registro["boletins_rejeitados"]
            )


def teste_resgate_identifica_o_item_para_a_curadoria():
    itens = [
        item(
            "SENACON | Notícias",
            "Publicacao",
            ["regulatorio-oleo-gas"],
            [{"boletim": "contencioso-civel", "motivo": "Possivel, mas insuficiente."}],
        )
    ]

    gb.resgatar_por_escassez(itens, 5)

    registro = itens[0]
    assert registro["motivo_filtragem"].startswith("[Resgatado por escassez:")
    assert "Radar Solução de Conflitos" in registro["motivo_filtragem"]
    assert "Motivo original." in registro["motivo_filtragem"]
    assert registro["resgates"][0]["boletim"] == "contencioso-civel"
    assert registro["resgates"][0]["motivo_da_recusa"] == "Possivel, mas insuficiente."


def teste_resgate_respeita_o_filtro_1():
    """
    A matriz continua mandando: fonte nao mapeada para o Radar nao e
    promovida, nem quando o Radar esta vazio.
    """
    itens = [
        item(
            "INPI | Notícias",  # so alimenta propriedade-intelectual
            "Publicacao do INPI",
            ["propriedade-intelectual"],
            [{"boletim": "contencioso-civel", "motivo": "Possivel, mas insuficiente."}],
        )
    ]

    resgates = gb.resgatar_por_escassez(itens, 5)

    assert resgates == [], resgates
    assert itens[0]["boletins"] == ["propriedade-intelectual"]


def teste_resgate_ignora_recusa_do_filtro_1():
    """Recusa escrita pelo Filtro 1 nao e opiniao da IA: nao vira resgate."""
    itens = [
        item(
            "SENACON | Notícias",
            "Publicacao",
            ["regulatorio-oleo-gas"],
            [{"boletim": "contencioso-civel", "motivo": "Filtro 1: fonte 'x' não está mapeada"}],
        )
    ]
    assert gb.resgatar_por_escassez(itens, 5) == []


def teste_resgate_nao_toca_radar_cheio():
    itens = [
        item(
            "SENACON | Notícias",
            f"Publicacao {i}",
            ["contencioso-civel"],
            [],
        )
        for i in range(5)
    ]
    itens.append(
        item(
            "SENACON | Notícias",
            "Candidata",
            ["regulatorio-oleo-gas"],
            [{"boletim": "contencioso-civel", "motivo": "Possivel, mas insuficiente."}],
        )
    )

    resgates = gb.resgatar_por_escassez(itens, 5)

    assert [r for r in resgates if r["boletim"] == "contencioso-civel"] == []
    assert "contencioso-civel" not in itens[-1]["boletins"]


def teste_resgate_nao_promove_excluido_por_conteudo_institucional():
    itens = [
        item(
            "SENACON | Notícias",
            "Aviso de pauta",
            [],
            [{"boletim": "contencioso-civel", "motivo": "Possivel, mas insuficiente."}],
            exclusao_editorial_automatica="Comunicação institucional.",
        )
    ]
    assert gb.resgatar_por_escassez(itens, 5) == []
    assert itens[0]["boletins"] == []


def teste_resgate_mantem_a_ordem_dos_slugs():
    itens = [
        item(
            "Planalto | Resenha Diaria",
            "Publicacao",
            ["regulatorio-oleo-gas"],
            [{"boletim": "direito-tributario", "motivo": "Possivel, mas insuficiente."}],
        )
    ]
    gb.resgatar_por_escassez(itens, 5)
    boletins = itens[0]["boletins"]
    assert boletins == [s for s in gb.SLUGS if s in boletins], boletins


def teste_piso_zero_desliga_o_resgate():
    itens = [
        item(
            "SENACON | Notícias",
            "Publicacao",
            [],
            [{"boletim": "contencioso-civel", "motivo": "Possivel, mas insuficiente."}],
        )
    ]
    assert gb.resgatar_por_escassez(itens, 0) == []


# ---------------------------------------------------------------------------
# Cascata do Gemini: cada erro com a sua resposta
# ---------------------------------------------------------------------------


class ErroFalso(Exception):
    """Imita os erros do google-genai, que trazem o codigo HTTP em .code."""

    def __init__(self, codigo, mensagem):
        super().__init__(f"{codigo} {mensagem}")
        self.code = codigo


class ClienteFalso:
    """Cada modelo devolve, na ordem, o que o roteiro manda; o ultimo passo se repete."""

    def __init__(self, roteiro):
        self.roteiro = {modelo: list(passos) for modelo, passos in roteiro.items()}
        self.chamadas = []
        self.models = self

    def generate_content(self, model, contents, config):
        self.chamadas.append(model)
        passos = self.roteiro.get(model) or [ErroFalso(503, "UNAVAILABLE")]
        passo = passos.pop(0) if len(passos) > 1 else passos[0]
        if isinstance(passo, Exception):
            raise passo
        return types.SimpleNamespace(text=json.dumps(passo))


def com_esperas_registradas(funcao):
    esperas = []
    original, gb.time.sleep = gb.time.sleep, esperas.append
    try:
        return funcao(), esperas
    finally:
        gb.time.sleep = original


def teste_503_espera_e_repete_no_mesmo_modelo():
    primeiro = gb.MODELOS[0]
    cliente = ClienteFalso({primeiro: [ErroFalso(503, "UNAVAILABLE"), ErroFalso(503, "UNAVAILABLE"), {"itens": []}]})
    orcamento = {"espera": 0}

    (dados, modelo, logs), esperas = com_esperas_registradas(lambda: gb.gemini(cliente, "P", orcamento))

    assert modelo == primeiro, f"desceu para {modelo}"
    assert esperas == [30, 60], esperas
    assert orcamento["espera"] == 90, orcamento
    assert [t.get("tipo_erro") for t in logs if t["status"] == "erro"] == ["sobrecarga", "sobrecarga"]


def teste_503_persistente_desce_so_depois_das_esperas():
    primeiro, segundo = gb.MODELOS[0], gb.MODELOS[1]
    cliente = ClienteFalso({primeiro: [ErroFalso(503, "UNAVAILABLE")], segundo: [{"itens": []}]})

    (dados, modelo, logs), esperas = com_esperas_registradas(lambda: gb.gemini(cliente, "P", {"espera": 0}))

    assert modelo == segundo
    assert esperas == list(gb.ESPERAS_SOBRECARGA), esperas
    assert cliente.chamadas.count(primeiro) == len(gb.ESPERAS_SOBRECARGA) + 1


def teste_429_desce_na_hora_e_guarda_a_mensagem_inteira():
    primeiro, segundo = gb.MODELOS[0], gb.MODELOS[1]
    mensagem = (
        "RESOURCE_EXHAUSTED. Quota exceeded for metric: "
        "generate_content_free_tier_input_token_count, limit: 250000 " + "detalhe " * 120
    )
    cliente = ClienteFalso({primeiro: [ErroFalso(429, mensagem)], segundo: [{"itens": []}]})

    (dados, modelo, logs), esperas = com_esperas_registradas(lambda: gb.gemini(cliente, "P", {"espera": 0}))

    assert modelo == segundo
    assert esperas == [], f"nao devia esperar no 429: {esperas}"
    assert cliente.chamadas.count(primeiro) == 1
    assert logs[0]["tipo_erro"] == "cota"
    assert len(logs[0]["erro"]) > 400, "a mensagem do 429 foi cortada"
    assert "input_token_count" in logs[0]["erro"]


def teste_teto_de_espera_faz_a_cascata_descer_sem_esperar():
    primeiro, segundo = gb.MODELOS[0], gb.MODELOS[1]
    cliente = ClienteFalso({
        primeiro: [ErroFalso(503, "UNAVAILABLE")],
        segundo: [ErroFalso(503, "UNAVAILABLE"), {"itens": []}],
    })
    orcamento = {"espera": gb.TETO_ESPERA_SOBRECARGA - 10}

    (dados, modelo, logs), esperas = com_esperas_registradas(lambda: gb.gemini(cliente, "P", orcamento))

    assert modelo == segundo
    assert esperas == [10], esperas
    assert orcamento["espera"] == gb.TETO_ESPERA_SOBRECARGA - 10, "espera dos modelos seguintes nao conta no teto"


def teste_resposta_invalida_repete_uma_vez_e_desce():
    primeiro, segundo = gb.MODELOS[0], gb.MODELOS[1]
    cliente = ClienteFalso({primeiro: [{"sem": "itens"}], segundo: [{"itens": [{"titulo": "x"}]}]})

    (dados, modelo, logs), esperas = com_esperas_registradas(lambda: gb.gemini(cliente, "P", {"espera": 0}))

    assert modelo == segundo and dados["itens"] == [{"titulo": "x"}]
    assert esperas == [10], esperas
    assert [t["tipo_erro"] for t in logs if t["status"] == "erro"] == ["outro", "outro"]


def teste_resumo_da_cascata_aponta_a_queda():
    lotes = [
        {"lote": 1, "fontes": ["A"], "modelo": gb.MODELOS[0], "espera_por_sobrecarga_s": 90},
        {"lote": 2, "fontes": ["B"], "modelo": gb.MODELOS[3], "espera_por_sobrecarga_s": 210},
        {"lote": 3, "fontes": ["C"], "modelo": "", "espera_por_sobrecarga_s": 0},
    ]
    resumo = gb.resumo_cascata(lotes)
    assert resumo["lotes_fora_do_preferido"] == 2
    assert resumo["espera_por_sobrecarga_s"] == 300
    assert "lote 2" in resumo["aviso"] and "lote 3" in resumo["aviso"]
    assert resumo["lotes"][2]["modelo"] == "falhou"
    assert gb.resumo_cascata(lotes[:1])["aviso"] == ""


# ---------------------------------------------------------------------------
# Busca complementar: uma por escopo, repartida entre as fontes
# ---------------------------------------------------------------------------

ANP = "https://www.gov.br/anp/pt-br"
# Coletadas pelo Firecrawl ("coleta" ausente) e com "busca": true, que e o que
# faz a busca complementar rodar.
FONTES_ANP = [
    {"fonte": "ANP | Notícias", "categoria": "Energia", "url": f"{ANP}/canais_atendimento/imprensa/noticias-comunicados", "pagina_inteira": True, "busca": True},
    {"fonte": "ANP | Consultas e Audiências Públicas", "categoria": "Energia", "url": f"{ANP}/assuntos/consultas-e-audiencias-publicas/consulta-audiencia-publica", "busca": True},
    {"fonte": "ANP | Consultas Prévias", "categoria": "Energia", "url": f"{ANP}/assuntos/consultas-e-audiencias-publicas/consulta-previa", "busca": True},
    {"fonte": "ANP | Pautas e Atas", "categoria": "Energia", "url": f"{ANP}/composicao/diretoria-colegiada/pautas", "busca": True},
]
ANEEL = {"fonte": "ANEEL | Últimas Notícias", "categoria": "Energia", "url": "https://www.gov.br/aneel/pt-br/assuntos/noticias"}
ACHADOS_ANP = [
    (f"{ANP}/canais_atendimento/imprensa/noticias-comunicados/anp-publica-painel", "ANP publica painel", "d1"),
    (f"{ANP}/assuntos/consultas-e-audiencias-publicas/consulta-audiencia-publica/2026/cp-12", "Consulta publica 12", "d2"),
    (f"{ANP}/assuntos/consultas-e-audiencias-publicas/consulta-previa/cp-3", "Consulta previa 3", "d3"),
    (f"{ANP}/assuntos/precos/boletim-semanal", "Boletim semanal de precos", "d4"),
    (f"{ANP}/assuntos/consultas-e-audiencias-publicas/consulta-audiencia-publica", "A propria listagem", "d5"),
]


class FirecrawlFalso:
    def __init__(self, paginas, achados):
        self.paginas, self.achados = paginas, achados
        self.coletas, self.buscas = [], []

    def scrape(self, url, formats=None, only_main_content=True):
        self.coletas.append(url)
        pagina = self.paginas[url]
        if isinstance(pagina, Exception):
            raise pagina
        return types.SimpleNamespace(markdown=pagina)

    def search(self, consulta, limit=10):
        self.buscas.append(consulta)
        alvo = consulta.split()[0][len("site:"):]
        return types.SimpleNamespace(web=[
            types.SimpleNamespace(url=u, title=t, description=d) for u, t, d in self.achados.get(alvo, [])
        ])


def paginas_padrao(**trocas):
    paginas = {f["url"]: "listagem " * 5000 for f in FONTES_ANP}  # 45 mil: pede busca
    paginas[ANEEL["url"]] = "noticia " * 1500  # 12 mil: nao pede
    paginas.update(trocas)
    return paginas


def coletar_falso(paginas, achados=None):
    import datetime

    fc = FirecrawlFalso(paginas, {"www.gov.br/anp/pt-br": ACHADOS_ANP} if achados is None else achados)
    dia = datetime.date(2026, 9, 29)
    material, buscas = gb.coletar(fc, FONTES_ANP + [ANEEL], dia, dia, pausa=0)
    return fc, material, buscas


def teste_busca_e_paga_uma_vez_por_escopo():
    fc, material, buscas = coletar_falso(paginas_padrao())

    assert len(fc.buscas) == 1, fc.buscas
    assert fc.buscas[0].startswith("site:www.gov.br/anp/pt-br ")
    assert len(buscas) == 1 and buscas[0]["resultados"] == 4, buscas
    assert gb.creditos_estimados(material, buscas)["total"] == 5 + gb.CREDITOS_POR_BUSCA


def teste_resultado_da_busca_vai_para_a_fonte_mais_especifica():
    fc, material, buscas = coletar_falso(paginas_padrao())
    por_fonte = {m["fonte"]: [d["titulo"] for d in m["descobertas"]] for m in material}

    assert por_fonte["ANP | Notícias"] == ["ANP publica painel", "Boletim semanal de precos"], por_fonte
    assert por_fonte["ANP | Consultas e Audiências Públicas"] == ["Consulta publica 12"]
    assert por_fonte["ANP | Consultas Prévias"] == ["Consulta previa 3"]
    assert por_fonte["ANP | Pautas e Atas"] == []
    assert por_fonte["ANEEL | Últimas Notícias"] == []


def teste_cada_publicacao_entra_uma_vez_no_dossier():
    fc, material, buscas = coletar_falso(paginas_padrao())
    dossier, processadas = gb.montar_dossier(material)

    for url, titulo, _ in ACHADOS_ANP[:4]:
        vezes = sum(entrada["conteudo"].count(f"URL: {url}\n") for entrada in dossier)
        assert vezes == 1, f"{titulo} aparece {vezes} vez(es) no dossier"
    propria = ACHADOS_ANP[4][0]
    assert all(f"URL: {propria}\n" not in entrada["conteudo"] for entrada in dossier), "a propria listagem entrou"

    consultas = next(p for p in processadas if p["fonte"] == "ANP | Consultas e Audiências Públicas")
    assert consultas["busca_complementar_executada"] and consultas["escopo_busca"] == "www.gov.br/anp/pt-br"
    assert "ANP | Notícias" in consultas["busca_compartilhada_com"]


def teste_busca_nao_vai_para_pagina_com_erro():
    trocas = {FONTES_ANP[0]["url"]: "Conteúdo restrito " * 400}
    fc, material, buscas = coletar_falso(paginas_padrao(**trocas))
    por_fonte = {m["fonte"]: m for m in material}

    assert por_fonte["ANP | Notícias"]["status"] == "erro_conteudo_origem"
    assert por_fonte["ANP | Notícias"]["descobertas"] == []
    # O que era da fonte com erro, e o que nao casava com ninguem, fica com a
    # primeira fonte de pe do escopo, em vez de sumir.
    titulos = [d["titulo"] for d in por_fonte["ANP | Consultas e Audiências Públicas"]["descobertas"]]
    assert "ANP publica painel" in titulos and "Boletim semanal de precos" in titulos, titulos
    assert sum(len(m["descobertas"]) for m in material) == 4


def teste_escopo_todo_com_erro_nao_gasta_busca():
    trocas = {f["url"]: RuntimeError("timeout") for f in FONTES_ANP}
    fc, material, buscas = coletar_falso(paginas_padrao(**trocas))

    assert fc.buscas == [], "gastou busca num escopo sem nenhuma pagina de pe"
    assert all(m["status"] == "erro" for m in material if m["fonte"].startswith("ANP"))
    assert gb.creditos_estimados(material, buscas)["buscas"] == 0


def teste_pagina_pequena_com_resultado_de_busca_nao_e_descartada():
    trocas = {FONTES_ANP[1]["url"]: "curta"}
    fc, material, buscas = coletar_falso(paginas_padrao(**trocas))
    dossier, processadas = gb.montar_dossier(material)
    consultas = next(p for p in processadas if p["fonte"] == "ANP | Consultas e Audiências Públicas")
    assert consultas["status"] == "ok", consultas
    assert consultas["publicacoes_localizadas"] == 1


# ---------------------------------------------------------------------------
# Dossier guardado
# ---------------------------------------------------------------------------


def teste_dossier_guardado_refaz_o_mesmo_dossier():
    grande = "pagina grande " * 6000  # 84 mil, acima do que fica guardado
    trocas = {FONTES_ANP[0]["url"]: grande, FONTES_ANP[3]["url"]: RuntimeError("timeout")}
    fc, material, buscas = coletar_falso(paginas_padrao(**trocas))
    original = gb.montar_dossier(material)

    with tempfile.TemporaryDirectory() as pasta:
        pasta = Path(pasta)
        (pasta / "fonte-que-saiu.md").write_text("velho", encoding="utf-8")
        gb.salvar_dossier(material, {"data_execucao": "2026-09-29", "buscas_complementares": buscas}, pasta=pasta)

        assert not (pasta / "fonte-que-saiu.md").exists(), "arquivo de fonte antiga ficou para tras"
        guardada = (pasta / "anp-noticias.md").read_text(encoding="utf-8")
        assert len(guardada) == gb.LIMITE_PAGINA_GUARDADA

        indice, recuperado = gb.carregar_dossier(pasta=pasta)
        assert indice["data_execucao"] == "2026-09-29"
        assert indice["buscas_complementares"] == buscas

    refeito = gb.montar_dossier(recuperado)
    assert refeito == original, "o dossier refeito do disco difere do original"


# ---------------------------------------------------------------------------
# Coleta sem Firecrawl
# ---------------------------------------------------------------------------

import datetime as _dt

import coleta_direta as cd  # noqa: E402

INICIO, FIM = _dt.date(2026, 9, 29), _dt.date(2026, 9, 30)


class ClienteHttpFalso:
    """Responde por URL (ou pelo comeco dela) o que o teste manda."""

    def __init__(self, respostas):
        self.respostas = respostas
        self.pedidos = []
        self.requisicoes = 0

    def baixar(self, url, aceitar=None, extras=None):
        self.pedidos.append(url)
        self.requisicoes += 1
        resposta = next((v for k, v in self.respostas.items() if url.startswith(k)), (404, ""))
        status, texto = resposta
        return {"url": url, "status": status, "erro": "" if status == 200 else f"HTTP {status}", "tipo": "",
                "bytes": len(texto), "ms": 0, "url_final": url, "texto": texto, "corpo": texto.encode(), "bloqueio": ""}


LINHA_RECEITA = """<tr class='linhaResultados'>
 <!-- <td width="10%"><a href='link.action?idAto=153836'>Ato Declaratório Executivo</a></td> -->
 <td width="10%"><a href='https://normasinternet2.receita.fazenda.gov.br/#/consulta/externa/153836/vs/MTU=' target="_blank"> Ato Declarat&#xF3;rio Executivo </a></td>
 <td width="10%"><a href='https://normasinternet2.receita.fazenda.gov.br/#/consulta/externa/153836/vs/MTU='> 79 </a></td>
 <td width="10%"><div><a href='https://normasinternet2.receita.fazenda.gov.br/#/consulta/externa/153836/vs/MTU='> Corat</a></div></td>
 <td width="10%"><a href='https://normasinternet2.receita.fazenda.gov.br/#/consulta/externa/153836/vs/MTU='> {data} </a></td>
 <td><a href='https://normasinternet2.receita.fazenda.gov.br/#/consulta/externa/153836/vs/MTU='>Divulga a taxa de juros aplicável.</a></td>
</tr>"""


def teste_receita_le_as_linhas_da_tabela():
    html_texto = "<table><thead></thead><tbody>" + LINHA_RECEITA.format(data="29/09/2026") + LINHA_RECEITA.format(data="25/09/2026").replace("153836", "153801") + "</tbody></table>"
    publicacoes = cd.ler_linhas_receita(html_texto)
    assert [p["data"] for p in publicacoes] == ["2026-09-29", "2026-09-25"], publicacoes
    assert publicacoes[0]["titulo"] == "Ato Declaratório Executivo Corat nº 79", publicacoes[0]
    assert publicacoes[0]["url"].endswith("/consulta/externa/153836")
    assert publicacoes[0]["descricao"] == "Divulga a taxa de juros aplicável."


def teste_receita_segue_a_paginacao_ate_sair_da_janela():
    url = "http://normas.exemplo/consulta.action?ordem=DESC&p=1"
    pagina1 = LINHA_RECEITA.format(data="30/09/2026") * 3
    pagina2 = LINHA_RECEITA.format(data="29/09/2026") + LINHA_RECEITA.format(data="26/09/2026")
    cliente = ClienteHttpFalso({url: (200, pagina1), url.replace("p=1", "p=2"): (200, pagina2)})
    coleta = cd.coletar(cliente, {"fonte": "Receita", "url": url, "coleta": "receita"}, INICIO, FIM)
    assert len(cliente.pedidos) == 2, cliente.pedidos
    assert coleta["listadas"] == 5
    assert sum(p["enviar"] for p in coleta["publicacoes"]) == 4


def teste_b3_le_a_data_de_dois_digitos_e_o_pdf():
    texto = (
        "[29/09/26 062-2026-VPC-Ofício Circular Deslistagem do Futuro de S&P Merval](https://www.b3.com.br/x/#panel0a)\n\n"
        "A negociação do contrato será descontinuada a partir de 01/10/2026.\n\n"
        "[Download do Documento](https://www.b3.com.br/data/files/OC%20062.pdf)\n\n"
        "[25/09/26 047-2026-VNC-Ofício Circular Prorrogação](https://www.b3.com.br/x/#panel1a)\n\nOutra chamada.\n"
    )
    publicacoes = cd.ler_oficios_b3(texto)
    assert [p["data"] for p in publicacoes] == ["2026-09-29", "2026-09-25"]
    assert publicacoes[0]["url"].endswith("OC%20062.pdf")
    assert publicacoes[0]["titulo"].startswith("062-2026-VPC")
    assert "descontinuada" in publicacoes[0]["descricao"] and "Download" not in publicacoes[0]["descricao"]


def teste_volto_usa_a_api_e_devolve_o_endereco_publico():
    resposta = json.dumps({"items": [
        {"@id": "https://www.gov.br/anatel/++api++/pt-br/assuntos/noticias/n1", "@type": "News Item", "title": "N1", "description": "D1", "effective": "2026-09-29T10:00:00-03:00"},
        {"@id": "https://www.gov.br/anatel/++api++/pt-br/assuntos/noticias/n0", "@type": "News Item", "title": "N0", "description": "D0", "effective": "2026-09-20T10:00:00-03:00"},
    ]})
    cliente = ClienteHttpFalso({"https://www.gov.br/anatel/++api++/pt-br/assuntos/noticias/@search": (200, resposta)})
    coleta = cd.coletar(cliente, {"fonte": "ANATEL", "url": "https://www.gov.br/anatel/pt-br/assuntos/noticias", "coleta": "volto"}, INICIO, FIM)
    assert "portal_type=News%20Item" in cliente.pedidos[0]
    assert coleta["publicacoes"][0]["url"] == "https://www.gov.br/anatel/pt-br/assuntos/noticias/n1"
    assert [p["enviar"] for p in coleta["publicacoes"]] == [True, False]


def teste_bc_sem_normativo_na_janela_confere_se_a_api_responde():
    vazio = json.dumps({"TotalRows": 0, "Rows": []})
    ultimos = json.dumps({"Rows": [{"Title": "Comunicado 1", "Data1OWSDATE": "2026-09-20T03:00:00Z"}]})
    cliente = ClienteHttpFalso({cd.BCB_BUSCA.format(linhas=100, filtro="")[:60]: (200, vazio)})
    cliente.respostas = {"https://www.bcb.gov.br/api/search/app/normativos/buscanormativos?querytext=ContentType:normativo%20AND%20contentSource:normativos&rowlimit=100": (200, vazio),
                         "https://www.bcb.gov.br/api/search/app/normativos/buscanormativos?querytext=ContentType:normativo%20AND%20contentSource:normativos&rowlimit=5": (200, ultimos)}
    coleta = cd.coletar(cliente, {"fonte": "BC", "url": "x", "coleta": "api_bcb"}, INICIO, FIM)
    assert coleta["publicacoes"] == [] and coleta["listadas"] == 1, coleta
    assert len(cliente.pedidos) == 2


def teste_listagem_tira_menu_sem_data_e_respeita_o_padrao_de_link():
    base = "https://www.exemplo.gov.br/orgao/pt-br/noticias"
    html_texto = ("<div id='content-core'>"
                  + "".join(f"<article><a href='{base}/n{i}'>Publicação número {i} da listagem</a><span>2{i}/09/2026</span></article>" for i in range(6, 10))
                  + f"<a href='{base}/menu'>Link de menu sem data qualquer</a></div>")
    html_texto = html_texto.replace("id='content-core'", 'id="content-core"')
    cliente = ClienteHttpFalso({base: (200, html_texto)})
    coleta = cd.coletar(cliente, {"fonte": "X", "url": base, "coleta": "html"}, INICIO, FIM)
    assert coleta["listadas"] == 4, [p["titulo"] for p in coleta["publicacoes"]]
    assert [p["data"] for p in coleta["publicacoes"] if p["enviar"]] == ["2026-09-29"], coleta["publicacoes"]
    coleta = cd.coletar(ClienteHttpFalso({base: (200, html_texto)}), {"fonte": "X", "url": base, "coleta": "html", "padrao_link": "/n9"}, INICIO, FIM)
    assert coleta["listadas"] == 1


def teste_pagina_do_ano_da_anp_so_le_o_que_esta_dentro_do_ano():
    base = "https://www.gov.br/anp/pt-br/assuntos/consultas/consulta-previa"
    html_texto = ('<div id="content-core">'
                  f"<a href='{base}/2026/cp-2'>Consulta Prévia nº 2/2026 aberta hoje</a> 29/09/2026 "
                  f"<a href='{base}/2026/cp-1'>Consulta Prévia nº 1/2026 com audiência</a> 13/10/2026 "
                  "<a href='https://www.gov.br/anp/pt-br/assuntos/air'>Análise de Impacto Regulatório do menu</a></div>")
    cliente = ClienteHttpFalso({f"{base}/2026": (200, html_texto)})
    coleta = cd.coletar(cliente, {"fonte": "ANP", "url": base, "coleta": "anp_ano"}, INICIO, FIM)
    assert coleta["listadas"] == 2, coleta["publicacoes"]
    # Data futura pode ser a da audiencia: vai ao Gemini em vez de sumir.
    assert all(p["enviar"] for p in coleta["publicacoes"])


def teste_metodo_desconhecido_e_falha():
    try:
        cd.coletar(ClienteHttpFalso({}), {"fonte": "X", "url": "x", "coleta": "firecrawl"}, INICIO, FIM)
    except cd.FalhaColeta:
        return
    raise AssertionError("devia ter falhado")


def teste_bloqueio_e_falha_sem_nova_tentativa():
    cliente = ClienteHttpFalso({"https://x.gov.br/l": (403, "")})
    try:
        cd.coletar(cliente, {"fonte": "X", "url": "https://x.gov.br/l", "coleta": "html"}, INICIO, FIM)
    except cd.FalhaColeta as erro:
        assert "403" in str(erro)
        assert len(cliente.pedidos) == 1
        return
    raise AssertionError("devia ter falhado")


# --- no pipeline -------------------------------------------------------------

def publicacao(titulo, data, enviar=True):
    return {"titulo": titulo, "url": f"https://x.gov.br/{titulo}", "data": data, "hora": "", "descricao": "d", "na_janela": enviar and bool(data), "enviar": enviar}


def coletor_falso(respostas):
    def coletor(cliente, fonte, inicio, fim):
        resposta = respostas[fonte["fonte"]]
        if isinstance(resposta, Exception):
            raise resposta
        return {"publicacoes": resposta, "listadas": len(resposta), "texto": "pagina", "requisicoes": 1}
    return coletor


FONTES_NOVAS = [
    {"fonte": "Direta", "categoria": "C", "url": "https://x.gov.br/direta", "coleta": "html"},
    {"fonte": "Quebrada", "categoria": "C", "url": "https://x.gov.br/quebrada", "coleta": "html"},
    {"fonte": "Vazia", "categoria": "C", "url": "https://x.gov.br/vazia", "coleta": "html"},
    {"fonte": "Pelo Firecrawl", "categoria": "C", "url": "https://y.gov.br/fc"},
]


def coletar_novo(respostas, historico=None, fontes=FONTES_NOVAS):
    fc = FirecrawlFalso({f["url"]: "pagina do firecrawl " * 100 for f in fontes}, {})
    material, buscas = gb.coletar(fc, fontes, INICIO, FIM, pausa=0, cliente=object(), historico=historico or {}, coletor=coletor_falso(respostas))
    return fc, {m["fonte"]: m for m in material}, material, buscas


def teste_fonte_gratuita_nao_gasta_firecrawl_e_a_que_falha_cai_para_ele():
    respostas = {"Direta": [publicacao("a", "2026-09-29")], "Quebrada": cd.FalhaColeta("listagem: HTTP 500"), "Vazia": [publicacao("b", "2026-09-01", enviar=False)]}
    fc, por_fonte, material, buscas = coletar_novo(respostas)
    assert sorted(fc.coletas) == ["https://x.gov.br/quebrada", "https://y.gov.br/fc"], fc.coletas
    assert por_fonte["Direta"]["metodo_usado"] == "html" and por_fonte["Direta"]["creditos_firecrawl"] == 0
    assert por_fonte["Quebrada"]["queda_firecrawl"] and "HTTP 500" in por_fonte["Quebrada"]["motivo_queda"]
    assert por_fonte["Quebrada"]["metodo_usado"] == "firecrawl" and por_fonte["Quebrada"]["creditos_firecrawl"] == 1
    creditos = gb.creditos_estimados(material, buscas)
    assert creditos["coletas"] == 2 and creditos["quedas_para_firecrawl"] == 1 and creditos["total"] == 2


def teste_zero_publicacoes_e_falha_quando_a_fonte_costuma_trazer():
    respostas = {"Direta": [], "Quebrada": [], "Vazia": [], }
    fontes = FONTES_NOVAS[:3]
    fc, por_fonte, _, _ = coletar_novo(respostas, historico={"Direta": 12, "Quebrada": None, "Vazia": 0}, fontes=fontes)
    assert por_fonte["Direta"]["queda_firecrawl"] and "anterior: 12" in por_fonte["Direta"]["motivo_queda"]
    assert por_fonte["Quebrada"]["queda_firecrawl"], "sem historico, zero tambem e falha"
    assert not por_fonte["Vazia"]["queda_firecrawl"], "fonte que ja vinha vazia pode continuar vazia"
    assert "https://x.gov.br/vazia" not in fc.coletas


def teste_dossier_leva_so_o_que_interessa_e_registra_fonte_sem_janela():
    respostas = {"Direta": [publicacao("na-janela", "2026-09-29"), publicacao("sem-data", ""), publicacao("antiga", "2026-09-01", enviar=False)],
                 "Quebrada": [publicacao("outra", "2026-09-30")], "Vazia": [publicacao("velha", "2026-09-10", enviar=False)]}
    _, _, material, _ = coletar_novo(respostas)
    dossier, processadas = gb.montar_dossier(material)
    por_fonte = {d["fonte"]: d for d in dossier}
    assert "https://x.gov.br/na-janela" in por_fonte["Direta"]["conteudo"]
    assert "https://x.gov.br/sem-data" in por_fonte["Direta"]["conteudo"], "sem data nunca sai"
    assert "https://x.gov.br/antiga" not in por_fonte["Direta"]["conteudo"]
    assert "Vazia" not in por_fonte, "fonte sem nada na janela nao vai ao Gemini"
    vazia = next(p for p in processadas if p["fonte"] == "Vazia")
    assert vazia["sem_publicacao_na_janela"] and vazia["publicacoes_listadas"] == 1
    direta = next(p for p in processadas if p["fonte"] == "Direta")
    assert (direta["metodo_usado"], direta["publicacoes_na_janela"], direta["publicacoes_enviadas"]) == ("html", 1, 2)


def teste_dossier_estruturado_se_refaz_do_disco():
    respostas = {"Direta": [publicacao("a", "2026-09-29"), publicacao("b", "")], "Quebrada": cd.FalhaColeta("x"), "Vazia": []}
    _, _, material, buscas = coletar_novo(respostas, historico={"Vazia": 0})
    original = gb.montar_dossier(material)
    with tempfile.TemporaryDirectory() as pasta:
        gb.salvar_dossier(material, {"data_execucao": "2026-09-30", "buscas_complementares": buscas}, pasta=Path(pasta))
        _, recuperado = gb.carregar_dossier(pasta=Path(pasta))
        assert gb.historico_de_listagem(Path(pasta)) == {"Direta": 2, "Quebrada": None, "Vazia": 0, "Pelo Firecrawl": None}
    assert gb.montar_dossier(recuperado) == original


def teste_busca_so_roda_onde_a_fonte_pede():
    fontes = [dict(FONTES_NOVAS[0], busca=True), FONTES_NOVAS[3]]
    fc = FirecrawlFalso({f["url"]: "pagina " * 1000 for f in fontes}, {"x.gov.br": [("https://x.gov.br/achado", "Achado", "d")]})
    material, buscas = gb.coletar(fc, fontes, INICIO, FIM, pausa=0, cliente=object(), coletor=coletor_falso({"Direta": [publicacao("a", "2026-09-29")]}))
    assert [b["escopo"] for b in buscas] == ["x.gov.br"], buscas
    direta = material[0]
    assert direta["creditos_firecrawl"] == gb.CREDITOS_POR_BUSCA and direta["descobertas"][0]["titulo"] == "Achado"


def teste_fonte_reativada_com_erro_vai_para_o_log():
    ativas = [{"fonte": "COAF", "suspenso": True, "reativar_em": "2026-10-26", "motivo_suspensao": "Defeso eleitoral"}, {"fonte": "Outra"}]
    processadas = [{"fonte": "COAF", "status": "erro_conteudo_origem", "erro": "Conteúdo restrito"}, {"fonte": "Outra", "status": "erro"}]
    avisos = gb.fontes_reativadas_com_erro(ativas, processadas, _dt.date(2026, 10, 27))
    assert [a["fonte"] for a in avisos] == ["COAF"] and avisos[0]["erro"] == "Conteúdo restrito"
    assert gb.fontes_reativadas_com_erro(ativas, [{"fonte": "COAF", "status": "ok"}], _dt.date(2026, 10, 27)) == []


def teste_coleta_do_fontes_json_e_valida():
    fontes = json.loads((BASE / "fontes.json").read_text(encoding="utf-8"))
    for fonte in fontes:
        assert fonte.get("coleta", "firecrawl") in set(cd.METODOS) | {"firecrawl"}, fonte
    com_busca = sorted(f["fonte"] for f in fontes if f.get("busca"))
    assert com_busca == ["CVM | Notícias", "Ministério da Agricultura | Notícias"], com_busca
    coaf = next(f for f in fontes if f["fonte"].startswith("COAF"))
    assert coaf["suspenso"] and coaf["reativar_em"] == "2026-10-26" and coaf["motivo_suspensao"] == "Defeso eleitoral"
    mme = next(f for f in fontes if f["fonte"] == "MME | Consultas Públicas")
    assert mme["suspenso"] and "reativar_em" not in mme


TESTES = [
    teste_busca_sobrevive_em_pagina_grande,
    teste_sem_busca_o_comportamento_nao_muda,
    teste_pagina_pequena_cabe_inteira,
    teste_bloco_da_busca_tem_teto,
    teste_lotes_cobrem_todas_as_fontes,
    teste_lote_que_falha_nao_derruba_os_outros,
    teste_todos_os_lotes_falhando_devolve_nada,
    teste_resgate_preenche_ate_o_piso,
    teste_resgate_identifica_o_item_para_a_curadoria,
    teste_resgate_respeita_o_filtro_1,
    teste_resgate_ignora_recusa_do_filtro_1,
    teste_resgate_nao_toca_radar_cheio,
    teste_resgate_nao_promove_excluido_por_conteudo_institucional,
    teste_resgate_mantem_a_ordem_dos_slugs,
    teste_piso_zero_desliga_o_resgate,
    teste_503_espera_e_repete_no_mesmo_modelo,
    teste_503_persistente_desce_so_depois_das_esperas,
    teste_429_desce_na_hora_e_guarda_a_mensagem_inteira,
    teste_teto_de_espera_faz_a_cascata_descer_sem_esperar,
    teste_resposta_invalida_repete_uma_vez_e_desce,
    teste_resumo_da_cascata_aponta_a_queda,
    teste_busca_e_paga_uma_vez_por_escopo,
    teste_resultado_da_busca_vai_para_a_fonte_mais_especifica,
    teste_cada_publicacao_entra_uma_vez_no_dossier,
    teste_busca_nao_vai_para_pagina_com_erro,
    teste_escopo_todo_com_erro_nao_gasta_busca,
    teste_pagina_pequena_com_resultado_de_busca_nao_e_descartada,
    teste_dossier_guardado_refaz_o_mesmo_dossier,
    teste_receita_le_as_linhas_da_tabela,
    teste_receita_segue_a_paginacao_ate_sair_da_janela,
    teste_b3_le_a_data_de_dois_digitos_e_o_pdf,
    teste_volto_usa_a_api_e_devolve_o_endereco_publico,
    teste_bc_sem_normativo_na_janela_confere_se_a_api_responde,
    teste_listagem_tira_menu_sem_data_e_respeita_o_padrao_de_link,
    teste_pagina_do_ano_da_anp_so_le_o_que_esta_dentro_do_ano,
    teste_metodo_desconhecido_e_falha,
    teste_bloqueio_e_falha_sem_nova_tentativa,
    teste_fonte_gratuita_nao_gasta_firecrawl_e_a_que_falha_cai_para_ele,
    teste_zero_publicacoes_e_falha_quando_a_fonte_costuma_trazer,
    teste_dossier_leva_so_o_que_interessa_e_registra_fonte_sem_janela,
    teste_dossier_estruturado_se_refaz_do_disco,
    teste_busca_so_roda_onde_a_fonte_pede,
    teste_fonte_reativada_com_erro_vai_para_o_log,
    teste_coleta_do_fontes_json_e_valida,
]


def main():
    falhas = 0
    for teste in TESTES:
        try:
            teste()
        except AssertionError as erro:
            falhas += 1
            print(f"FALHOU  {teste.__name__}: {erro}")
        except Exception as erro:  # pragma: no cover
            falhas += 1
            print(f"ERRO    {teste.__name__}: {erro!r}")
        else:
            print(f"ok      {teste.__name__}")

    print("-" * 60)
    if falhas:
        print(f"{falhas} de {len(TESTES)} testes falharam.")
        raise SystemExit(1)
    print(f"{len(TESTES)} testes passaram.")


if __name__ == "__main__":
    main()
