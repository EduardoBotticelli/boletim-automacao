"""
Testa a coleta do DOU pela leitura do jornal (scripts/coleta_dou.py) e a
passagem dos atos pelo gerar_boletim.py ate o e-mail.

Nao acessa rede nem usa chave: o Firecrawl e falso e as paginas sao amostras
reais da edicao de 02/10/2026 (scripts/dados_teste/dou), recortadas. O que
estes testes protegem:

- a leitura do jornal traz todos os atos do JSON embutido, com titulo, tipo,
  orgao e endereco; sem o JSON, e falha registrada;
- o filtro por orgao segue o dou.json: no Regulatorio, CADE (Secoes 1 e 3),
  MEC (Secao 3 so com Mais Medicos) e MDIC; unidades regionais e
  administrativas ficam de fora;
- so os atos que passam no filtro abrem; a serie abre um so; o teto vale;
  o ato que nao abre entra com o comeco do texto e o motivo;
- os creditos gastos ficam no log, e o DOU nao vai ao Gemini;
- o trecho do ato sai no e-mail, na secao do DOU do Radar (modelo D).

Uso: python scripts/testar_dou.py
"""

import datetime
import json
import sys
import tempfile
import types
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DADOS = BASE / "scripts" / "dados_teste" / "dou"
sys.path.insert(0, str(BASE / "scripts"))


def _stub(nome, **atributos):
    modulo = types.ModuleType(nome)
    for chave, valor in atributos.items():
        setattr(modulo, chave, valor)
    sys.modules.setdefault(nome, modulo)
    return sys.modules[nome]


# O gerar_boletim importa firecrawl e google.genai no topo; aqui nenhum dos
# dois e usado de verdade.
_stub("firecrawl", Firecrawl=object)
_stub("google")
_stub("google.genai", Client=object)
_stub("google.genai.types", GenerateContentConfig=lambda **o: o, HttpOptions=lambda **o: o)
sys.modules["google"].genai = sys.modules["google.genai"]
sys.modules["google.genai"].types = sys.modules["google.genai.types"]

import coleta_dou as cd  # noqa: E402
import gerar_boletim as gb  # noqa: E402

EDICAO = datetime.date(2026, 10, 2)
CONFIG = cd.carregar_config()


def leitura_html(secao):
    atos = json.loads((DADOS / f"leitura_{secao}.json").read_text(encoding="utf-8"))
    corpo = json.dumps({"jsonArray": atos, "section": secao}, ensure_ascii=False)
    return f'<html><body><div id="menu">Leitura do jornal</div><script id="params" type="application/json">{corpo}</script></body></html>'


def atos_de(secao):
    return cd.ler_leitura(leitura_html(secao), secao)


def radares(atos, trecho, secao="dou1"):
    ato = next(a for a in atos if trecho in a["orgao"] or trecho in a["titulo"])
    return list(cd.radares_do_ato(ato, CONFIG["secoes"][secao]["radares"], CONFIG["unidades_excluidas"]))


class Meta:
    def __init__(self, creditos=1, status=200):
        self.credits_used = creditos
        self.status_code = status


class FirecrawlFalso:
    """Devolve a leitura de cada secao e a pagina de cada ato; registra os pedidos."""

    def __init__(self, paginas=None, falhas=()):
        self.pedidos = []
        self.paginas = paginas or {}
        self.falhas = set(falhas)

    def scrape(self, url, formats=None, only_main_content=True, max_age=None):
        self.pedidos.append({"url": url, "formats": formats, "max_age": max_age})
        if any(f in url for f in self.falhas):
            raise RuntimeError("timeout do Firecrawl")
        if "leiturajornal" in url:
            secao = url.split("secao=")[1].split("&")[0]
            return types.SimpleNamespace(raw_html=leitura_html(secao), metadata=Meta())
        for trecho, arquivo in self.paginas.items():
            if trecho in url:
                return types.SimpleNamespace(raw_html=(DADOS / arquivo).read_text(encoding="utf-8"), metadata=Meta())
        return types.SimpleNamespace(raw_html="<html><div class='texto-dou'><p class='identifica'>ATO</p>"
                                              "<p class='dou-paragraph'>Texto do ato.</p></div></html>", metadata=Meta())


