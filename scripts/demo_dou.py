"""
Demonstracao: quatro jeitos de levar o DOU para o Radar Regulatorio.

Pergunta que motivou: "sera que ele consegue baixar os PDFs do DOU e colocar
junto no e-mail?". Em vez de adivinhar o que a pessoa quer, este script gera o
mesmo Radar Regulatorio de exemplo em quatro versoes, para ela escolher:

  A  link para o PDF oficial da pagina, ao lado de "Acesse a materia";
  B  PDF da pagina onde o ato saiu, anexado a mensagem;
  C  PDF completo da Secao 1 do dia, anexado;
  D  trecho do ato em texto, no proprio e-mail, abaixo do resumo.

E so demonstracao. Nao altera o pipeline, o portal nem o gerador final: usa os
modulos do gerador (templates_radar, ajustes_templates) apenas para ler o
template oficial e montar a mensagem, e grava tudo em output/demo_dou.

De onde vem o DOU, sem Firecrawl:

  inlabs  o servico oficial da Imprensa Nacional para download automatizado
          (inlabs.in.gov.br). Exige cadastro gratuito; as credenciais vem de
          INLABS_EMAIL e INLABS_SENHA. Traz o XML de cada ato e o PDF da Secao 1.
  direto  a leitura do jornal e o PDF da Secao 1 em in.gov.br. Funciona de onde
          o in.gov.br aceita conexao; do runner do GitHub, nao aceita.

Gemini: nenhum. O resumo de cada ato e a ementa do proprio ato.

Uso:
    python scripts/demo_dou.py --data 2026-09-29 --origem inlabs
    python scripts/demo_dou.py --autoteste
"""

import argparse
import copy
import datetime
import html
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from email.message import EmailMessage, MIMEPart
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))

import ajustes_templates  # noqa: E402
import templates_radar  # noqa: E402
from coleta_direta import USER_AGENT  # noqa: E402

SAIDA = BASE / "output" / "demo_dou"
SLUG = "regulatorio-oleo-gas"
ANCORA_DOU = "DiarioOficialUniao"
JORNAL_DO1 = 515
# Orgaos que alimentam o Regulatorio, na ordem de preferencia da amostra.
ORGAOS = ("Agência Nacional do Petróleo", "Agência Nacional de Energia Elétrica", "Ministério de Minas e Energia",
          "Agência Nacional de Mineração", "Conselho Nacional de Política Energética")
TIPOS = ("Resolução", "Portaria", "Despacho", "Deliberação", "Instrução Normativa")
ATOS_NA_AMOSTRA = 4
TAMANHO_TRECHO = 900
ROTULO_PDF = "PDF oficial (página {pagina})"


# ---------------------------------------------------------------------------
# Atos do DOU
# ---------------------------------------------------------------------------


def _texto(html_texto):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", html_texto or "")).split())


def url_pagina_oficial(data, pagina):
    """O visualizador oficial da pagina do DOU, que oferece o PDF dela."""
    return (f"https://pesquisa.in.gov.br/imprensa/jsp/visualiza/index.jsp?"
            f"data={data.strftime('%d/%m/%Y')}&jornal={JORNAL_DO1}&pagina={pagina}")


def ler_xml_inlabs(conteudo_zip, data):
    """Um ato por arquivo XML do pacote diario do INLABS."""
    atos = []
    with zipfile.ZipFile(io.BytesIO(conteudo_zip)) as pacote:
        for nome in pacote.namelist():
            if not nome.lower().endswith(".xml"):
                continue
            artigo = ET.fromstring(pacote.read(nome)).find(".//article")
            if artigo is None:
                continue
            corpo = artigo.find("body")
            campo = lambda n: (corpo.findtext(n) or "") if corpo is not None else ""  # noqa: E731
            pagina = int(re.sub(r"\D", "", artigo.get("numberPage", "") or "0") or 0)
            atos.append({
                "identificacao": _texto(campo("Identifica")) or artigo.get("name", ""),
                "ementa": _texto(campo("Ementa")),
                "texto": _texto(campo("Texto")),
                "orgao": artigo.get("artCategory", ""),
                "tipo": artigo.get("artType", ""),
                "pagina": pagina,
                "edicao": artigo.get("editionNumber", ""),
                "url_ato": artigo.get("pdfPage", "") or url_pagina_oficial(data, pagina),
                "url_pdf_pagina": artigo.get("pdfPage", "") or url_pagina_oficial(data, pagina),
            })
    return atos


