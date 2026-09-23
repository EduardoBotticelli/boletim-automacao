"""
Testa o contrato entre o portal de curadoria e o gerar_boletim_final.py.

Este teste não depende de rede, de credenciais nem do repositório real: cada
caso monta um boletim.json e um decisoes_alice.json em um diretório temporário
que imita a estrutura do repositório, executa o scripts/gerar_boletim_final.py
como subprocesso e verifica o resultado.

O que ele protege:
- o formato canônico gravado pelo portal gera os nove email_<slug>.html;
- itens adicionados manualmente na curadoria são publicados;
- notícia cuja fonte não tem faixa no Radar sai na faixa "Outras
  publicações", com a procedência real no título, em vez de travar a geração;
- ajustes de Radar feitos por uma pessoa valem mais que a sugestão da IA;
- edições de título, resumo e URL são aplicadas;
- itens rejeitados não são publicados;
- qualquer revisão incompleta, em rascunho ou em formato antigo bloqueia a
  geração e preserva os e-mails anteriores.

Uso: python scripts/testar_decisoes_portal.py
"""

import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPT = BASE_DIR / "scripts" / "gerar_boletim_final.py"
MODULO_TEMPLATES = BASE_DIR / "scripts" / "templates_radar.py"
MODULO_AJUSTES = BASE_DIR / "scripts" / "ajustes_templates.py"
TEMPLATES_DIR = BASE_DIR / "templates"

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

SENTINELA = "<!-- e-mail anterior preservado -->"


@dataclass
class Resultado:
    codigo: int
    saida: str
    emails: dict
    mensagens: dict
    resumo: dict


def boletim_exemplo():
    """Dois itens no mesmo formato que o gerar_boletim.py produz."""
    return {
        "data_execucao": "2026-08-27",
        "itens": [
            {
                "fonte": "CVM | Notícias",
                "categoria": "Financeiro e Mercado de Capitais",
                "titulo": "CVM orienta sobre a Resolução 244",
                "data_publicacao": "2026-08-27",
                "resumo": "Ofício circular sobre relatório de sustentabilidade.",
                "motivo_filtragem": "Orientação da CVM.",
                "palavras_chave_detectadas": ["CVM"],
                "boletins_confirmados": ["mercado-capitais-fundos", "ambiental-esg"],
                "boletins_rejeitados": [],
                "url": "https://www.gov.br/cvm/noticia-244",
                "boletins": ["mercado-capitais-fundos"],
            },
            {
                "fonte": "Destaques do D.O.U.",
                "categoria": "Legislação Federal",
                "titulo": "RESOLUÇÃO CPPI Nº 367",
                "data_publicacao": "2026-08-26",
                "resumo": "Resolução do Conselho do PPI.",
                "motivo_filtragem": "Ato normativo federal.",
                "palavras_chave_detectadas": ["PPI"],
                "boletins_confirmados": ["regulatorio-oleo-gas"],
                "boletins_rejeitados": [],
                "url": "https://www.in.gov.br/dou/resolucao-cppi-367",
                "boletins": ["regulatorio-oleo-gas"],
            },
        ],
        "boletins_config": {
            "boletins_disponiveis": SLUGS,
            "nomes_radares": {},
            "fontes_em_defeso": [
                {
                    "fonte": "CGU | Notícias",
                    "motivo": "Defeso eleitoral",
                    "reativar_em": "2026-10-26",
                }
            ],
        },
    }


def decisao(titulo, url, fonte, status, radares, **extras):
    """Monta uma decisão no formato canônico exportado pelo portal."""
    registro = {
        "id": "it-teste-" + str(abs(hash(url)) % 10**8),
        "status": status,
        "status_portal": extras.pop("status_portal", status),
        "origem": extras.pop("origem", "scraper"),
        "url": url,
        "fonte": fonte,
        "titulo": titulo,
        "radares_finais": radares,
        "boletins": radares,
    }
    registro.update(extras)
    return registro


def payload(decisoes, **extras):
    corpo = {
        "versao_formato": 2,
        "revisao_concluida": True,
        "origem": "portal-curadoria",
        "confirmado_em": "2026-08-27T18:00:00.000Z",
        "data_execucao": "2026-08-27",
        "total_itens": len(decisoes),
        "decisoes": decisoes,
    }
    corpo.update(extras)
    return corpo


def config_ajustes():
    """A configuração de ajustes do repositório, para o teste variar."""
    return json.loads(
        (TEMPLATES_DIR / "ajustes_templates.json").read_text(encoding="utf-8")
    )


def config_mapeamento():
    """O mapeamento de Radares do repositório, para o teste variar."""
    return json.loads(
        (TEMPLATES_DIR / "mapeamento_radares.json").read_text(encoding="utf-8")
    )