# ---------------------------------------------------------------------------
# Leitura do jornal
# ---------------------------------------------------------------------------


def teste_leitura_traz_todos_os_atos_com_os_campos():
    bruto = json.loads((DADOS / "leitura_dou1.json").read_text(encoding="utf-8"))
    atos = atos_de("dou1")
    assert len(atos) == len(bruto)
    cade = next(a for a in atos if "Defesa Econômica" in a["orgao"])
    assert cade["titulo"].startswith("DESPACHO DECISÓRIO Nº 31/CGAA6/SGA2/SG/CADE")
    assert cade["tipo"] == "Despacho" and cade["data"] == "2026-10-02" and cade["pagina"] > 0
    assert cade["url"].startswith("https://www.in.gov.br/web/dou/-/despacho-decisorio-n-31")
    assert cade["niveis"][:2] == ["Ministério da Justiça e Segurança Pública", "Conselho Administrativo de Defesa Econômica"]
    assert not cade["inicio_do_texto"].startswith("DESPACHO"), "o comeco do texto repete o titulo"
    assert all(a["titulo"] and a["tipo"] and a["orgao"] and a["url"] for a in atos)


def teste_leitura_sem_json_e_falha():
    try:
        cd.ler_leitura("<html><body>Manutenção programada</body></html>", "dou1")
    except cd.FalhaDou:
        return
    raise AssertionError("leitura sem o JSON dos atos devia ser falha")


# ---------------------------------------------------------------------------
# Filtro por orgao
# ---------------------------------------------------------------------------


def teste_regulatorio_segue_o_documento_na_secao_1():
    atos = atos_de("dou1")
    assert "regulatorio-oleo-gas" in radares(atos, "Conselho Administrativo de Defesa Econômica")
    assert radares(atos, "Secretaria de Educação Superior") == ["regulatorio-oleo-gas"]
    assert radares(atos, "Superintendência da Zona Franca de Manaus") == ["regulatorio-oleo-gas"], "MDIC inteiro, na Seção 1"
    assert radares(atos, "Agência Nacional de Energia Elétrica") == [], "a ANEEL tem fonte própria no Regulatório"


def teste_secao_3_so_cade_e_mais_medicos_do_mec():
    atos = atos_de("dou3")
    assert radares(atos, "Conselho Administrativo de Defesa Econômica", "dou3") == ["regulatorio-oleo-gas"]
    mec = [a for a in atos if a["niveis"][0] == "Ministério da Educação"]
    com = [a for a in mec if "Mais Médicos" in a["inicio_do_texto"]]
    sem = [a for a in mec if a not in com]
    assert com and sem
    regras = CONFIG["secoes"]["dou3"]["radares"]
    assert all(cd.radares_do_ato(a, regras, CONFIG["unidades_excluidas"]) == {"regulatorio-oleo-gas": "Ministério da Educação"} for a in com)
    assert all(not cd.radares_do_ato(a, regras, CONFIG["unidades_excluidas"]) for a in sem), "MEC na Seção 3 só com Mais Médicos"
    # Na regra com termos, a exclusão geral de unidades administrativas não vale.
    administrativo = dict(com[0], niveis=["Ministério da Educação", "Fundo Nacional de Desenvolvimento da Educação", "Diretoria de Administração"])
    assert cd.radares_do_ato(administrativo, regras, CONFIG["unidades_excluidas"]) == {"regulatorio-oleo-gas": "Ministério da Educação"}


def teste_secao_1_vai_para_os_oito_radares_do_documento_e_nao_para_o_trabalhista():
    secao1 = CONFIG["secoes"]["dou1"]["radares"]
    assert set(secao1) == set(gb.SLUGS) - {"trabalhista-empresarial"}
    assert list(CONFIG["secoes"]["dou3"]["radares"]) == ["regulatorio-oleo-gas"]
    assert gb.MAPA["Diário Oficial da União | Seção 1"] == [s for s in gb.SLUGS if s != "trabalhista-empresarial"]
    assert gb.MAPA["Diário Oficial da União | Seção 3"] == ["regulatorio-oleo-gas"]


