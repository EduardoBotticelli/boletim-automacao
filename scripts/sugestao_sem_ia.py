"""
Radar sugerido, sem IA, para a publicacao que o Gemini nao devolveu.

Em 30/09, com os tres primeiros modelos da cascata em 503, o flash-lite
devolveu 43 das 82 publicacoes coletadas direto das fontes. As 38 que
faltaram foram ao portal sem Radar. Aqui cada uma recebe um Radar sugerido
quando uma regra fixa consegue decidir com seguranca, na ordem:

1. matriz: o Filtro 1 da fonte liga a fonte a um Radar so (Receita ->
   Tributario, INPI -> Propriedade Intelectual).
2. palavras-chave: os termos de "Palavras e temas indicativos" de cada Radar
   no prompt.md, contados so entre os Radares do Filtro 1 da fonte. Termo
   que aparece na lista de tres ou mais Radares nao conta, nem o que e o
   nome da propria fonte ("Banco Central" numa norma do Banco Central). O
   Radar vencedor precisa de um termo composto ("oferta publica") ou de dois
   termos diferentes; empate so se resolve pelo perfil da fonte.
3. perfil da fonte: o Radar predominante da fonte no historico, declarado
   em "radar_predominante" na definicao dela (Banco Central -> Mercado de
   Capitais: 74 de 74 publicacoes de 13/07 a 29/09).

Fonte generica (Planalto, Diario Oficial, Destaques do DOU, Ministerio da
Fazenda) nunca passa pela matriz nem pelo perfil: so recebe sugestao por
palavras-chave, com dois termos diferentes e um Radar a frente dos outros.
Nunca vai para todos os Radares, e sempre para um so.

O Radar sugerido precisa estar no Filtro 1 da fonte e ter secao propria
para ela no template (a mesma resolucao do gerador final). Se os templates
nao puderem ser lidos, nenhuma sugestao e feita.

A sugestao nunca vai para 'boletins': fica em 'sugestao_sem_ia', e o
motivo_filtragem diz que ela nao veio da IA. O portal mostra o item como
pendente, com o Radar ja marcado, e a pessoa confirma, troca ou rejeita.
O que nenhuma regra decide continua indo sem Radar, com o motivo.

Avaliacao nos 148 itens de 01/09 a 29/09 (decisao da curadoria quando
havia, da IA nos demais; perfil calculado so com 13/07 a 31/08): 49
receberiam Radar pelo titulo, 46 iguais a decisao (94%), nenhum em Radar
errado, 3 em itens que a IA deixou sem Radar. Ver docs/sugestao-sem-ia.md.
"""

import re
import unicodedata
from collections import Counter
from urllib.parse import urlparse

METODOS = ("matriz", "palavras_chave", "perfil_da_fonte")
ROTULOS = {
    "matriz": "matriz do Filtro 1",
    "palavras_chave": "palavras-chave do prompt.md",
    "perfil_da_fonte": "perfil da fonte",
}
# Termo presente nas listas de tantos Radares ou mais nao distingue nenhum.
LIMITE_RADARES_POR_TERMO = 3
# Fonte generica precisa de ao menos tantos termos distintos do mesmo Radar.
MINIMO_TERMOS_GENERICA = 2
FONTE_GENERICA = re.compile(r"planalto|diario oficial|\bd\.?o\.?u\b|ministerio da fazenda", re.I)
SECAO_PALAVRAS = "## Palavras e temas indicativos"
SECAO_PROJETOS = "## Projetos em acompanhamento"
SIGLA = re.compile(r"[A-Z0-9&]{2,8}")


def sem_acento(valor):
    return "".join(c for c in unicodedata.normalize("NFD", str(valor or "")) if unicodedata.category(c) != "Mn")


def normalizar(valor):
    return " ".join(sem_acento(valor).lower().split())


class Termo:
    """
    Um termo do prompt.md. Sigla curta (ANA, CAT, NR, PLD) so casa em
    maiusculas: em minusculas ela aparece dentro de nomes e palavras comuns.
    """

    def __init__(self, original):
        self.original = " ".join(original.split())
        self.sigla = bool(SIGLA.fullmatch(self.original))
        self.chave = normalizar(self.original)
        self.composto = " " in self.chave
        alvo = sem_acento(self.original) if self.sigla else self.chave
        corpo = r"\s+".join(re.escape(parte) for parte in alvo.split())
        self.padrao = re.compile(r"(?<![A-Za-z0-9])" + corpo + r"(?![A-Za-z0-9])", 0 if self.sigla else re.I)

    def casa(self, texto_sem_acento):
        return bool(self.padrao.search(texto_sem_acento))


def _trecho(bloco, titulo):
    if titulo not in bloco:
        return ""
    resto = bloco.split(titulo, 1)[1]
    return re.split(r"\n(?:#{1,2} |---)", resto, maxsplit=1)[0]


