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
  institucional, e identifica o item para a curadoria.

Uso: python scripts/testar_coleta.py
"""

import sys
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
_stub("google.genai.types", GenerateContentConfig=object)
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

    def falso_gemini(cliente, prompt):
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

    def falso_gemini(cliente, prompt):
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
    def falso_gemini(cliente, prompt):
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
