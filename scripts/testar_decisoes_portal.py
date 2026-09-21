"""
Testa o contrato entre o portal de curadoria e o gerar_boletim_final.py.

Este teste não depende de rede, de credenciais nem do repositório real: cada
caso monta um boletim.json e um decisoes_alice.json em um diretório temporário
que imita a estrutura do repositório, executa o scripts/gerar_boletim_final.py
como subprocesso e verifica o resultado.

O que ele protege:
- o formato canônico gravado pelo portal gera os nove email_<slug>.html;
- itens adicionados manualmente na curadoria são publicados;
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
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPT = BASE_DIR / "scripts" / "gerar_boletim_final.py"

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


def executar(boletim, decisoes):
    """
    Roda o gerar_boletim_final.py em uma cópia isolada do repositório.

    Devolve (returncode, saida, conteudo_dos_emails, resumo).
    """
    with tempfile.TemporaryDirectory() as raiz:
        raiz = Path(raiz)
        (raiz / "scripts").mkdir()
        saida_dir = raiz / "output"
        saida_dir.mkdir()

        shutil.copy2(SCRIPT, raiz / "scripts" / SCRIPT.name)

        (saida_dir / "boletim.json").write_text(
            json.dumps(boletim, ensure_ascii=False), encoding="utf-8"
        )
        (saida_dir / "decisoes_alice.json").write_text(
            json.dumps(decisoes, ensure_ascii=False), encoding="utf-8"
        )

        # E-mails de uma edição anterior: nenhuma falha pode sobrescrevê-los.
        for slug in SLUGS:
            (saida_dir / f"email_{slug}.html").write_text(SENTINELA, encoding="utf-8")

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

        resumo_path = saida_dir / "resumo_geracao_final.json"
        resumo = (
            json.loads(resumo_path.read_text(encoding="utf-8"))
            if resumo_path.exists()
            else {}
        )

        return processo.returncode, processo.stdout + processo.stderr, emails, resumo


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
                ["mercado-capitais-fundos", "ambiental-esg"],
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
                "STJ fixa tese sobre honorários",
                "https://www.stj.jus.br/noticia-honorarios",
                "STJ | Notícias",
                "aprovado",
                ["contencioso-civel"],
                origem="manual",
                noticia={
                    "fonte": "STJ | Notícias",
                    "categoria": "Adicionado manualmente",
                    "titulo": "STJ fixa tese sobre honorários",
                    "data_publicacao": "2026-08-27",
                    "resumo": "Corte Especial define critérios de fixação.",
                    "url": "https://www.stj.jus.br/noticia-honorarios",
                    "boletins": ["contencioso-civel"],
                },
            ),
        ]
    )

    codigo, saida, emails, resumo = executar(boletim_exemplo(), decisoes)

    assert codigo == 0, f"esperava sucesso, saida:\n{saida}"
    assert len(emails) == 9, f"esperava 9 arquivos, veio {len(emails)}"
    assert resumo["status"] == "sucesso"
    assert resumo["total_aprovados"] == 2
    assert resumo["total_itens_manuais"] == 1
    assert resumo["total_rejeitados"] == 1

    # O ajuste manual venceu: a IA sugeriu só mercado-capitais, a curadoria
    # acrescentou ambiental-esg.
    assert "Resolução 244" in emails["mercado-capitais-fundos"]
    assert "Resolução 244" in emails["ambiental-esg"]

    # O item manual foi publicado.
    assert "honorários" in emails["contencioso-civel"]

    # O item rejeitado não aparece em lugar nenhum.
    for slug, conteudo in emails.items():
        assert "CPPI" not in conteudo, f"item rejeitado vazou em {slug}"

    # Radar sem itens continua sendo gerado, com a mensagem de vazio.
    assert "Nenhum item aprovado" in emails["trabalhista-empresarial"]


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

    codigo, saida, emails, _ = executar(boletim_exemplo(), decisoes)

    assert codigo == 0, f"esperava sucesso, saida:\n{saida}"
    html = emails["mercado-capitais-fundos"]
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

    codigo, _, emails, resumo = executar(boletim_exemplo(), decisoes)

    assert codigo != 0, "revisão incompleta deveria bloquear"
    assert resumo["status"] == "bloqueado_por_itens_sem_decisao"
    assert all(conteudo == SENTINELA for conteudo in emails.values())


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

    codigo, _, emails, _ = executar(boletim_exemplo(), decisoes)

    assert codigo != 0, "status pendente deveria bloquear"
    assert all(conteudo == SENTINELA for conteudo in emails.values())


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

    codigo, _, emails, _ = executar(boletim_exemplo(), decisoes)

    assert codigo != 0, "rascunho deveria bloquear"
    assert all(conteudo == SENTINELA for conteudo in emails.values())


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

    codigo, _, emails, resumo = executar(boletim_exemplo(), decisoes)

    assert codigo != 0, "formato legado deveria bloquear"
    assert resumo["status"] == "bloqueado_por_itens_sem_decisao"
    assert all(conteudo == SENTINELA for conteudo in emails.values())


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

    codigo, _, emails, resumo = executar(boletim_exemplo(), decisoes)

    assert codigo != 0, "aprovado sem Radar deveria bloquear"
    assert resumo["status"] == "bloqueado_por_itens_sem_decisao"
    assert all(conteudo == SENTINELA for conteudo in emails.values())


TESTES = [
    teste_fluxo_completo,
    teste_edicoes_de_texto,
    teste_item_sem_decisao_bloqueia,
    teste_status_pendente_bloqueia,
    teste_rascunho_bloqueia,
    teste_formato_legado_bloqueia,
    teste_aprovado_sem_radar_bloqueia,
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