def ler_leitura_do_jornal(html_texto, data):
    """Os atos que a pagina de leitura do jornal traz no JSON embutido."""
    achado = re.search(r'<script[^>]*id="params"[^>]*>(.*?)</script>', html_texto, re.S)
    if not achado:
        raise ValueError("a página de leitura do jornal não trouxe o JSON dos atos")
    atos = []
    for item in json.loads(achado.group(1)).get("jsonArray") or []:
        pagina = int(re.sub(r"\D", "", str(item.get("numberPage") or "0")) or 0)
        atos.append({
            "identificacao": _texto(item.get("title") or item.get("titulo")),
            "ementa": "",
            "texto": _texto(item.get("content")),
            "orgao": item.get("hierarchyStr", ""),
            "tipo": item.get("artType", ""),
            "pagina": pagina,
            "edicao": item.get("editionNumber", ""),
            "url_ato": f"https://www.in.gov.br/web/dou/-/{item.get('urlTitle', '')}",
            "url_pdf_pagina": url_pagina_oficial(data, pagina),
        })
    return atos


def escolher_atos(atos, quantidade=ATOS_NA_AMOSTRA):
    """Atos do setor de energia, com tipo normativo, um por orgao, na ordem de ORGAOS."""
    candidatos = [a for a in atos if a["pagina"] and any(a["tipo"].startswith(t) for t in TIPOS)]
    escolhidos = []
    for orgao in ORGAOS:
        for ato in candidatos:
            if orgao in ato["orgao"] and ato not in escolhidos:
                escolhidos.append(ato)
                break
    for ato in candidatos:
        if len(escolhidos) >= quantidade:
            break
        if ato not in escolhidos and any(orgao in ato["orgao"] for orgao in ORGAOS):
            escolhidos.append(ato)
    return escolhidos[:quantidade]


def resumo_do_ato(ato):
    return ato["ementa"] or ato["texto"][:320]