def termos_do_prompt(texto_prompt):
    """
    {slug: [Termo]} a partir das secoes "Palavras e temas indicativos" (e
    "Projetos em acompanhamento") de cada Radar do prompt.md. Descarta o
    termo que aparece na lista de LIMITE_RADARES_POR_TERMO Radares ou mais.
    """
    brutos = {}
    for bloco in re.split(r"\n(?=# \d+\. )", texto_prompt):
        achado = re.search(r"Slug técnico:\s*`([^`]+)`", bloco)
        if not achado:
            continue
        termos = [t.strip(" .\t") for t in re.split(r"[;\n]", _trecho(bloco, SECAO_PALAVRAS))]
        termos += [linha.strip(" -*.\t") for linha in _trecho(bloco, SECAO_PROJETOS).splitlines() if linha.strip().startswith(("-", "*"))]
        vistos = {}
        for termo in termos:
            if len(termo) >= 2 and normalizar(termo) not in vistos:
                vistos[normalizar(termo)] = termo
        brutos[achado.group(1)] = vistos
    frequencia = Counter(chave for termos in brutos.values() for chave in termos)
    return {
        slug: [Termo(original) for chave, original in termos.items() if frequencia[chave] < LIMITE_RADARES_POR_TERMO]
        for slug, termos in brutos.items()
    }


def secoes_dos_templates(fontes, slugs):
    """
    {fonte: {slugs em que a fonte tem secao propria no template}}, com a
    mesma leitura do gerador final (template oficial mais os ajustes
    autorizados). Levanta excecao se algum template nao puder ser lido.
    """
    import ajustes_templates
    import gerar_boletim_final as final
    import templates_radar

    mapeamento = final.carregar_mapeamento()
    aliases = mapeamento.get("aliases_fonte", {})
    config = ajustes_templates.carregar_config()
    com_secao = {fonte: set() for fonte in fontes}
    for slug in slugs:
        template = templates_radar.carregar_template(str(final.TEMPLATES_DIR / mapeamento["templates"][slug]))
        html_ajustado, _ = ajustes_templates.aplicar(template.html, slug, config)
        secoes = templates_radar.analisar(html_ajustado).secoes
        for fonte in fontes:
            if final.resolver_secao(fonte, slug, secoes, aliases):
                com_secao[fonte].add(slug)
    return com_secao


class Sugestor:
    """
    termos: {slug: [Termo]}, de termos_do_prompt.
    filtro1: {fonte: [slugs]} (o MAPA do gerar_boletim).
    com_secao: {fonte: set(slugs)} com secao propria no template.
    fontes: {fonte: definicao}, para url, "generica" e "radar_predominante".
    nomes: {slug: nome do Radar}, so para o texto do motivo.
    """

    def __init__(self, termos, filtro1, com_secao, fontes=None, nomes=None):
        self.termos = termos
        self.filtro1 = {normalizar(k): list(v) for k, v in filtro1.items()}
        self.com_secao = {normalizar(k): set(v) for k, v in com_secao.items()}
        self.fontes = {normalizar(k): v for k, v in (fontes or {}).items()}
        self.nomes = nomes or {}
        self.todos = {s for slugs in self.filtro1.values() for s in slugs}

    def generica(self, fonte, permitidos):
        definicao = self.fontes.get(normalizar(fonte)) or {}
        return bool(definicao.get("generica")) or bool(FONTE_GENERICA.search(sem_acento(fonte))) or (
            len(permitidos) > 1 and set(permitidos) >= self.todos
        )

    def _nome_da_fonte(self, fonte):
        definicao = self.fontes.get(normalizar(fonte)) or {}
        host = (urlparse(definicao.get("url", "")).hostname or "").replace(".", " ")
        return f" {normalizar(fonte)} {host} "

    def palavras(self, item, permitidos):
        texto = sem_acento(f"{item.get('titulo', '')} {item.get('resumo', '')}")
        proprio = self._nome_da_fonte(item.get("fonte", ""))
        achados = {}
        for slug in permitidos:
            casados = sorted({t.original for t in self.termos.get(slug, []) if f" {t.chave} " not in proprio and t.casa(texto)})
            if casados:
                achados[slug] = casados
        return achados

    def _nome(self, slug):
        return self.nomes.get(slug, slug)

    def sugerir(self, item):
        """
        {"radares": [slug], "metodo": ..., "evidencia": ...}, ou radares vazio
        com "motivo_sem_radar" quando nenhuma regra decide com seguranca.
        """
        fonte = item.get("fonte", "")
        chave = normalizar(fonte)
        filtro = self.filtro1.get(chave)
        if filtro is None:
            return {"radares": [], "metodo": None, "motivo_sem_radar": "fonte fora da matriz do Filtro 1"}
        permitidos = [s for s in filtro if s in self.com_secao.get(chave, set())]
        if not permitidos:
            return {"radares": [], "metodo": None, "motivo_sem_radar": "nenhum Radar do Filtro 1 tem seção para a fonte no template"}
        generica = self.generica(fonte, permitidos)
        if len(permitidos) == 1 and not generica:
            slug = permitidos[0]
            return {"radares": [slug], "metodo": "matriz", "evidencia": f"o Filtro 1 liga {fonte} só ao {self._nome(slug)}"}

        achados = self.palavras(item, permitidos)
        predominante = ((self.fontes.get(chave) or {}).get("radar_predominante") or {})
        perfil = predominante.get("radar") if not generica and predominante.get("radar") in permitidos else None
        if achados:
            maximo = max(len(v) for v in achados.values())
            vencedores = [s for s in permitidos if len(achados.get(s, [])) == maximo]
            if generica:
                if maximo >= MINIMO_TERMOS_GENERICA and len(vencedores) == 1:
                    slug = vencedores[0]
                    return self._por_palavras(slug, achados[slug])
                return {"radares": [], "metodo": None, "motivo_sem_radar": "fonte genérica sem dois termos de um Radar só: " + self._resumo(achados)}
            if len(vencedores) > 1:
                if perfil in vencedores:
                    return self._por_palavras(perfil, achados[perfil], desempate=True)
                return {"radares": [], "metodo": None, "motivo_sem_radar": "palavras-chave empatadas: " + self._resumo(achados)}
            slug = vencedores[0]
            if len(achados[slug]) >= 2 or any(" " in t.strip() for t in achados[slug]):
                return self._por_palavras(slug, achados[slug])
        elif generica:
            return {"radares": [], "metodo": None, "motivo_sem_radar": "fonte genérica sem palavra-chave de Radar"}

        if perfil:
            return {
                "radares": [perfil], "metodo": "perfil_da_fonte",
                "evidencia": f"{self._nome(perfil)} é o Radar predominante de {fonte} ({predominante.get('base', 'histórico da fonte')})",
            }
        if achados:
            return {"radares": [], "metodo": None, "motivo_sem_radar": "só um termo genérico: " + self._resumo(achados)}
        return {"radares": [], "metodo": None, "motivo_sem_radar": "nenhuma palavra-chave de Radar no título ou na descrição"}

    def _por_palavras(self, slug, termos, desempate=False):
        evidencia = f"termos do {self._nome(slug)} no prompt.md: " + ", ".join(f'"{t}"' for t in termos)
        if desempate:
            evidencia += " (empate desfeito pelo perfil da fonte)"
        return {"radares": [slug], "metodo": "palavras_chave", "evidencia": evidencia}

    def _resumo(self, achados):
        return "; ".join(f"{self._nome(s)}: " + ", ".join(v) for s, v in achados.items())


