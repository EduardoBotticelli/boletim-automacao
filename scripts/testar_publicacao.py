"""
Testes do scripts/publicar_saidas.sh, o passo que commita e envia as saidas
do workflow.

Cada teste monta um repositorio remoto de verdade (git init --bare) numa
pasta temporaria, um clone que faz o papel do runner e outro que faz o papel
do portal, que grava as decisoes no mesmo ramo durante a execucao. Nada sai
da maquina.

Rodar: python scripts/testar_publicacao.py
"""

import os
import subprocess
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SCRIPT = BASE / "scripts" / "publicar_saidas.sh"
WORKFLOW = BASE / ".github" / "workflows" / "boletim.yml"
AMBIENTE = dict(
    os.environ,
    PUBLICAR_ESPERA="0",
    GIT_AUTHOR_NAME="teste", GIT_AUTHOR_EMAIL="teste@exemplo",
    GIT_COMMITTER_NAME="teste", GIT_COMMITTER_EMAIL="teste@exemplo",
)


def git(pasta, *args, checar=True):
    resultado = subprocess.run(["git", *args], cwd=pasta, env=AMBIENTE, capture_output=True, text=True)
    if checar and resultado.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} falhou: {resultado.stderr}")
    return resultado


def publicar(pasta, mensagem, *caminhos):
    return subprocess.run(["bash", str(SCRIPT), mensagem, "main", *caminhos], cwd=pasta, env=AMBIENTE, capture_output=True, text=True)


def escrever(pasta, caminho, texto):
    arquivo = Path(pasta) / caminho
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(texto, encoding="utf-8")


def cenario(raiz):
    """Remoto com a main de producao, o clone do runner e o do portal."""
    remoto = Path(raiz) / "remoto.git"
    git(raiz, "-c", "init.defaultBranch=main", "init", "-q", "--bare", str(remoto))
    semente = Path(raiz) / "semente"
    git(raiz, "clone", "-q", str(remoto), str(semente))
    git(semente, "checkout", "-q", "-b", "main")
    for caminho, texto in {
        "output/boletim.json": "edicao anterior\n", "output/log_execucao.json": "log anterior\n",
        "output/validacao_a.html": "validacao anterior\n", "output/decisoes_alice.json": "decisoes anteriores\n",
        "output/auditoria.html": "auditoria anterior\n",
    }.items():
        escrever(semente, caminho, texto)
    git(semente, "add", ".")
    git(semente, "commit", "-q", "-m", "producao")
    git(semente, "push", "-q", "origin", "main")
    runner = Path(raiz) / "runner"
    portal = Path(raiz) / "portal"
    git(raiz, "clone", "-q", str(remoto), str(runner))
    git(raiz, "clone", "-q", str(remoto), str(portal))
    return remoto, runner, portal


def coleta_rodou(runner):
    """O que a etapa 'Gerar Radares' deixa no runner: nada commitado."""
    escrever(runner, "output/boletim.json", "edicao nova\n")
    escrever(runner, "output/log_execucao.json", "log novo\n")
    escrever(runner, "output/validacao_a.html", "validacao nova\n")
    escrever(runner, "output/auditoria.html", "auditoria nova\n")
    escrever(runner, "output/dossier/indice.json", "{}\n")
    escrever(runner, "output/dossier/anp-noticias.md", "pagina\n")


def portal_grava_decisoes(portal):
    escrever(portal, "output/decisoes_alice.json", "decisoes novas\n")
    git(portal, "commit", "-q", "-am", "boletins-finais: revisao")
    git(portal, "push", "-q", "origin", "main")


def no_remoto(remoto, caminho):
    return git(remoto, "show", f"main:{caminho}").stdout


def teste_o_comando_antigo_trava_com_saida_nao_commitada():
    # Reproduz a falha de 01/10: o dossier e commitado sozinho, o boletim.json
    # fica modificado e o 'git pull --rebase' se recusa a rodar.
    with tempfile.TemporaryDirectory() as raiz:
        _, runner, _ = cenario(raiz)
        coleta_rodou(runner)
        git(runner, "add", "output/dossier", "output/log_execucao.json")
        git(runner, "commit", "-q", "-m", "Guarda a coleta")
        antigo = git(runner, "pull", "--rebase", "origin", "main", checar=False)
        assert antigo.returncode != 0 and "unstaged changes" in antigo.stderr, antigo.stderr