def trecho_do_ato(ato):
    """O comeco do texto do ato, sem repetir a identificacao nem a ementa."""
    texto = ato["texto"]
    for repetido in (ato["identificacao"], ato["ementa"]):
        if repetido and texto.startswith(repetido):
            texto = texto[len(repetido):].strip()
    if len(texto) <= TAMANHO_TRECHO:
        return texto
    corte = texto.rfind(". ", 0, TAMANHO_TRECHO)
    return texto[: corte + 1 if corte > TAMANHO_TRECHO // 2 else TAMANHO_TRECHO].rstrip() + " [...]"


# ---------------------------------------------------------------------------
# Download, sem Firecrawl
# ---------------------------------------------------------------------------


def _abridor():
    import http.cookiejar
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def _baixar(abridor, url, cabecalhos=None, dados=None, limite=200_000_000):
    pedido = urllib.request.Request(url, data=dados, headers={"User-Agent": USER_AGENT, **(cabecalhos or {})})
    with abridor.open(pedido, timeout=120) as resposta:
        return resposta.read(limite)


def pdf_completo_url(data):
    a, m, d = data.strftime("%Y"), data.strftime("%m"), data.strftime("%d")
    return f"https://download.in.gov.br/do/secao1/{a}/{a}_{m}_{d}/{a}_{m}_{d}_ASSINADO_do1.pdf"


def baixar_inlabs(data, email, senha):
    """Login no INLABS e download do XML dos atos e do PDF da Secao 1."""
    abridor = _abridor()
    _baixar(abridor, "https://inlabs.in.gov.br/logar.php",
            {"Content-Type": "application/x-www-form-urlencoded"},
            urllib.parse.urlencode({"email": email, "password": senha}).encode())
    # 'origem' e o cabecalho que os exemplos oficiais do INLABS mandam.
    cabecalhos = {"origem": "736372697074"}
    dia = data.isoformat()
    pacote = _baixar(abridor, f"https://inlabs.in.gov.br/index.php?p={dia}&dl={dia}-DO1.zip", cabecalhos)
    if not pacote.startswith(b"PK"):
        raise RuntimeError("o INLABS não devolveu o pacote do DO1 (login recusado ou edição inexistente)")
    pdf = _baixar(abridor, f"https://inlabs.in.gov.br/index.php?p={dia}&dl={dia.replace('-', '_')}_ASSINADO_do1.pdf", cabecalhos)
    if not pdf.startswith(b"%PDF"):
        raise RuntimeError("o INLABS não devolveu o PDF da Seção 1")
    return ler_xml_inlabs(pacote, data), pdf


def baixar_direto(data):
    abridor = _abridor()
    leitura = _baixar(abridor, f"https://www.in.gov.br/leiturajornal?data={data.strftime('%d-%m-%Y')}&secao=do1").decode("utf-8", "replace")
    pdf = _baixar(abridor, pdf_completo_url(data))
    if not pdf.startswith(b"%PDF"):
        raise RuntimeError("o in.gov.br não devolveu o PDF da Seção 1")
    return ler_leitura_do_jornal(leitura, data), pdf


def paginas_do_pdf(pdf, paginas):
    """Um PDF de uma pagina para cada numero pedido, tirado do PDF completo."""
    from pypdf import PdfReader, PdfWriter

    leitor = PdfReader(io.BytesIO(pdf))
    separadas = {}
    for numero in sorted(set(paginas)):
        if not 1 <= numero <= len(leitor.pages):
            continue
        escritor = PdfWriter()
        escritor.add_page(leitor.pages[numero - 1])
        saida = io.BytesIO()
        escritor.write(saida)
        separadas[numero] = saida.getvalue()
    return separadas


# ---------------------------------------------------------------------------
# Os quatro modelos
# ---------------------------------------------------------------------------


def carregar_template():
    mapeamento = json.loads((BASE / "templates" / "mapeamento_radares.json").read_text(encoding="utf-8"))
    template = templates_radar.carregar_template(str(BASE / "templates" / mapeamento["templates"][SLUG]))
    template.html, _ = ajustes_templates.aplicar(template.html, SLUG, ajustes_templates.carregar_config())
    return template, templates_radar.analisar(template.html), mapeamento


def noticias_do_dou(atos):
    return [{"titulo": f"{ato['identificacao']} ({ato['orgao'].split('/')[-1]})", "url": ato["url_ato"], "resumo": resumo_do_ato(ato)}
            for ato in atos]


def aplicar_modelo_a(corpo, atos):
    """Link para o PDF oficial da pagina, logo depois de "Acesse a materia"."""
    for ato in atos:
        ancora = f'href="{html.escape(ato["url_ato"], quote=True)}" target="_blank" rel="noopener noreferrer">Acesse a matéria</a>'
        link = (f' | <a href="{html.escape(ato["url_pdf_pagina"], quote=True)}" target="_blank" rel="noopener noreferrer">'
                f"{ROTULO_PDF.format(pagina=ato['pagina'])}</a>")
        corpo = corpo.replace(ancora, ancora + link, 1)
    return corpo


def aplicar_modelo_d(corpo, atos):
    """O trecho do ato, em texto, logo abaixo do resumo."""
    for ato in atos:
        resumo = html.escape(resumo_do_ato(ato), quote=True)
        trecho = html.escape(trecho_do_ato(ato), quote=True)
        bloco = (f"<br><span style='font-size:8.0pt;font-family:\"Arial\",sans-serif;color:#404040'>"
                 f"<i>Trecho do ato (DOU, Seção 1, p. {ato['pagina']}):</i> {trecho}</span>")
        corpo = corpo.replace(resumo, resumo + bloco, 1)
    return corpo


def com_anexos(mensagem, anexos):
    """A mensagem do Radar dentro de um multipart/mixed, com os PDFs anexados."""
    externa = EmailMessage()
    for cabecalho in ("Subject", "Date", "Message-ID", "From", "To"):
        if mensagem[cabecalho]:
            externa[cabecalho] = mensagem[cabecalho]
    externa.set_type("multipart/mixed")
    interna = MIMEPart()
    for cabecalho, valor in mensagem.items():
        if cabecalho.lower().startswith("content-"):
            interna[cabecalho] = valor
    interna.set_payload(copy.deepcopy(mensagem.get_payload()))
    externa.attach(interna)
    for nome, dados in anexos:
        parte = MIMEPart()
        parte.set_content(dados, maintype="application", subtype="pdf", filename=nome, disposition="attachment")
        externa.attach(parte)
    return externa


def gerar(atos, pdf_completo, data, destino=SAIDA, base_noticias=None):
    template, estrutura, mapeamento = carregar_template()
    por_ancora = {k: list(v) for k, v in (base_noticias or {}).items()}
    por_ancora[ANCORA_DOU] = noticias_do_dou(atos)
    data_curta = data.strftime("%d.%m.%Y")
    corpo = templates_radar.preencher(template.html, estrutura, data_curta, por_ancora)
    assunto_base = f"{mapeamento['assuntos'].get(SLUG, 'Radar Regulatório')} | {data.strftime('%d/%m/%Y')} | EXEMPLO"
    paginas = paginas_do_pdf(pdf_completo, [a["pagina"] for a in atos])
    variantes = {
        "A": (aplicar_modelo_a(corpo, atos), [], "link para o PDF oficial da página"),
        "B": (corpo, [(f"DOU_Secao1_{data:%Y-%m-%d}_pagina_{n}.pdf", paginas[n]) for n in sorted(paginas)], "PDF da página de cada ato anexado"),
        "C": (corpo, [(f"DOU_Secao1_{data:%Y-%m-%d}_completo.pdf", pdf_completo)], "Seção 1 completa anexada"),
        "D": (aplicar_modelo_d(corpo, atos), [], "trecho do ato em texto"),
    }
    destino.mkdir(parents=True, exist_ok=True)
    resumo = {"data_do_dou": data.isoformat(), "atos": [{k: a[k] for k in ("identificacao", "orgao", "tipo", "pagina", "url_ato", "url_pdf_pagina")} for a in atos],
              "tamanho_pdf_completo_mb": round(len(pdf_completo) / 1e6, 1), "modelos": {}}
    for letra, (html_corpo, anexos, descricao) in variantes.items():
        mensagem = templates_radar.montar_eml(f"{assunto_base} | Modelo {letra}: {descricao}", html_corpo, template.recursos)
        if anexos:
            mensagem = com_anexos(mensagem, anexos)
        eml = mensagem.as_bytes()
        (destino / f"modelo_{letra}.eml").write_bytes(eml)
        resumo["modelos"][letra] = {"descricao": descricao, "anexos": [n for n, _ in anexos], "tamanho_eml_mb": round(len(eml) / 1e6, 2)}
        print(f"Modelo {letra} ({descricao}): {len(eml) / 1e6:.2f} MB, {len(anexos)} anexo(s)")
    (destino / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
    return resumo


def noticias_do_radar(boletim_path=BASE / "output" / "boletim.json", limite=8):
    """As outras noticias do exemplo: as que a IA sugeriu para o Regulatorio."""
    import gerar_boletim_final as final

    try:
        boletim = json.loads(boletim_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    itens = [i for i in boletim.get("itens") or [] if SLUG in (i.get("boletins") or [])][:limite]
    _, estrutura, mapeamento = carregar_template()
    por_ancora, _, _ = final.agrupar_por_secao(itens, SLUG, estrutura.secoes, mapeamento.get("aliases_fonte", {}),
                                               "", ajustes_templates.ancora_generica(ajustes_templates.carregar_config()))
    return {ancora: [{"titulo": n.get("titulo", ""), "url": n.get("url", ""), "resumo": n.get("resumo", "")} for n in noticias]
            for ancora, noticias in por_ancora.items()}


# ---------------------------------------------------------------------------


def autoteste():
    """Os quatro modelos montados sobre atos e PDF sinteticos, sem rede."""
    import tempfile
    from pypdf import PdfWriter

    escritor = PdfWriter()
    for _ in range(3):
        escritor.add_blank_page(width=200, height=200)
    memoria = io.BytesIO()
    escritor.write(memoria)
    pdf = memoria.getvalue()
    data = datetime.date(2026, 9, 29)
    atos = [{
        "identificacao": "RESOLUÇÃO DE TESTE Nº 1", "ementa": "Ementa sintética do ato de teste.",
        "texto": "RESOLUÇÃO DE TESTE Nº 1 Ementa sintética do ato de teste. Art. 1º Texto sintético do artigo primeiro.",
        "orgao": "Ministério de Minas e Energia/Agência Nacional do Petróleo", "tipo": "Resolução", "pagina": 2,
        "edicao": "1", "url_ato": "https://exemplo.invalido/ato-1", "url_pdf_pagina": url_pagina_oficial(data, 2),
    }]
    assert escolher_atos(atos + [dict(atos[0], orgao="Ministério da Saúde")]) == atos
    with tempfile.TemporaryDirectory() as pasta:
        resumo = gerar(atos, pdf, data, destino=Path(pasta))
        a = (Path(pasta) / "modelo_A.eml").read_bytes().decode("utf-8", "replace")
        assert "PDF oficial (p=C3=A1gina 2)" in a or "PDF oficial (página 2)" in a, "o link do modelo A nao entrou"
        assert resumo["modelos"]["B"]["anexos"] == ["DOU_Secao1_2026-09-29_pagina_2.pdf"]
        assert resumo["modelos"]["C"]["anexos"] == ["DOU_Secao1_2026-09-29_completo.pdf"]
        d = (Path(pasta) / "modelo_D.eml").read_bytes().decode("utf-8", "replace")
        assert "artigo primeiro" in d or "artigo=20primeiro" in d, "o trecho do modelo D nao entrou"
    print("autoteste: ok")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default="")
    parser.add_argument("--origem", choices=("inlabs", "direto"), default="inlabs")
    parser.add_argument("--autoteste", action="store_true")
    args = parser.parse_args()
    if args.autoteste:
        autoteste()
        return
    if re.fullmatch(r"\d{2}-\d{2}-\d{4}", args.data):
        args.data = "-".join(reversed(args.data.split("-")))  # DD-MM-AAAA, como o workflow pede
    data = datetime.date.fromisoformat(args.data) if args.data else datetime.date.today() - datetime.timedelta(days=1)
    if args.origem == "inlabs":
        email, senha = os.getenv("INLABS_EMAIL"), os.getenv("INLABS_SENHA")
        if not email or not senha:
            raise SystemExit("INLABS_EMAIL e INLABS_SENHA não estão configurados: a demonstração precisa de uma conta "
                             "gratuita no INLABS (https://inlabs.in.gov.br) para baixar o DOU sem Firecrawl.")
        atos, pdf = baixar_inlabs(data, email, senha)
    else:
        atos, pdf = baixar_direto(data)
    escolhidos = escolher_atos(atos)
    if not escolhidos:
        raise SystemExit(f"Nenhum ato do setor de energia na Seção 1 de {data:%d/%m/%Y}; tente outra data.")
    print(f"{len(atos)} atos na Seção 1 de {data:%d/%m/%Y}; {len(escolhidos)} na amostra.")
    gerar(escolhidos, pdf, data, base_noticias=noticias_do_radar())


if __name__ == "__main__":
    main()