def teste_unidades_regionais_e_tipos_fora_da_regra_ficam_de_fora():
    atos = atos_de("dou1")
    assert radares(atos, "Alfândega da Receita Federal") == []
    assert radares(atos, "Conselho da Justiça Federal") == [], "portaria administrativa do CJF"
    fcvs = next(a for a in atos if a["orgao"] == "Ministério da Fazenda/Gabinete do Ministro")
    assert fcvs["tipo"] == "Despacho" and not cd.radares_do_ato(fcvs, CONFIG["secoes"]["dou1"]["radares"], CONFIG["unidades_excluidas"])
    portaria = dict(fcvs, tipo="Portaria")
    assert "direito-tributario" in cd.radares_do_ato(portaria, CONFIG["secoes"]["dou1"]["radares"], CONFIG["unidades_excluidas"])
    spu = next(a for a in atos_de("dou3") if "Superintendência em" in a["orgao"])
    regra = {"orgao": "Secretaria do Patrimônio da União"}
    assert not cd.casa(spu, regra, CONFIG["unidades_excluidas"]) and cd.casa(spu, regra, ())


# ---------------------------------------------------------------------------
# Quais atos abrir
# ---------------------------------------------------------------------------


def _selecionados(secao="dou1"):
    atos = []
    for ato in atos_de(secao):
        achados = cd.radares_do_ato(ato, CONFIG["secoes"][secao]["radares"], CONFIG["unidades_excluidas"])
        if achados:
            atos.append(dict(ato, radares=list(achados), regras=achados))
    return atos


def teste_serie_abre_um_so_e_o_teto_vale():
    atos = _selecionados()
    mec = [a for a in atos if "Secretaria de Educação Superior" in a["orgao"]]
    assert len(mec) == 3
    abrir = cd.escolher_para_abrir(atos, limite=100)
    assert sum(1 for a in mec if a in abrir) == 1, "as portarias conjuntas iguais do MEC abrem uma só"
    assert all(a["nao_aberto"].startswith("série") and a["serie_de"] for a in mec if a not in abrir)

    atos = _selecionados()
    abrir = cd.escolher_para_abrir(atos, limite=2)
    assert len(abrir) == 2
    teto = [a for a in atos if a.get("nao_aberto", "").startswith("teto")]
    assert teto and all(a not in abrir for a in teto)
    assert cd.prioridade(abrir[0]["tipo"]) <= cd.prioridade(teto[0]["tipo"]), "norma abre antes de expediente"


# ---------------------------------------------------------------------------
# Pagina do ato
# ---------------------------------------------------------------------------


def teste_ler_ato_separa_identificacao_ementa_texto_e_assinatura():
    lido = cd.ler_ato((DADOS / "ato_suframa.html").read_text(encoding="utf-8"))
    assert lido["identifica"] == "PORTARIA SUFRAMA Nº 2.772, DE 30 DE SETEMBRO DE 2026"
    assert lido["ementa"].startswith("Aprova o projeto técnico-econômico industrial pleno")
    assert lido["paragrafos"][0].startswith("O SUPERINTENDENTE DA SUPERINTENDÊNCIA DA ZONA FRANCA")
    assert lido["assinatura"] == ["LEOPOLDO AUGUSTO MELO MONTENEGRO JÚNIOR"]
    assert not any("Acessibilidade" in p or "Imprensa Nacional" in p for p in lido["paragrafos"]), "menu e rodapé fora do texto"
    resumo, trecho = cd.resumo_e_trecho(lido, 900)
    assert resumo == lido["ementa"]
    assert trecho.startswith("O SUPERINTENDENTE") and len(trecho) <= 906 and trecho.endswith("[...]")


