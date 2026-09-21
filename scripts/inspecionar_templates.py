"""
Relatório dos templates oficiais dos Radares.

Mostra, para cada template .msg, as seções de fonte com suas âncoras, quantas
imagens ele carrega e quais fontes do Filtro 1 ainda não têm seção. É o que
usar quando o gerador bloquear com "fonte sem seção no template": o relatório
diz quais âncoras existem para preencher templates/mapeamento_radares.json.

Uso: python scripts/inspecionar_templates.py
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))

import templates_radar  # noqa: E402

TEMPLATES_DIR = BASE_DIR / "templates"
MAPEAMENTO_PATH = TEMPLATES_DIR / "mapeamento_radares.json"
GERADOR_COLETA = BASE_DIR / "scripts" / "gerar_boletim.py"


def fontes_permitidas_por_radar():
    """
    Lê o MAPA do Filtro 1 direto do gerar_boletim.py.

    O arquivo é lido como texto para não arrastar as dependências de coleta
    (Firecrawl e Gemini) só para montar um relatório.
    """
    if not GERADOR_COLETA.exists():
        return {}

    codigo = GERADOR_COLETA.read_text(encoding="utf-8")
    espaco = {}

    for padrao in (r"^SLUGS = \[.*?\]$", r"^MAPA = \{.*?^\}$"):
        encontrado = re.search(padrao, codigo, re.M | re.S)
        if not encontrado:
            return {}
        exec(encontrado.group(0), espaco)  # noqa: S102

    permitidas = {slug: set() for slug in espaco["SLUGS"]}
    for fonte, slugs in espaco["MAPA"].items():
        for slug in slugs:
            permitidas.setdefault(slug, set()).add(fonte)

    return permitidas


def main():
    mapeamento = json.loads(MAPEAMENTO_PATH.read_text(encoding="utf-8"))
    permitidas = fontes_permitidas_por_radar()
    aliases = mapeamento.get("aliases_fonte", {})

    lacunas = []

    for slug, arquivo in mapeamento["templates"].items():
        caminho = TEMPLATES_DIR / arquivo
        template = templates_radar.carregar_template(str(caminho))
        estrutura = templates_radar.analisar(template.html)

        print("=" * 78)
        print(f"{slug}  ->  {arquivo}")
        print(
            f"  HTML: {len(template.html)} bytes | "
            f"imagens: {len(template.recursos)} | "
            f"seções: {len(estrutura.secoes)}"
        )
        print(f"  {'ÂNCORA':<28} SEÇÃO")
        for secao in estrutura.secoes:
            print(f"  {secao.ancora:<28} {secao.nome}")

        for fonte in sorted(permitidas.get(slug, [])):
            if _tem_secao(fonte, slug, estrutura.secoes, aliases):
                continue
            lacunas.append((slug, fonte))

        print()

    print("=" * 78)
    if lacunas:
        print("FONTES DO FILTRO 1 SEM SEÇÃO NO TEMPLATE")
        print("(uma notícia dessas fontes bloqueia a geração do Radar)")
        for slug, fonte in lacunas:
            print(f"  {slug:<28} {fonte}")
    else:
        print("Todas as fontes do Filtro 1 têm seção no template do Radar.")


def _tem_secao(fonte, slug, secoes, aliases):
    normalizar = templates_radar.normalizar
    orgao = normalizar(str(fonte).split("|")[0])

    for chave, destinos in aliases.items():
        if isinstance(destinos, dict) and normalizar(chave) == orgao:
            if destinos.get(slug):
                return True

    for secao in secoes:
        nome = normalizar(secao.nome)
        if not nome or not orgao:
            continue
        if nome == orgao or nome.startswith(orgao + " ") or orgao.startswith(nome + " "):
            return True

    return False


if __name__ == "__main__":
    main()