def motivo(sugestao, modelo, nomes):
    """O texto que o portal mostra no item."""
    inicio = f"A IA ({modelo or 'nenhum modelo'}) não devolveu esta publicação."
    if sugestao["radares"]:
        radares = ", ".join(nomes.get(s, s) for s in sugestao["radares"])
        return (
            f"[Sugestão sem IA: {radares}, por {ROTULOS[sugestao['metodo']]}] {inicio} "
            f"O Radar foi sugerido por regra fixa, não pela IA: {sugestao['evidencia']}. "
            "Confirme, troque o Radar ou rejeite."
        )
    return (
        f"[Não classificada pela IA] {inicio} Nenhuma regra sem IA sugeriu Radar com segurança "
        f"({sugestao['motivo_sem_radar']}). Escolha o Radar ou rejeite."
    )


def distribuir(itens, sugestor, modelo, nomes):
    """
    Aplica o sugestor aos itens marcados com 'nao_classificada_pela_ia' e
    devolve o resumo para o log. 'boletins' nao e tocado: a sugestao fica em
    'sugestao_sem_ia' e so vale depois que a pessoa confirmar no portal.
    """
    resumo = {"itens": 0, "com_radar_sugerido": 0, "por_metodo": {m: 0 for m in METODOS}, "sem_radar": 0,
              "por_radar": {}, "motivos_sem_radar": {}, "por_fonte": {}}
    for item in itens:
        if not item.get("nao_classificada_pela_ia"):
            continue
        if item.get("exclusao_editorial_automatica"):
            sugestao = {"radares": [], "metodo": None, "motivo_sem_radar": "comunicação institucional, sem impacto jurídico externo"}
        elif sugestor is None:
            sugestao = {"radares": [], "metodo": None, "motivo_sem_radar": "sugestão sem IA indisponível nesta execução"}
        else:
            sugestao = sugestor.sugerir(item)
        item["sugestao_sem_ia"] = sugestao
        item["motivo_filtragem"] = motivo(sugestao, modelo, nomes)
        resumo["itens"] += 1
        por_fonte = resumo["por_fonte"].setdefault(item.get("fonte", ""), {"itens": 0, "sem_radar": 0, **{m: 0 for m in METODOS}})
        por_fonte["itens"] += 1
        if sugestao["radares"]:
            resumo["com_radar_sugerido"] += 1
            resumo["por_metodo"][sugestao["metodo"]] += 1
            por_fonte[sugestao["metodo"]] += 1
            for slug in sugestao["radares"]:
                resumo["por_radar"][slug] = resumo["por_radar"].get(slug, 0) + 1
        else:
            resumo["sem_radar"] += 1
            por_fonte["sem_radar"] += 1
            razao = sugestao["motivo_sem_radar"].split(":")[0]
            resumo["motivos_sem_radar"][razao] = resumo["motivos_sem_radar"].get(razao, 0) + 1
    return resumo