def teste_sem_ementa_o_resumo_junta_os_primeiros_paragrafos():
    lido = cd.ler_ato((DADOS / "ato_cade.html").read_text(encoding="utf-8"))
    assert not lido["ementa"]
    resumo, trecho = cd.resumo_e_trecho(lido, 900)
    assert resumo.startswith("Processo nº 08700.002479/2022-57") and len(resumo) > 60, resumo
    assert trecho and not trecho.startswith("Processo nº 08700.002479/2022-57 Processo"), "o trecho não repete o resumo"


def teste_pagina_sem_texto_do_ato_e_falha():
    try:
        cd.ler_ato("<html><body><p>Página não encontrada</p></body></html>")
    except cd.FalhaDou:
        return
    raise AssertionError("página sem o bloco texto-dou devia ser falha")


# ---------------------------------------------------------------------------
# Coleta com o Firecrawl falso
# ---------------------------------------------------------------------------


PAGINAS = {"portaria-suframa": "ato_suframa.html", "despacho-decisorio-n-31": "ato_cade.html"}


def teste_coleta_abre_so_o_que_passou_e_conta_os_creditos():
    fc = FirecrawlFalso(PAGINAS)
    resultado = cd.coletar(fc, ["dou1", "dou3"], EDICAO, CONFIG)
    leituras = [p for p in fc.pedidos if "leiturajornal" in p["url"]]
    assert [p["url"] for p in leituras] == [
        "https://www.in.gov.br/leiturajornal?secao=dou1&data=02-10-2026",
        "https://www.in.gov.br/leiturajornal?secao=dou3&data=02-10-2026",
    ]
    assert all(p["formats"] == ["rawHtml"] and p["max_age"] == 0 for p in leituras), "leitura em HTML bruto e sem cache"
    selecionados = [a for s in resultado["secoes"].values() for a in s["atos"]]
    abertos = [p["url"] for p in fc.pedidos if "/web/dou/-/" in p["url"]]
    assert set(abertos) <= {a["url"] for a in selecionados}, "só abre ato que passou no filtro"
    assert len(abertos) == sum(1 for a in selecionados if a["aberto"])
    assert resultado["creditos"] == len(fc.pedidos) == 2 + len(abertos)
    assert resultado["secoes"]["dou1"]["listados"] == 11 and resultado["secoes"]["dou3"]["listados"] == 5
    suframa = next(a for a in selecionados if "SUFRAMA" in a["titulo"])
    assert suframa["aberto"] and suframa["resumo"].startswith("Aprova o projeto") and suframa["trecho"]
    serie = [a for a in selecionados if not a["aberto"]]
    assert serie and all(a["resumo"] and not a["trecho"] and a["nao_aberto"] for a in serie), "quem não abre entra com o começo do texto"


def teste_falha_ao_abrir_ou_ao_ler_a_secao_fica_registrada():
    fc = FirecrawlFalso(PAGINAS, falhas=["portaria-suframa", "secao=dou3"])
    resultado = cd.coletar(fc, ["dou1", "dou3"], EDICAO, CONFIG)
    assert resultado["secoes"]["dou3"]["erro"].startswith("RuntimeError") and resultado["secoes"]["dou3"]["atos"] == []
    suframa = next(a for a in resultado["secoes"]["dou1"]["atos"] if "SUFRAMA" in a["titulo"])
    assert not suframa["aberto"] and suframa["nao_aberto"].startswith("falha ao abrir") and suframa["resumo"]
    assert resultado["creditos"] == len(fc.pedidos), "pedido que falhou também conta"


# ---------------------------------------------------------------------------
# No gerar_boletim
# ---------------------------------------------------------------------------


FONTES_DOU = [f for f in json.loads((BASE / "fontes.json").read_text(encoding="utf-8")) if f.get("coleta") == "dou"]


def teste_fontes_json_tem_as_duas_secoes():
    assert [(f["fonte"], f["secao"]) for f in FONTES_DOU] == [
        ("Diário Oficial da União | Seção 1", "dou1"), ("Diário Oficial da União | Seção 3", "dou3")]
    assert all(CONFIG["secoes"][f["secao"]]["fonte"] == f["fonte"] for f in FONTES_DOU)