def executar(boletim, decisoes, ajustes=None, mapeamento=None):
    """
    Roda o gerar_boletim_final.py em uma cópia isolada do repositório.

    'ajustes' e 'mapeamento' substituem os JSON de configuração da pasta
    templates/, para o teste experimentar variações sem tocar no repositório.

    Devolve um Resultado com o código de saída, a saída de texto, as prévias
    em HTML, as mensagens .eml e o resumo.
    """
    with tempfile.TemporaryDirectory() as raiz:
        raiz = Path(raiz)
        (raiz / "scripts").mkdir()
        saida_dir = raiz / "output"
        saida_dir.mkdir()

        shutil.copy2(SCRIPT, raiz / "scripts" / SCRIPT.name)
        shutil.copy2(MODULO_TEMPLATES, raiz / "scripts" / MODULO_TEMPLATES.name)
        shutil.copy2(MODULO_AJUSTES, raiz / "scripts" / MODULO_AJUSTES.name)

        # Os templates oficiais entram por link simbólico: são ~10 MB e o
        # script só os lê. Quando o teste troca uma configuração, a pasta
        # passa a ser real e só os .msg continuam vindo por link.
        if ajustes is None and mapeamento is None:
            (raiz / "templates").symlink_to(TEMPLATES_DIR, target_is_directory=True)
        else:
            destino = raiz / "templates"
            destino.mkdir()
            for arquivo in TEMPLATES_DIR.iterdir():
                if arquivo.suffix != ".json":
                    (destino / arquivo.name).symlink_to(arquivo)

            configuracoes = {
                "ajustes_templates.json": ajustes,
                "mapeamento_radares.json": mapeamento,
            }
            for nome, valor in configuracoes.items():
                if valor is None:
                    shutil.copy2(TEMPLATES_DIR / nome, destino / nome)
                else:
                    (destino / nome).write_text(
                        json.dumps(valor, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

        (saida_dir / "boletim.json").write_text(
            json.dumps(boletim, ensure_ascii=False), encoding="utf-8"
        )
        (saida_dir / "decisoes_alice.json").write_text(
            json.dumps(decisoes, ensure_ascii=False), encoding="utf-8"
        )

        # Arquivos de uma edição anterior: nenhuma falha pode sobrescrevê-los.
        for slug in SLUGS:
            (saida_dir / f"email_{slug}.html").write_text(SENTINELA, encoding="utf-8")
            (saida_dir / f"email_{slug}.eml").write_text(SENTINELA, encoding="utf-8")

        processo = subprocess.run(
            [sys.executable, str(raiz / "scripts" / SCRIPT.name)],
            capture_output=True,
            text=True,
        )

        emails = {
            slug: (saida_dir / f"email_{slug}.html").read_text(encoding="utf-8")
            for slug in SLUGS
            if (saida_dir / f"email_{slug}.html").exists()
        }

        mensagens = {
            slug: (saida_dir / f"email_{slug}.eml").read_bytes()
            for slug in SLUGS
            if (saida_dir / f"email_{slug}.eml").exists()
        }

        resumo_path = saida_dir / "resumo_geracao_final.json"
        resumo = (
            json.loads(resumo_path.read_text(encoding="utf-8"))
            if resumo_path.exists()
            else {}
        )

        return Resultado(
            codigo=processo.returncode,
            saida=processo.stdout + processo.stderr,
            emails=emails,
            mensagens=mensagens,
            resumo=resumo,
        )


# ---------------------------------------------------------------------------
# Casos de teste
# ---------------------------------------------------------------------------


def teste_fluxo_completo():
    """Aprovado + rejeitado + ajustado + manual gera os nove Radares."""
    decisoes = payload(
        [
            decisao(
                "CVM orienta sobre a Resolução 244",
                "https://www.gov.br/cvm/noticia-244",
                "CVM | Notícias",
                "aprovado",
                ["mercado-capitais-fundos", "imobiliario-infraestrutura"],
                status_portal="ajustado",
            ),
            decisao(
                "RESOLUÇÃO CPPI Nº 367",
                "https://www.in.gov.br/dou/resolucao-cppi-367",
                "Destaques do D.O.U.",
                "rejeitado",
                [],
            ),
            decisao(
                "SENACON abre consulta sobre superendividamento",
                "https://www.gov.br/senacon/consulta-superendividamento",
                "SENACON | Notícias",
                "aprovado",
                ["contencioso-civel"],
                origem="manual",
                noticia={
                    "fonte": "SENACON | Notícias",
                    "categoria": "Adicionado manualmente",
                    "titulo": "SENACON abre consulta sobre superendividamento",
                    "data_publicacao": "2026-08-27",
                    "resumo": "Consulta pública sobre renegociação de dívidas.",
                    "url": "https://www.gov.br/senacon/consulta-superendividamento",
                    "boletins": ["contencioso-civel"],
                },
            ),
        ]
    )

    r = executar(boletim_exemplo(), decisoes)

    assert r.codigo == 0, f"esperava sucesso, saida:\n{r.saida}"
    assert len(r.emails) == 9, f"esperava 9 arquivos, veio {len(r.emails)}"
    assert r.resumo["status"] == "sucesso"
    assert r.resumo["total_aprovados"] == 2
    assert r.resumo["total_itens_manuais"] == 1
    assert r.resumo["total_rejeitados"] == 1

    # O ajuste manual venceu: a IA sugeriu só mercado-capitais, a curadoria
    # acrescentou imobiliario-infraestrutura.
    assert "Resolução 244" in r.emails["mercado-capitais-fundos"]
    assert "Resolução 244" in r.emails["imobiliario-infraestrutura"]

    # O item manual foi publicado, na seção da fonte dele.
    assert "superendividamento" in r.emails["contencioso-civel"]

    # O item rejeitado não aparece em lugar nenhum.
    for slug, conteudo in r.emails.items():
        assert "CPPI" not in conteudo, f"item rejeitado vazou em {slug}"

    # Radar sem itens continua sendo gerado, com a mensagem padrão.
    assert (
        "Não foram identificadas atualizações para este Radar"
        in r.emails["trabalhista-empresarial"]
    )

    # O .eml é o artefato de envio: precisa existir para os nove Radares.
    assert len(r.mensagens) == 9, f"esperava 9 .eml, veio {len(r.mensagens)}"


def teste_edicoes_de_texto():
    """Título, resumo e URL editados na curadoria chegam ao e-mail final."""
    decisoes = payload(
        [
            decisao(
                "CVM orienta sobre a Resolução 244",
                "https://www.gov.br/cvm/noticia-244",
                "CVM | Notícias",
                "aprovado",
                ["mercado-capitais-fundos"],
                titulo_editado="CVM detalha a aplicação da Resolução 244",
                resumo_editado="Resumo reescrito pela curadoria.",
                url_editada="https://www.gov.br/cvm/noticia-244-corrigida",
            ),
            decisao(
                "RESOLUÇÃO CPPI Nº 367",
                "https://www.in.gov.br/dou/resolucao-cppi-367",
                "Destaques do D.O.U.",
                "rejeitado",
                [],
            ),
        ]
    )

    r = executar(boletim_exemplo(), decisoes)

    assert r.codigo == 0, f"esperava sucesso, saida:\n{r.saida}"
    html = r.emails["mercado-capitais-fundos"]
    assert "CVM detalha a aplicação da Resolução 244" in html
    assert "Resumo reescrito pela curadoria." in html
    assert "noticia-244-corrigida" in html


def teste_item_sem_decisao_bloqueia():
    """Faltando decisão para um item, nada é publicado."""
    decisoes = payload(
        [
            decisao(
                "CVM orienta sobre a Resolução 244",
                "https://www.gov.br/cvm/noticia-244",
                "CVM | Notícias",
                "aprovado",
                ["mercado-capitais-fundos"],
            )
        ]
    )

    r = executar(boletim_exemplo(), decisoes)

    assert r.codigo != 0, "revisão incompleta deveria bloquear"
    assert r.resumo["status"] == "bloqueado_por_itens_sem_decisao"
    assert all(conteudo == SENTINELA for conteudo in r.emails.values())
    assert all(dados.decode() == SENTINELA for dados in r.mensagens.values())


def teste_status_pendente_bloqueia():
    """
    "pendente" não é decisão.

    O portal atual converte pendentes em rejeitados antes de exportar; se um
    cliente antigo mandar "pendente", a geração precisa parar em vez de chutar.
    """
    decisoes = payload(
        [
            decisao(
                "CVM orienta sobre a Resolução 244",
                "https://www.gov.br/cvm/noticia-244",
                "CVM | Notícias",
                "pendente",
                [],
            ),
            decisao(
                "RESOLUÇÃO CPPI Nº 367",
                "https://www.in.gov.br/dou/resolucao-cppi-367",
                "Destaques do D.O.U.",
                "aprovado",
                ["regulatorio-oleo-gas"],
            ),
        ]
    )

    r = executar(boletim_exemplo(), decisoes)

    assert r.codigo != 0, "status pendente deveria bloquear"
    assert all(conteudo == SENTINELA for conteudo in r.emails.values())
    assert all(dados.decode() == SENTINELA for dados in r.mensagens.values())


def teste_rascunho_bloqueia():
    """revisao_concluida: false não gera e-mail."""
    decisoes = payload(
        [
            decisao(
                "CVM orienta sobre a Resolução 244",
                "https://www.gov.br/cvm/noticia-244",
                "CVM | Notícias",
                "aprovado",
                ["mercado-capitais-fundos"],
            ),
            decisao(
                "RESOLUÇÃO CPPI Nº 367",
                "https://www.in.gov.br/dou/resolucao-cppi-367",
                "Destaques do D.O.U.",
                "rejeitado",
                [],
            ),
        ],
        revisao_concluida=False,
    )

    r = executar(boletim_exemplo(), decisoes)

    assert r.codigo != 0, "rascunho deveria bloquear"
    assert all(conteudo == SENTINELA for conteudo in r.emails.values())
    assert all(dados.decode() == SENTINELA for dados in r.mensagens.values())


def teste_formato_legado_bloqueia():
    """
    O formato antigo do portal ({id, status, boletins}, sem url/fonte/titulo)
    não tem chave de casamento com o boletim.json. Precisa bloquear, não
    publicar um boletim vazio.
    """
    decisoes = {
        "confirmadoEm": "2026-08-27T18:00:00.000Z",
        "itens": [
            {"id": "real-0", "status": "aprovado", "boletins": ["mercado-capitais-fundos"]},
            {"id": "real-1", "status": "rejeitado", "boletins": []},
        ],
    }

    r = executar(boletim_exemplo(), decisoes)

    assert r.codigo != 0, "formato legado deveria bloquear"
    assert r.resumo["status"] == "bloqueado_por_itens_sem_decisao"
    assert all(conteudo == SENTINELA for conteudo in r.emails.values())
    assert all(dados.decode() == SENTINELA for dados in r.mensagens.values())


def teste_aprovado_sem_radar_bloqueia():
    """Aprovar sem escolher nenhum Radar válido é inconsistente."""
    decisoes = payload(
        [
            decisao(
                "CVM orienta sobre a Resolução 244",
                "https://www.gov.br/cvm/noticia-244",
                "CVM | Notícias",
                "aprovado",
                ["radar-que-nao-existe"],
            ),
            decisao(
                "RESOLUÇÃO CPPI Nº 367",
                "https://www.in.gov.br/dou/resolucao-cppi-367",
                "Destaques do D.O.U.",
                "rejeitado",
                [],
            ),
        ]
    )

    r = executar(boletim_exemplo(), decisoes)

    assert r.codigo != 0, "aprovado sem Radar deveria bloquear"
    assert r.resumo["status"] == "bloqueado_por_itens_sem_decisao"
    assert all(conteudo == SENTINELA for conteudo in r.emails.values())
    assert all(dados.decode() == SENTINELA for dados in r.mensagens.values())



def teste_template_oficial_preservado():
    """
    O corpo publicado é o do template: imagens, avaliação, rodapé e links
    institucionais chegam intactos, e nenhum placeholder sobra.
    """
    decisoes = payload(
        [
            decisao(
                "CVM orienta sobre a Resolução 244",
                "https://www.gov.br/cvm/noticia-244",
                "CVM | Notícias",
                "aprovado",
                ["mercado-capitais-fundos"],
            ),
            decisao(
                "RESOLUÇÃO CPPI Nº 367",
                "https://www.in.gov.br/dou/resolucao-cppi-367",
                "Destaques do D.O.U.",
                "rejeitado",
                [],
            ),
        ]
    )

    r = executar(boletim_exemplo(), decisoes)
    assert r.codigo == 0, f"esperava sucesso, saida:\n{r.saida}"

    html = r.emails["mercado-capitais-fundos"]

    # Identidade visual e recursos do template.
    assert html.count("<img") == 9, "as imagens do template sumiram"
    assert "forms.cloud.microsoft" in html, "a avaliação da edição sumiu"
    assert "linkedin.com/company/loboderizzoadvogados" in html, "rodapé social sumiu"
    assert "www.ldr.com.br" in html, "link institucional sumiu"
    assert "VOLTAR AO SUM" in html, "o voltar ao sumário sumiu"

    # Nenhum placeholder remanescente.
    assert "00.00.2026" not in html
    assert "Título | " not in html
    assert "Descrição<" not in html

    # Data da edição e link real da matéria.
    assert "27.08.2026" in html
    assert "https://www.gov.br/cvm/noticia-244" in html


def teste_secoes_sem_noticia_saem_do_corpo_e_do_sumario():
    """Fonte sem notícia não aparece nem como seção nem no sumário."""
    decisoes = payload(
        [
            decisao(
                "CVM orienta sobre a Resolução 244",
                "https://www.gov.br/cvm/noticia-244",
                "CVM | Notícias",
                "aprovado",
                ["mercado-capitais-fundos"],
            ),
            decisao(
                "RESOLUÇÃO CPPI Nº 367",
                "https://www.in.gov.br/dou/resolucao-cppi-367",
                "Destaques do D.O.U.",
                "rejeitado",
                [],
            ),
        ]
    )

    r = executar(boletim_exemplo(), decisoes)
    assert r.codigo == 0, f"esperava sucesso, saida:\n{r.saida}"

    html = r.emails["mercado-capitais-fundos"]

    # A seção da CVM ficou.
    assert "name=CVM" in html

    # As demais fontes do template saíram, com as entradas do sumário.
    for ausente in ("B3", "LatinLawyer", "COAF", "BancoCentral"):
        assert f"name={ausente}" not in html, f"seção {ausente} deveria ter saído"
        assert f'href="#{ausente}"' not in html, f"sumário ainda cita {ausente}"


def teste_radar_vazio_usa_o_template_com_mensagem():
    """Radar sem notícia mantém o template e exibe a mensagem padrão."""
    decisoes = payload(
        [
            decisao(
                "CVM orienta sobre a Resolução 244",
                "https://www.gov.br/cvm/noticia-244",
                "CVM | Notícias",
                "aprovado",
                ["mercado-capitais-fundos"],
            ),
            decisao(
                "RESOLUÇÃO CPPI Nº 367",
                "https://www.in.gov.br/dou/resolucao-cppi-367",
                "Destaques do D.O.U.",
                "rejeitado",
                [],
            ),
        ]
    )

    r = executar(boletim_exemplo(), decisoes)
    assert r.codigo == 0, f"esperava sucesso, saida:\n{r.saida}"

    html = r.emails["ambiental-esg"]

    assert (
        "Não foram identificadas atualizações para este Radar no período analisado."
        in html
    )
    # O template continua inteiro.
    assert html.count("<img") == 9
    assert "forms.cloud.microsoft" in html
    assert "VOLTAR AO SUM" in html
    # E nenhuma faixa de fonte sobrou, nem a genérica.
    assert "Título | " not in html
    assert "Outras publicações" not in html


def teste_eml_carrega_as_imagens_do_template():
    """O .eml traz cada imagem referenciada por cid: como parte da mensagem."""
    import email
    import re
    from email import policy

    decisoes = payload(
        [
            decisao(
                "CVM orienta sobre a Resolução 244",
                "https://www.gov.br/cvm/noticia-244",
                "CVM | Notícias",
                "aprovado",
                ["mercado-capitais-fundos"],
            ),
            decisao(
                "RESOLUÇÃO CPPI Nº 367",
                "https://www.in.gov.br/dou/resolucao-cppi-367",
                "Destaques do D.O.U.",
                "rejeitado",
                [],
            ),
        ]
    )

    r = executar(boletim_exemplo(), decisoes)
    assert r.codigo == 0, f"esperava sucesso, saida:\n{r.saida}"

    for slug, bruto in r.mensagens.items():
        mensagem = email.message_from_bytes(bruto, policy=policy.default)
        corpo = mensagem.get_body(preferencelist=("html",))
        assert corpo is not None, f"{slug}: .eml sem corpo HTML"

        conteudo = corpo.get_content()
        embutidos = {
            parte.get("Content-ID")
            for parte in mensagem.walk()
            if parte.get("Content-ID")
        }
        sem_comentario = re.sub(r"<!--.*?-->", " ", conteudo, flags=re.S)
        referenciados = set(re.findall(r"cid:([^\"'\s>)]+)", sem_comentario))

        assert referenciados, f"{slug}: o corpo não referencia imagem alguma"
        faltando = [
            cid for cid in referenciados if f"<{cid}>" not in embutidos
        ]
        assert not faltando, f"{slug}: imagens sem anexo correspondente: {faltando}"


def boletim_com_fonte_desconhecida():
    """O boletim de exemplo mais uma notícia sem faixa em Radar algum."""
    boletim = boletim_exemplo()
    boletim["itens"].append(
    {
        "fonte": "Tribunal Inexistente | Notícias",
        "categoria": "Teste",
        "titulo": "Notícia de fonte que o template não conhece",
        "data_publicacao": "2026-08-27",
        "resumo": "Não existe faixa desta fonte em Radar algum.",
        "motivo_filtragem": "Teste.",
        "palavras_chave_detectadas": [],
        "boletins_confirmados": ["mercado-capitais-fundos"],
        "boletins_rejeitados": [],
        "url": "https://exemplo.invalido/noticia",
        "boletins": ["mercado-capitais-fundos"],
    }
    )
    return boletim


def decisoes_com_fonte_desconhecida(radares):
    """Só a notícia de fonte desconhecida é aprovada."""
    return payload(
        [
            decisao(
                "CVM orienta sobre a Resolução 244",
                "https://www.gov.br/cvm/noticia-244",
                "CVM | Notícias",
                "rejeitado",
                [],
            ),
            decisao(
                "RESOLUÇÃO CPPI Nº 367",
                "https://www.in.gov.br/dou/resolucao-cppi-367",
                "Destaques do D.O.U.",
                "rejeitado",
                [],
            ),
            decisao(
                "Notícia de fonte que o template não conhece",
                "https://exemplo.invalido/noticia",
                "Tribunal Inexistente | Notícias",
                "aprovado",
                radares,
            ),
        ]
    )


def teste_fonte_sem_secao_vai_para_outras_publicacoes():
    """
    Notícia aprovada cuja fonte não tem faixa no template é publicada na
    faixa "Outras publicações", com a procedência real no título.

    É a origem 1: a matriz do Filtro 1 e os templates do Marketing foram
    construídos em momentos diferentes e divergem.
    """
    r = executar(
        boletim_com_fonte_desconhecida(),
        decisoes_com_fonte_desconhecida(["mercado-capitais-fundos"]),
    )

    assert r.codigo == 0, f"esperava sucesso, saida:\n{r.saida}"

    publicadas = next(
        arquivo["secoes_publicadas"]
        for arquivo in r.resumo["arquivos_gerados"]
        if arquivo["slug"] == "mercado-capitais-fundos"
    )
    assert publicadas == ["OutrasPublicacoes"], (
        f"a notícia deveria sair na faixa genérica, saiu em {publicadas}"
    )

    html = r.emails["mercado-capitais-fundos"]
    assert "Outras publicações" in html, "a faixa genérica não foi publicada"
    assert 'href="#OutrasPublicacoes"' in html, (
        "a faixa genérica não entrou no sumário"
    )
    assert "Tribunal Inexistente — Notícia de fonte que o template não conhece" in (
        html
    ), "a procedência real não aparece no título"

    # Nada foi descartado e o encaminhamento fica registrado.
    encaminhadas = r.resumo["noticias_em_outras_publicacoes"]
    assert len(encaminhadas) == 1, encaminhadas
    assert encaminhadas[0]["fonte"] == "Tribunal Inexistente | Notícias"
    assert encaminhadas[0]["radar"] == "mercado-capitais-fundos"
    assert encaminhadas[0]["publicada_em"] == "OutrasPublicacoes"

    # Nos Radares onde nada caiu na faixa, ela não aparece.
    for slug in SLUGS:
        if slug == "mercado-capitais-fundos":
            continue
        assert "Outras publicações" not in r.emails[slug], (
            f"{slug}: a faixa genérica vazia deveria ter saído do Radar"
        )
        assert "#OutrasPublicacoes" not in r.emails[slug], (
            f"{slug}: a faixa genérica vazia deveria ter saído do sumário"
        )


def teste_sem_faixa_generica_a_geracao_bloqueia():
    """
    Sem a faixa genérica declarada, a notícia sem faixa própria volta a
    bloquear a geração.

    É a garantia de que nada é descartado em silêncio: quando não há para
    onde mandar a notícia, o gerador para e preserva os e-mails anteriores.
    """
    ajustes = config_ajustes()
    ajustes.pop("secao_outras_publicacoes", None)

    r = executar(
        boletim_com_fonte_desconhecida(),
        decisoes_com_fonte_desconhecida(["mercado-capitais-fundos"]),
        ajustes=ajustes,
    )

    assert r.codigo != 0, "sem faixa genérica, a fonte sem seção deveria bloquear"
    assert r.resumo["status"] == "bloqueado_por_fonte_sem_secao_no_template"
    assert r.resumo["itens_sem_secao_no_template"][0]["fonte"] == (
        "Tribunal Inexistente | Notícias"
    )
    assert all(conteudo == SENTINELA for conteudo in r.emails.values())
    assert all(dados.decode() == SENTINELA for dados in r.mensagens.values())


def teste_radar_escolhido_a_mao_preserva_a_procedencia():
    """
    O caso concreto que travou a geração: notícia do Ministério da
    Agricultura aprovada para o Radar Regulatório e Óleo e Gás, que não tem
    faixa do MAPA.

    É a origem 2: no portal, qualquer Radar pode ser acrescentado a qualquer
    notícia. A mesma notícia vai para dois Radares e em cada um aparece sob a
    procedência certa — faixa do MAPA no Ambiental, que tem a faixa, e
    "Outras publicações" no Regulatório, que não tem.
    """
    boletim = boletim_exemplo()
    boletim["itens"].append(
        {
            "fonte": "Ministério da Agricultura | Notícias",
            "categoria": "Agropecuária",
            "titulo": "Fiscalização do Mapa identifica fábrica irregular de ração",
            "data_publicacao": "2026-09-23",
            "resumo": "Operação em fábrica de ração animal.",
            "motivo_filtragem": "Fiscalização federal.",
            "palavras_chave_detectadas": [],
            # A matriz do Filtro 1 não liga o MAPA ao Regulatório, então a
            # coleta entrega o item sem Radar algum.
            "boletins_confirmados": ["regulatorio-oleo-gas"],
            "boletins_rejeitados": [],
            "url": "https://www.gov.br/agricultura/fiscalizacao-racao",
            "boletins": [],
        }
    )

    decisoes = payload(
        [
            decisao(
                "CVM orienta sobre a Resolução 244",
                "https://www.gov.br/cvm/noticia-244",
                "CVM | Notícias",
                "rejeitado",
                [],
            ),
            decisao(
                "RESOLUÇÃO CPPI Nº 367",
                "https://www.in.gov.br/dou/resolucao-cppi-367",
                "Destaques do D.O.U.",
                "rejeitado",
                [],
            ),
            decisao(
                "Fiscalização do Mapa identifica fábrica irregular de ração",
                "https://www.gov.br/agricultura/fiscalizacao-racao",
                "Ministério da Agricultura | Notícias",
                "aprovado",
                ["regulatorio-oleo-gas", "ambiental-esg"],
            ),
        ]
    )

    r = executar(boletim, decisoes)
    assert r.codigo == 0, f"esperava sucesso, saida:\n{r.saida}"

    por_slug = {
        arquivo["slug"]: arquivo["secoes_publicadas"]
        for arquivo in r.resumo["arquivos_gerados"]
    }

    # No Ambiental existe a faixa do MAPA: publica lá, sob o próprio nome.
    assert por_slug["ambiental-esg"] == ["MAPA"], por_slug["ambiental-esg"]
    ambiental = r.emails["ambiental-esg"]
    assert "Fiscalização do Mapa identifica" in ambiental
    assert "Ministério da Agricultura — Fiscalização" not in ambiental, (
        "na faixa do MAPA a procedência já está na faixa; não repetir no título"
    )
    assert "Outras publicações" not in ambiental

    # No Regulatório não existe: publica na faixa genérica, com a fonte no
    # título, sem ser atribuída a nenhum outro órgão.
    assert por_slug["regulatorio-oleo-gas"] == ["OutrasPublicacoes"], (
        por_slug["regulatorio-oleo-gas"]
    )
    regulatorio = r.emails["regulatorio-oleo-gas"]
    assert "Ministério da Agricultura — Fiscalização do Mapa identifica" in (
        regulatorio
    ), "a procedência real não aparece no título"

    encaminhadas = r.resumo["noticias_em_outras_publicacoes"]
    assert [e["radar"] for e in encaminhadas] == ["regulatorio-oleo-gas"], (
        encaminhadas
    )


def item_manual_de_fonte_livre(radares):
    """Decisão de item adicionado à mão, com a fonte digitada em texto livre."""
    return decisao(
        "Latin Lawyer analisa operação de infraestrutura",
        "https://latinlawyer.com/analise-infraestrutura",
        "Latin Lawyer",
        "aprovado",
        radares,
        origem="manual",
        noticia={
            "fonte": "Latin Lawyer",
            "categoria": "Adicionado manualmente",
            "titulo": "Latin Lawyer analisa operação de infraestrutura",
            "data_publicacao": "2026-08-27",
            "resumo": "Análise de operação recente.",
            "url": "https://latinlawyer.com/analise-infraestrutura",
            "boletins": radares,
        },
    )


def teste_item_manual_com_fonte_livre_vai_para_outras_publicacoes():
    """
    Item adicionado à mão, com a fonte digitada, é publicado na faixa
    genérica com o nome que a pessoa digitou.

    É a origem 3: o portal aceita fonte em texto livre justamente para as
    fontes ainda fora do scraper, que não têm faixa em template nenhum.
    """
    decisoes = payload(
        [
            decisao(
                "CVM orienta sobre a Resolução 244",
                "https://www.gov.br/cvm/noticia-244",
                "CVM | Notícias",
                "rejeitado",
                [],
            ),
            decisao(
                "RESOLUÇÃO CPPI Nº 367",
                "https://www.in.gov.br/dou/resolucao-cppi-367",
                "Destaques do D.O.U.",
                "rejeitado",
                [],
            ),
            item_manual_de_fonte_livre(["trabalhista-empresarial"]),
        ]
    )

    r = executar(boletim_exemplo(), decisoes)
    assert r.codigo == 0, f"esperava sucesso, saida:\n{r.saida}"

    publicadas = next(
        arquivo["secoes_publicadas"]
        for arquivo in r.resumo["arquivos_gerados"]
        if arquivo["slug"] == "trabalhista-empresarial"
    )
    assert publicadas == ["OutrasPublicacoes"], publicadas

    html = r.emails["trabalhista-empresarial"]
    assert "Latin Lawyer — Latin Lawyer analisa operação de infraestrutura" in html
    assert 'href="#OutrasPublicacoes"' in html

    encaminhadas = r.resumo["noticias_em_outras_publicacoes"]
    assert len(encaminhadas) == 1 and encaminhadas[0]["origem"] == "manual", (
        encaminhadas
    )


def teste_secao_padrao_manual_continua_tendo_precedencia():
    """
    O 'secao_padrao_item_manual' continua disponível e vale mais que a faixa
    genérica, para o caso em que a fonte digitada é mesmo a de uma faixa.

    Aqui a pessoa digitou "Controladoria-Geral da União", que é a CGU do
    template escrita por extenso.
    """
    mapeamento = config_mapeamento()
    mapeamento["secao_padrao_item_manual"]["trabalhista-empresarial"] = "CGU"

    manual = item_manual_de_fonte_livre(["trabalhista-empresarial"])
    manual["fonte"] = "Controladoria-Geral da União"
    manual["titulo"] = "CGU publica relatório de integridade"
    manual["url"] = "https://www.gov.br/cgu/relatorio-integridade"
    manual["noticia"] = {
        "fonte": "Controladoria-Geral da União",
        "categoria": "Adicionado manualmente",
        "titulo": "CGU publica relatório de integridade",
        "data_publicacao": "2026-08-27",
        "resumo": "Relatório anual de integridade.",
        "url": "https://www.gov.br/cgu/relatorio-integridade",
        "boletins": ["trabalhista-empresarial"],
    }

    decisoes = payload(
        [
            decisao(
                "CVM orienta sobre a Resolução 244",
                "https://www.gov.br/cvm/noticia-244",
                "CVM | Notícias",
                "rejeitado",
                [],
            ),
            decisao(
                "RESOLUÇÃO CPPI Nº 367",
                "https://www.in.gov.br/dou/resolucao-cppi-367",
                "Destaques do D.O.U.",
                "rejeitado",
                [],
            ),
            manual,
        ]
    )

    r = executar(boletim_exemplo(), decisoes, mapeamento=mapeamento)
    assert r.codigo == 0, f"esperava sucesso, saida:\n{r.saida}"

    publicadas = next(
        arquivo["secoes_publicadas"]
        for arquivo in r.resumo["arquivos_gerados"]
        if arquivo["slug"] == "trabalhista-empresarial"
    )
    assert publicadas == ["CGU"], (
        f"o padrão manual deveria vencer a faixa genérica, saiu em {publicadas}"
    )
    assert not r.resumo["noticias_em_outras_publicacoes"]
    assert "Outras publicações" not in r.emails["trabalhista-empresarial"]


def teste_fonte_nova_publica_na_propria_secao():
    """
    Fonte que ganhou seção no template publica sob o próprio nome, não sob
    outra procedência.

    A ANTAQ não tinha seção no Radar Imobiliário e Infraestrutura; agora tem.
    """
    boletim = boletim_exemplo()
    boletim["itens"].append(
        {
            "fonte": "ANTAQ | Notícias",
            "categoria": "Infraestrutura",
            "titulo": "ANTAQ realiza visita técnica em Santos",
            "data_publicacao": "2026-09-22",
            "resumo": "Visita a empresas de navegação.",
            "motivo_filtragem": "Regulação portuária.",
            "palavras_chave_detectadas": [],
            "boletins_confirmados": ["imobiliario-infraestrutura"],
            "boletins_rejeitados": [],
            "url": "https://www.gov.br/antaq/visita-santos",
            "boletins": ["imobiliario-infraestrutura"],
        }
    )

    decisoes = payload(
        [
            decisao(
                "CVM orienta sobre a Resolução 244",
                "https://www.gov.br/cvm/noticia-244",
                "CVM | Notícias",
                "rejeitado",
                [],
            ),
            decisao(
                "RESOLUÇÃO CPPI Nº 367",
                "https://www.in.gov.br/dou/resolucao-cppi-367",
                "Destaques do D.O.U.",
                "rejeitado",
                [],
            ),
            decisao(
                "ANTAQ realiza visita técnica em Santos",
                "https://www.gov.br/antaq/visita-santos",
                "ANTAQ | Notícias",
                "aprovado",
                ["imobiliario-infraestrutura"],
            ),
        ]
    )

    r = executar(boletim, decisoes)
    assert r.codigo == 0, f"esperava sucesso, saida:\n{r.saida}"

    publicadas = next(
        arquivo["secoes_publicadas"]
        for arquivo in r.resumo["arquivos_gerados"]
        if arquivo["slug"] == "imobiliario-infraestrutura"
    )
    assert publicadas == ["ANTAQ"], (
        f"a notícia deveria sair na seção da ANTAQ, saiu em {publicadas}"
    )

    html = r.emails["imobiliario-infraestrutura"]
    assert "visita técnica em Santos" in html
    assert 'href="#ANTAQ"' in html, "a ANTAQ não entrou no sumário"


def teste_mecanismo_de_alias_continua_disponivel():
    """
    O alias continua funcionando para casos futuros, mesmo sem nenhuma fonte
    dependendo dele hoje.

    O Ministério da Agricultura chega como MAPA no template do Radar
    Ambiental e ESG por meio de alias.
    """
    mapeamento = json.loads(
        (BASE_DIR / "templates" / "mapeamento_radares.json").read_text(encoding="utf-8")
    )
    aliases = mapeamento.get("aliases_fonte", {})
    assert "Ministério da Agricultura" in aliases, "o mecanismo de alias sumiu"

    boletim = boletim_exemplo()
    boletim["itens"].append(
        {
            "fonte": "Ministério da Agricultura | Notícias",
            "categoria": "Ambiental",
            "titulo": "MAPA publica normas de defesa agropecuária",
            "data_publicacao": "2026-09-22",
            "resumo": "Normas de defesa agropecuária.",
            "motivo_filtragem": "Teste de alias.",
            "palavras_chave_detectadas": [],
            "boletins_confirmados": ["ambiental-esg"],
            "boletins_rejeitados": [],
            "url": "https://www.gov.br/agricultura/normas",
            "boletins": ["ambiental-esg"],
        }
    )

    decisoes = payload(
        [
            decisao(
                "CVM orienta sobre a Resolução 244",
                "https://www.gov.br/cvm/noticia-244",
                "CVM | Notícias",
                "rejeitado",
                [],
            ),
            decisao(
                "RESOLUÇÃO CPPI Nº 367",
                "https://www.in.gov.br/dou/resolucao-cppi-367",
                "Destaques do D.O.U.",
                "rejeitado",
                [],
            ),
            decisao(
                "MAPA publica normas de defesa agropecuária",
                "https://www.gov.br/agricultura/normas",
                "Ministério da Agricultura | Notícias",
                "aprovado",
                ["ambiental-esg"],
            ),
        ]
    )

    r = executar(boletim, decisoes)
    assert r.codigo == 0, f"esperava sucesso, saida:\n{r.saida}"

    publicadas = next(
        arquivo["secoes_publicadas"]
        for arquivo in r.resumo["arquivos_gerados"]
        if arquivo["slug"] == "ambiental-esg"
    )
    assert publicadas == ["MAPA"], publicadas


def teste_ancora_do_voltar_ao_sumario_existe():
    """
    Em todos os nove Radares, todo link interno tem âncora de destino.

    Antes do ajuste, o "VOLTAR AO SUMÁRIO" apontava para "#Sumario", que não
    existia em template nenhum.
    """
    decisoes = payload(
        [
            decisao(
                "CVM orienta sobre a Resolução 244",
                "https://www.gov.br/cvm/noticia-244",
                "CVM | Notícias",
                "aprovado",
                ["mercado-capitais-fundos"],
            ),
            decisao(
                "RESOLUÇÃO CPPI Nº 367",
                "https://www.in.gov.br/dou/resolucao-cppi-367",
                "Destaques do D.O.U.",
                "rejeitado",
                [],
            ),
        ]
    )

    r = executar(boletim_exemplo(), decisoes)
    assert r.codigo == 0, f"esperava sucesso, saida:\n{r.saida}"

    import re

    for slug, html in r.emails.items():
        ancoras = set(re.findall(r'<a[^>]*name="?([A-Za-z0-9_.-]+)"?', html))
        destinos = set(re.findall(r'href="#([A-Za-z0-9_.-]+)"', html))
        quebrados = sorted(destinos - ancoras)
        assert not quebrados, f"{slug}: links internos sem âncora: {quebrados}"

    # Vale também na edição vazia, onde a grade de fontes some inteira.
    vazio = r.emails["ambiental-esg"]
    assert "Não foram identificadas atualizações" in vazio
    ancoras = set(re.findall(r'<a[^>]*name="?([A-Za-z0-9_.-]+)"?', vazio))
    assert "Sumario" in ancoras, "a âncora do sumário sumiu na edição vazia"


def teste_todas_as_fontes_do_filtro1_tem_destino():
    """
    Toda fonte que o Filtro 1 permite para um Radar precisa ter seção no
    template ou alias no mapeamento. Sem isso, uma notícia dessa fonte
    bloquearia a edição inteira.
    """
    import re

    codigo = (BASE_DIR / "scripts" / "gerar_boletim.py").read_text(encoding="utf-8")
    espaco = {}
    for padrao in (r"^SLUGS = \[.*?\]$", r"^MAPA = \{.*?^\}$"):
        encontrado = re.search(padrao, codigo, re.M | re.S)
        assert encontrado, "não foi possível ler o Filtro 1 do gerar_boletim.py"
        exec(encontrado.group(0), espaco)

    mapeamento = json.loads(
        (BASE_DIR / "templates" / "mapeamento_radares.json").read_text(encoding="utf-8")
    )
    aliases = mapeamento.get("aliases_fonte", {})

    sys.path.insert(0, str(BASE_DIR / "scripts"))
    import ajustes_templates
    import templates_radar

    config_ajustes = ajustes_templates.carregar_config()
    faltando = []

    for fonte, slugs in espaco["MAPA"].items():
        orgao = templates_radar.normalizar(str(fonte).split("|")[0])

        for slug in slugs:
            template = templates_radar.carregar_template(
                str(BASE_DIR / "templates" / mapeamento["templates"][slug])
            )
            html, _ = ajustes_templates.aplicar(template.html, slug, config_ajustes)
            secoes = templates_radar.analisar(html).secoes

            destino = None
            for chave, destinos in aliases.items():
                if isinstance(destinos, dict) and templates_radar.normalizar(chave) == orgao:
                    destino = destinos.get(slug)
                    if destino:
                        break

            if destino:
                assert any(secao.ancora == destino for secao in secoes), (
                    f"{slug}: o alias de '{fonte}' aponta para a âncora "
                    f"'{destino}', que não existe no template"
                )
                continue

            casou = any(
                templates_radar.normalizar(secao.nome) == orgao
                or templates_radar.normalizar(secao.nome).startswith(orgao + " ")
                or orgao.startswith(templates_radar.normalizar(secao.nome) + " ")
                for secao in secoes
                if templates_radar.normalizar(secao.nome)
            )
            if not casou:
                faltando.append((slug, fonte))

    assert not faltando, "fontes do Filtro 1 sem destino no template: " + str(faltando)



def teste_estrutura_mime_embute_as_imagens():
    """
    A mensagem precisa ter a estrutura que o Outlook embute.

    Falha se a montagem MIME regredir para o formato em que as doze imagens
    viram anexos visíveis e o corpo mostra caixas quebradas, que foi o
    defeito observado: as partes estavam com Content-Disposition attachment
    e o multipart/related não declarava o tipo da parte raiz.

    Espelha o que o .msg oficial declara para cada anexo:
    PR_ATTACH_FLAGS = ATT_MHTML_REF, PR_ATTACHMENT_HIDDEN = 1 e
    PR_RENDERING_POSITION = -1.
    """
    import email
    import re
    from email import policy

    decisoes = payload(
        [
            decisao(
                "CVM orienta sobre a Resolução 244",
                "https://www.gov.br/cvm/noticia-244",
                "CVM | Notícias",
                "aprovado",
                ["mercado-capitais-fundos"],
            ),
            decisao(
                "RESOLUÇÃO CPPI Nº 367",
                "https://www.in.gov.br/dou/resolucao-cppi-367",
                "Destaques do D.O.U.",
                "rejeitado",
                [],
            ),
        ]
    )

    r = executar(boletim_exemplo(), decisoes)
    assert r.codigo == 0, f"esperava sucesso, saida:\n{r.saida}"
    assert len(r.mensagens) == 9, f"esperava 9 .eml, veio {len(r.mensagens)}"

    for slug, bruto in r.mensagens.items():
        mensagem = email.message_from_bytes(bruto, policy=policy.default)

        # 1. corpo e imagens no mesmo multipart/related, com o tipo da raiz
        #    declarado.
        assert mensagem.get_content_type() == "multipart/related", (
            f"{slug}: a raiz é {mensagem.get_content_type()}"
        )
        assert mensagem.get_param("type") == "multipart/alternative", (
            f"{slug}: o multipart/related não declara o tipo da parte raiz"
        )

        # 2. cabeçalhos básicos da mensagem.
        for cabecalho in ("Subject", "Date", "Message-ID"):
            assert mensagem.get(cabecalho), f"{slug}: falta {cabecalho}"

        # 3. sem X-Unsent: ele abre o arquivo em modo de composição, e o
        #    editor do Word descaracteriza o CSS do template (sumário em
        #    minúsculas, hiperlinks recoloridos, botões de avaliação fora de
        #    ordem). Conferido no Outlook comparando com o template.
        assert not mensagem.get("X-Unsent"), (
            f"{slug}: a mensagem tem X-Unsent e o corpo sairia "
            "descaracterizado no Outlook"
        )

        corpo = mensagem.get_body(preferencelist=("html",))
        assert corpo is not None, f"{slug}: sem corpo HTML"
        conteudo = corpo.get_content()

        embutidos = {}
        for parte in mensagem.walk():
            identificador = parte.get("Content-ID")
            if not identificador:
                continue

            # 3. Content-ID entre sinais de menor e maior.
            assert identificador.startswith("<") and identificador.endswith(">"), (
                f"{slug}: Content-ID fora do formato: {identificador}"
            )

            # 4. imagem embutida, não anexo.
            disposicao = (parte.get_content_disposition() or "").lower()
            assert disposicao == "inline", (
                f"{slug}: {identificador} está como "
                f"{disposicao or 'sem disposição'}, deveria ser inline"
            )

            # 5. codificação adequada para binário.
            assert parte.get("Content-Transfer-Encoding", "").lower() == "base64", (
                f"{slug}: {identificador} não está em base64"
            )

            embutidos[identificador.strip("<>")] = parte

        # 6. nenhum anexo visível.
        anexos = [
            parte.get_filename() or parte.get_content_type()
            for parte in mensagem.walk()
            if (parte.get_content_disposition() or "").lower() == "attachment"
        ]
        assert not anexos, f"{slug}: a mensagem tem anexo visível: {anexos}"

        # 7. todo cid que o cliente enxerga tem parte, e toda parte é
        #    referenciada. Referência dentro de comentário HTML não conta: é
        #    o caso do fallback VML, cujos recursos não entram na mensagem
        #    justamente porque o Outlook os listaria como anexos.
        sem_comentario = re.sub(r"<!--.*?-->", " ", conteudo, flags=re.S)
        referenciados = set(re.findall(r"cid:([^\"'\s>)]+)", sem_comentario))
        assert referenciados, f"{slug}: o corpo não referencia imagem alguma"

        so_em_comentario = (
            set(re.findall(r"cid:([^\"'\s>)]+)", conteudo)) - referenciados
        )
        embutidos_indevidos = sorted(so_em_comentario & set(embutidos))
        assert not embutidos_indevidos, (
            f"{slug}: recurso referenciado só dentro de comentário entrou na "
            f"mensagem e apareceria como anexo: {embutidos_indevidos}"
        )

        faltando = sorted(referenciados - set(embutidos))
        assert not faltando, f"{slug}: cid sem parte correspondente: {faltando}"

        sobrando = sorted(set(embutidos) - referenciados)
        assert not sobrando, (
            f"{slug}: parte embutida sem referência no corpo: {sobrando}"
        )


def teste_faixa_outras_publicacoes_existe_nos_nove_templates():
    """
    A faixa genérica é criada nos nove templates: sempre por cópia de uma
    seção do próprio template, sempre como última seção do Radar, e sem tocar
    em nada que já existia.
    """
    sys.path.insert(0, str(BASE_DIR / "scripts"))
    import ajustes_templates
    import templates_radar

    config = config_ajustes()
    mapeamento = config_mapeamento()

    ancora = ajustes_templates.ancora_generica(config)
    assert ancora, "a faixa genérica não está declarada"
    nome = config["secao_outras_publicacoes"]["nome"]

    sem_generica = dict(config)
    sem_generica.pop("secao_outras_publicacoes", None)

    for slug, arquivo in mapeamento["templates"].items():
        template = templates_radar.carregar_template(str(TEMPLATES_DIR / arquivo))

        antes, _ = ajustes_templates.aplicar(template.html, slug, sem_generica)
        depois, relatorio = ajustes_templates.aplicar(template.html, slug, config)

        estrutura_antes = templates_radar.analisar(antes)
        estrutura_depois = templates_radar.analisar(depois)

        # A faixa é a última seção do Radar.
        ultima = estrutura_depois.secoes[-1]
        assert ultima.ancora == ancora, f"{slug}: última seção é {ultima.ancora}"
        assert ultima.nome == nome, f"{slug}: faixa criada como {ultima.nome!r}"

        # Nenhuma seção existente mudou de nome, de âncora ou de posição.
        assert [(s.ancora, s.nome) for s in estrutura_depois.secoes[:-1]] == [
            (s.ancora, s.nome) for s in estrutura_antes.secoes
        ], f"{slug}: as seções existentes foram alteradas"

        # Tudo o que vem depois da última seção — avaliação da edição, rodapé
        # e links institucionais — continua byte a byte igual.
        cauda = antes[estrutura_antes.secoes[-1].fim_corpo :]
        assert cauda in depois, f"{slug}: o trecho final do template mudou"

        # A grade do sumário continua com três células por linha.
        celulas = ajustes_templates._celulas_do_sumario(depois, estrutura_depois)
        assert len(celulas) == 3 * len(estrutura_depois.linhas_sumario), (
            f"{slug}: a grade do sumário deixou de ter três células por linha"
        )
        assert f'href="#{ancora}"' in depois, f"{slug}: faixa fora do sumário"

        # E a cópia saiu de uma seção do próprio template.
        copiada_de = relatorio["secao_generica"]["copiada_de"]
        assert copiada_de in {s.ancora for s in estrutura_antes.secoes}, (
            f"{slug}: a faixa foi copiada de {copiada_de}, que não é do template"
        )


TESTES = [
    teste_fluxo_completo,
    teste_edicoes_de_texto,
    teste_item_sem_decisao_bloqueia,
    teste_status_pendente_bloqueia,
    teste_rascunho_bloqueia,
    teste_formato_legado_bloqueia,
    teste_aprovado_sem_radar_bloqueia,
    teste_template_oficial_preservado,
    teste_secoes_sem_noticia_saem_do_corpo_e_do_sumario,
    teste_radar_vazio_usa_o_template_com_mensagem,
    teste_eml_carrega_as_imagens_do_template,
    teste_estrutura_mime_embute_as_imagens,
    teste_fonte_sem_secao_vai_para_outras_publicacoes,
    teste_sem_faixa_generica_a_geracao_bloqueia,
    teste_radar_escolhido_a_mao_preserva_a_procedencia,
    teste_item_manual_com_fonte_livre_vai_para_outras_publicacoes,
    teste_secao_padrao_manual_continua_tendo_precedencia,
    teste_faixa_outras_publicacoes_existe_nos_nove_templates,
    teste_fonte_nova_publica_na_propria_secao,
    teste_mecanismo_de_alias_continua_disponivel,
    teste_ancora_do_voltar_ao_sumario_existe,
    teste_todas_as_fontes_do_filtro1_tem_destino,
]


def main():
    falhas = 0

    for teste in TESTES:
        try:
            teste()
        except AssertionError as erro:
            falhas += 1
            print(f"FALHOU  {teste.__name__}: {erro}")
        except Exception as erro:  # pragma: no cover - erro inesperado
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