def teste_dossier_e_commit_oficial_saem_mesmo_com_o_ramo_andando():
    with tempfile.TemporaryDirectory() as raiz:
        remoto, runner, portal = cenario(raiz)
        coleta_rodou(runner)
        portal_grava_decisoes(portal)  # a curadoria confirmou durante a coleta

        dossier = publicar(runner, "Guarda a coleta", "output/dossier", "output/log_execucao.json")
        assert dossier.returncode == 0, dossier.stdout + dossier.stderr
        assert no_remoto(remoto, "output/dossier/indice.json") == "{}\n"
        assert no_remoto(remoto, "output/decisoes_alice.json") == "decisoes novas\n"
        # O que ficou fora do commit do dossier continua modificado no runner.
        assert (runner / "output/boletim.json").read_text() == "edicao nova\n"
        assert no_remoto(remoto, "output/boletim.json") == "edicao anterior\n"

        caminhos = ["output/boletim.json", "output/log_execucao.json", "output/auditoria.html", *sorted(str(p.relative_to(runner)) for p in runner.glob("output/validacao_*.html"))]
        oficial = publicar(runner, "Atualiza Radares", *caminhos)
        assert oficial.returncode == 0, oficial.stdout + oficial.stderr
        assert no_remoto(remoto, "output/boletim.json") == "edicao nova\n"
        assert no_remoto(remoto, "output/validacao_a.html") == "validacao nova\n"
        assert no_remoto(remoto, "output/decisoes_alice.json") == "decisoes novas\n"
        mensagens = git(remoto, "log", "--format=%s", "main").stdout.splitlines()
        assert mensagens[:3] == ["Atualiza Radares", "Guarda a coleta", "boletins-finais: revisao"], mensagens


def teste_push_recusado_tenta_de_novo():
    with tempfile.TemporaryDirectory() as raiz:
        remoto, runner, _ = cenario(raiz)
        gancho = remoto / "hooks" / "pre-receive"
        gancho.write_text('#!/bin/sh\nif [ ! -f "$GIT_DIR/recusou" ]; then touch "$GIT_DIR/recusou"; exit 1; fi\nexit 0\n')
        gancho.chmod(0o755)
        coleta_rodou(runner)
        resultado = publicar(runner, "Guarda a coleta", "output/dossier")
        assert resultado.returncode == 0, resultado.stdout + resultado.stderr
        assert "tentativa 1 de 3" in resultado.stdout
        assert no_remoto(remoto, "output/dossier/indice.json") == "{}\n"


def teste_conflito_para_com_erro_sem_rebase_pela_metade():
    with tempfile.TemporaryDirectory() as raiz:
        remoto, runner, portal = cenario(raiz)
        coleta_rodou(runner)
        escrever(portal, "output/boletim.json", "outra edicao\n")
        git(portal, "commit", "-q", "-am", "outra edicao")
        git(portal, "push", "-q", "origin", "main")
        resultado = publicar(runner, "Atualiza Radares", "output/boletim.json")
        assert resultado.returncode != 0
        assert "::error" in resultado.stdout
        assert not (runner / ".git" / "rebase-merge").exists() and not (runner / ".git" / "rebase-apply").exists()
        assert no_remoto(remoto, "output/boletim.json") == "outra edicao\n"


def teste_nada_a_publicar_nao_cria_commit():
    with tempfile.TemporaryDirectory() as raiz:
        remoto, runner, _ = cenario(raiz)
        antes = git(remoto, "rev-parse", "main").stdout
        assert publicar(runner, "x", "output/nao-existe.json").returncode == 0
        assert publicar(runner, "x", "output/boletim.json").returncode == 0  # sem mudanca
        assert git(remoto, "rev-parse", "main").stdout == antes


def teste_o_workflow_so_publica_pelo_script():
    texto = WORKFLOW.read_text(encoding="utf-8")
    assert "git pull --rebase origin" not in texto and "git push" not in texto, "commit e push do workflow devem passar pelo publicar_saidas.sh"
    assert texto.count("bash scripts/publicar_saidas.sh") == 5
    assert "python scripts/testar_publicacao.py" in texto


TESTES = [
    teste_o_comando_antigo_trava_com_saida_nao_commitada,
    teste_dossier_e_commit_oficial_saem_mesmo_com_o_ramo_andando,
    teste_push_recusado_tenta_de_novo,
    teste_conflito_para_com_erro_sem_rebase_pela_metade,
    teste_nada_a_publicar_nao_cria_commit,
    teste_o_workflow_so_publica_pelo_script,
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