def teste_dou_entra_no_boletim_sem_passar_pelo_gemini():
    fc = FirecrawlFalso(PAGINAS)
    material = gb.coletar_dou(fc, FONTES_DOU, EDICAO, lambda: None)
    dossier, processadas = gb.montar_dossier(material)
    assert dossier == [], "o DOU não vai ao Gemini"
    assert [p["fonte"] for p in processadas] == [f["fonte"] for f in FONTES_DOU]
    assert all(p["status"] == "ok" and p["metodo_usado"] == "dou" for p in processadas)
    itens = gb.itens_do_dou(material)
    assert len(itens) == sum(len(m["publicacoes"]) for m in material)
    cade = next(i for i in itens if "CADE" in i["titulo"] and i["fonte"].endswith("Seção 1"))
    assert cade["boletins_confirmados"] == ["societario-ma", "regulatorio-oleo-gas"]
    assert cade["titulo"].endswith("(Conselho Administrativo de Defesa Econômica)")
    assert cade["trecho_do_ato"]["secao"] == "1" and cade["trecho_do_ato"]["pagina"] > 0
    novos, _ = gb.publicacoes_nao_devolvidas(material, [], "m")
    assert novos == [], "o DOU não volta como 'não devolvido pela IA'"
    creditos = gb.creditos_estimados(material, [])
    assert creditos["dou"] == sum(m["creditos_firecrawl"] for m in material) == len(fc.pedidos)
    assert creditos["total"] == creditos["dou"] and creditos["coletas"] == 0
    log = gb.resumo_dou(material)
    assert log["creditos_firecrawl"] == len(fc.pedidos) and log["edicao"] == "2026-10-02"
    assert log["por_secao"]["Diário Oficial da União | Seção 1"]["atos_na_edicao"] == 11
    assert log["por_radar"]["regulatorio-oleo-gas"] >= 4 and "série" in log["nao_abertos_por_motivo"]


def teste_fim_de_semana_nao_gasta_credito():
    fc = FirecrawlFalso(PAGINAS)
    material = gb.coletar_dou(fc, FONTES_DOU, datetime.date(2026, 10, 3), lambda: None)
    assert fc.pedidos == [] and all(m["status"] == "ok" and not m["publicacoes"] for m in material)
    _, processadas = gb.montar_dossier(material)
    assert all(p["sem_publicacao_na_janela"] and "fim de semana" in p["motivo_sem_publicacao"] for p in processadas)


def teste_secao_com_erro_vira_erro_tecnico():
    fc = FirecrawlFalso(PAGINAS, falhas=["secao=dou3"])
    material = gb.coletar_dou(fc, FONTES_DOU, EDICAO, lambda: None)
    _, processadas = gb.montar_dossier(material)
    tres = next(p for p in processadas if p["fonte"].endswith("Seção 3"))
    assert tres["status"] == "erro" and "Leitura do jornal do DOU falhou" in tres["erro"]


def teste_leitura_vazia_em_dia_util_vira_aviso():
    class Vazio(FirecrawlFalso):
        def scrape(self, url, formats=None, only_main_content=True, max_age=None):
            self.pedidos.append({"url": url})
            corpo = json.dumps({"jsonArray": [], "section": "dou1"})
            return types.SimpleNamespace(raw_html=f'<script id="params" type="application/json">{corpo}</script>', metadata=Meta())

    material = gb.coletar_dou(Vazio(), FONTES_DOU, EDICAO, lambda: None)
    assert all(m["status"] == "ok" and "veio sem atos" in m["aviso_coleta"] for m in material)
    _, processadas = gb.montar_dossier(material)
    assert all("veio sem atos" in p["motivo_sem_publicacao"] for p in processadas), "o motivo não pode dizer 'nenhum passou no filtro'"


