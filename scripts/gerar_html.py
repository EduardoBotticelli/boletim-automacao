"""Gera nove páginas HTML de validação sem alterar email_<slug>.html."""

import datetime, html, json, os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_PATH = os.path.join(BASE_DIR, "output", "boletim.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
PADRAO = {
    "trabalhista-empresarial": "Radar Trabalhista Empresarial",
    "direito-tributario": "Radar Tributário",
    "societario-ma": "Radar Societário, Fusões e Aquisições",
    "mercado-capitais-fundos": "Radar Mercado de Capitais e Fundos de Investimento",
    "regulatorio-oleo-gas": "Radar Regulatório e Óleo e Gás",
    "imobiliario-infraestrutura": "Radar Negócios Imobiliários e Infraestrutura",
    "ambiental-esg": "Radar Ambiental e ESG",
    "propriedade-intelectual": "Radar Propriedade Intelectual, Tecnologia e Privacidade",
    "contencioso-civel": "Radar Solução de Conflitos",
}


def e(v):
    return html.escape(str(v or ""), quote=True)


def data(v):
    try:
        return datetime.date.fromisoformat(str(v)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return str(v or "Data não identificada")


def fontes_radar(m, s):
    return [f for f, r in m.items() if isinstance(r, list) and s in r]


def lista_fontes(v):
    out = []
    for x in v if isinstance(v, list) else []:
        if isinstance(x, dict):
            nome = str(x.get("fonte", "")).strip()
            detalhe = "; ".join(
                (
                    y
                    for y in [
                        str(x.get("motivo", "")).strip(),
                        (
                            "retomada em " + str(x.get("reativar_em"))
                            if x.get("reativar_em")
                            else ""
                        ),
                    ]
                    if y
                )
            )
        else:
            nome = str(x).strip()
            detalhe = ""
        if nome:
            out.append(nome + (f" ({detalhe})" if detalhe else ""))
    return out


def item(x):
    link = (
        f"""<a href="{e(x.get('url'))}">Acessar publicação</a>"""
        if x.get("url")
        else ""
    )
    pcs = ", ".join(
        (e(p) for p in x.get("palavras_chave_detectadas", []) if isinstance(p, str))
    )
    return f"""<article><div class="meta">{e(x.get('fonte'))} · {e(data(x.get('data_publicacao')))}</div><h3>{e(x.get('titulo', 'Sem título'))}</h3><p>{e(x.get('resumo'))}</p>{link}<small><b>Termos:</b> {pcs or 'Não informados'}</small></article>"""


def pagina(slug, nome, desc, clusters, fontes, email, defeso, itens, modelo, janela):
    grupos = {}
    for x in itens:
        grupos.setdefault(str(x.get("fonte", "Fonte não identificada")), []).append(x)
    corpo = (
        "".join(
            (
                f"<h2>{e(f)} ({len(v)})</h2>" + "".join((item(x) for x in v))
                for f, v in grupos.items()
            )
        )
        or '<div class="vazio">Nenhum item classificado neste Radar.</div>'
    )
    avisos = ""
    if email:
        avisos += f"""<div class="aviso"><b>Fontes por e-mail ainda não integradas:</b> {e(', '.join(email))}</div>"""
    if defeso:
        avisos += f"""<div class="defeso"><b>Fontes temporariamente suspensas:</b> {e(', '.join(defeso))}</div>"""
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{e(nome)} - Validação</title><style>body{{margin:0;background:#f0f2f1;font-family:Arial;color:#1f2937}}main{{max-width:760px;margin:24px auto;background:white}}header{{background:#0d3320;color:white;padding:34px}}header p{{color:#a8d8b9}}section{{padding:22px 34px}}h2{{font-size:13px;background:#f5f8f6;padding:12px;color:#1a4d2e}}article{{padding:18px 0;border-bottom:1px solid #e5e7eb}}h3{{color:#0d3320}}.meta,small{{display:block;color:#6b7280;font-size:11px;margin:8px 0}}a{{color:#0d3320;font-weight:bold}}.aviso,.defeso{{padding:14px 34px}}.aviso{{background:#fff8e6}}.defeso{{background:#fef2f2}}.vazio{{padding:50px;text-align:center}}</style></head><body><main><header><small>VALIDAÇÃO DA CURADORIA AUTOMATIZADA</small><h1>{e(nome)}</h1><p>{e(desc)}</p></header><section><b>Clusters:</b> {e(', '.join(clusters))}<br><b>Modelo Gemini:</b> {e(modelo)}<br><b>Fontes configuradas:</b> {e(', '.join(fontes))}</section>{avisos}<section>{corpo}</section><section><small>Janela: {e(janela.get('inicio'))} até {e(janela.get('fim'))}</small></section></main></body></html>"""


def main():
    with open(INPUT_PATH, encoding="utf-8") as a:
        b = json.load(a)
    if not isinstance(b.get("itens"), list) or b.get("erro"):
        raise SystemExit("ERRO: boletim.json inválido.")
    c = b.get("boletins_config", {})
    slugs = c.get("boletins_disponiveis", list(PADRAO))
    nomes = c.get("nomes_radares", {})
    mapa = c.get("mapeamento_fonte_boletim", {})
    emails = c.get("fontes_email_pendentes", {})
    susp = c.get("fontes_em_defeso", [])
    susp_nomes = lista_fontes(susp)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for s in slugs:
        itens = [
            x for x in b["itens"] if isinstance(x, dict) and s in x.get("boletins", [])
        ]
        html_ = pagina(
            s,
            nomes.get(s, PADRAO.get(s, s)),
            c.get("descricao", ""),
            c.get("clusters_por_boletim", {}).get(s, []),
            fontes_radar(mapa, s),
            lista_fontes(emails.get(s, [])),
            susp_nomes,
            itens,
            b.get("modelo_gemini_utilizado", ""),
            b.get("janela_aplicada", {}),
        )
        with open(
            os.path.join(OUTPUT_DIR, "validacao_" + s + ".html"), "w", encoding="utf-8"
        ) as a:
            a.write(html_)
        print("Validação", s, ":", len(itens), "itens")


if __name__ == "__main__":
    main()