def teste_dossier_guardado_refaz_os_itens_do_dou():
    material = gb.coletar_dou(FirecrawlFalso(PAGINAS), FONTES_DOU, EDICAO, lambda: None)
    with tempfile.TemporaryDirectory() as pasta:
        gb.salvar_dossier(material, {"data_execucao": "2026-10-02"}, Path(pasta))
        _, refeito = gb.carregar_dossier(Path(pasta))
        texto = (Path(pasta) / "diario-oficial-da-uniao-secao-1.md").read_text(encoding="utf-8")
    assert gb.itens_do_dou(refeito) == gb.itens_do_dou(material), "reprocessar não pode gastar crédito com o DOU de novo"
    assert "PORTARIA SUFRAMA" in texto and "Radares: regulatorio-oleo-gas" in texto


# ---------------------------------------------------------------------------
# No e-mail
# ---------------------------------------------------------------------------


def teste_trecho_sai_abaixo_do_resumo_na_secao_do_dou():
    import gerar_boletim_final as gf
    import templates_radar

    material = gb.coletar_dou(FirecrawlFalso(PAGINAS), FONTES_DOU, EDICAO, lambda: None)
    itens = [dict(i, boletins=i["boletins_confirmados"]) for i in gb.itens_do_dou(material)]
    mapeamento = json.loads((BASE / "templates" / "mapeamento_radares.json").read_text(encoding="utf-8"))
    slug = "regulatorio-oleo-gas"
    template = templates_radar.carregar_template(str(BASE / "templates" / mapeamento["templates"][slug]))
    estrutura = templates_radar.analisar(template.html)
    regulatorio = [i for i in itens if slug in i["boletins"]]
    por_ancora, sem_secao, encaminhadas = gf.agrupar_por_secao(regulatorio, slug, estrutura.secoes, mapeamento["aliases_fonte"])
    assert not sem_secao and not encaminhadas
    assert list(por_ancora) == ["DiarioOficialUniao"], "Seções 1 e 3 vão para a seção do DOU do Regulatório"
    suframa = next(n for n in por_ancora["DiarioOficialUniao"] if "SUFRAMA" in n["titulo"])
    assert suframa["trecho"]["texto"].startswith("O SUPERINTENDENTE") and suframa["trecho"]["secao"] == "1"
    html = templates_radar.preencher(template.html, estrutura, "02.10.2026", por_ancora)
    resumo = "Aprova o projeto técnico-econômico industrial pleno"
    posicao = html.index(resumo)
    assert html.index("Trecho do ato (DOU, Seção 1, p. 34):", posicao) > posicao
    sem_trecho = templates_radar._preencher_unidade("Título | Acesse a matéria Descrição", {"titulo": "T", "url": "", "resumo": "R"})
    assert "Trecho do ato" not in sem_trecho, "notícia de outra fonte não muda"


TESTES = [
    teste_leitura_traz_todos_os_atos_com_os_campos,
    teste_leitura_sem_json_e_falha,
    teste_regulatorio_segue_o_documento_na_secao_1,
    teste_secao_3_so_cade_e_mais_medicos_do_mec,
    teste_secao_1_vai_para_os_oito_radares_do_documento_e_nao_para_o_trabalhista,
    teste_unidades_regionais_e_tipos_fora_da_regra_ficam_de_fora,
    teste_serie_abre_um_so_e_o_teto_vale,
    teste_ler_ato_separa_identificacao_ementa_texto_e_assinatura,
    teste_sem_ementa_o_resumo_junta_os_primeiros_paragrafos,
    teste_pagina_sem_texto_do_ato_e_falha,
    teste_coleta_abre_so_o_que_passou_e_conta_os_creditos,
    teste_falha_ao_abrir_ou_ao_ler_a_secao_fica_registrada,
    teste_fontes_json_tem_as_duas_secoes,
    teste_dou_entra_no_boletim_sem_passar_pelo_gemini,
    teste_fim_de_semana_nao_gasta_credito,
    teste_secao_com_erro_vira_erro_tecnico,
    teste_leitura_vazia_em_dia_util_vira_aviso,
    teste_dossier_guardado_refaz_os_itens_do_dou,
    teste_trecho_sai_abaixo_do_resumo_na_secao_do_dou,
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
