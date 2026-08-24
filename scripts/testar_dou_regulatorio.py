"""
Prova de conceito: extração de publicações específicas do DOU para o cluster Regulatório.

Objetivo:
- acessar a edição da Seção 1 do DOU de uma data informada;
- extrair o conteúdo em texto por meio do Firecrawl;
- pedir ao Gemini que identifique somente atos aderentes ao cluster Regulatório;
- devolver atos individualizados em JSON e HTML, nunca o PDF inteiro.

Uso no repositório:
    python scripts/testar_dou_regulatorio.py

Variáveis opcionais:
    DOU_DATA=24-08-2026
    DOU_SECAO=do1
    DOU_URL=https://www.in.gov.br/leiturajornal?data=24-08-2026&secao=do1

Saídas:
    output/teste_dou_regulatorio.json
    output/teste_dou_regulatorio.html
"""

import datetime
import html
import json
import os
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from firecrawl import Firecrawl
from google import genai
from google.genai import types


BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_JSON = OUTPUT_DIR / "teste_dou_regulatorio.json"
OUTPUT_HTML = OUTPUT_DIR / "teste_dou_regulatorio.html"

FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

CASCATA_MODELOS = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
]

TENTATIVAS_POR_MODELO = 2
ESPERAS_GEMINI_SEGUNDOS = [10, 30]
MAX_TENTATIVAS_FIRECRAWL = 3
ESPERA_FIRECRAWL_SEGUNDOS = 65
MAX_CONTEUDO_CHARS = 120000

ORGAOS_PRIORITARIOS = [
    "ANATEL",
    "SUSEP",
    "ANTT",
    "CADE",
    "MDIC",
    "MME",
    "ANP",
    "ANEEL",
    "ANTAQ",
    "CNPE",
    "SENACON",
    "ANVISA",
    "ANM",
]

TIPOS_PRIORITARIOS = [
    "resolução",
    "portaria",
    "instrução normativa",
    "consulta pública",
    "despacho",
    "decisão",
    "deliberação",
    "edital regulatório",
    "autorização",
    "outorga",
    "fiscalização",
    "sanção",
]

EXCLUSOES_INICIAIS = [
    "nomeação",
    "exoneração",
    "férias",
    "afastamento",
    "agenda institucional",
    "extrato administrativo rotineiro",
    "ato interno sem impacto externo",
]


def exigir_secrets():
    if not FIRECRAWL_API_KEY:
        raise SystemExit("ERRO: FIRECRAWL_API_KEY não encontrada.")
    if not GEMINI_API_KEY:
        raise SystemExit("ERRO: GEMINI_API_KEY não encontrada.")


def data_dou():
    valor = os.environ.get("DOU_DATA", "").strip()
    if valor:
        try:
            datetime.datetime.strptime(valor, "%d-%m-%Y")
        except ValueError as erro:
            raise SystemExit("ERRO: DOU_DATA deve usar o formato DD-MM-AAAA.") from erro
        return valor
    hoje = datetime.datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    return hoje.strftime("%d-%m-%Y")


def montar_url(data, secao):
    url_manual = os.environ.get("DOU_URL", "").strip()
    if url_manual:
        return url_manual
    return f"https://www.in.gov.br/leiturajornal?data={data}&secao={secao}"


def erro_recuperavel(erro):
    texto = str(erro).lower()
    marcadores = [
        "429", "500", "502", "503", "504", "rate limit", "unavailable",
        "high demand", "resource_exhausted", "deadline_exceeded", "timeout",
        "temporarily", "not found", "not_found", "model not found",
        "not supported", "permission denied for model",
    ]
    return any(marcador in texto for marcador in marcadores)


def resumir_erro(erro, limite=600):
    return " ".join(str(erro).split())[:limite]


def coletar_dou(url):
    cliente = Firecrawl(api_key=FIRECRAWL_API_KEY)
    ultimo_erro = None
    for tentativa in range(1, MAX_TENTATIVAS_FIRECRAWL + 1):
        try:
            resultado = cliente.scrape(
                url,
                formats=["markdown"],
                only_main_content=True,
            )
            conteudo = (resultado.markdown or "").strip()
            if not conteudo:
                raise RuntimeError("Firecrawl devolveu conteúdo vazio para a edição do DOU.")
            return conteudo[:MAX_CONTEUDO_CHARS]
        except Exception as erro:
            ultimo_erro = erro
            if not erro_recuperavel(erro) or tentativa == MAX_TENTATIVAS_FIRECRAWL:
                raise
            print(
                f"Firecrawl indisponível. Tentativa {tentativa + 1}/"
                f"{MAX_TENTATIVAS_FIRECRAWL} após espera."
            )
            time.sleep(ESPERA_FIRECRAWL_SEGUNDOS)
    raise ultimo_erro


def montar_prompt(data, secao, url, conteudo):
    return f"""
Você é responsável por uma prova de conceito de clipping jurídico do Diário Oficial da União.

OBJETIVO
Analise o conteúdo coletado da edição abaixo e extraia SOMENTE publicações específicas com aderência material ao cluster Regulatório. O resultado será exibido como texto em uma seção do Radar Regulatório. Não resuma a edição inteira e não reproduza o PDF inteiro.

EDIÇÃO
- Data: {data}
- Seção técnica: {secao}
- URL da edição: {url}

ESCOPO DO CLUSTER REGULATÓRIO
Priorize atos de agências reguladoras, ministérios e autoridades públicas que criem, alterem, interpretem, fiscalizem ou apliquem regras com impacto externo em setores regulados.

ÓRGÃOS PRIORITÁRIOS, SEM EXCLUSIVIDADE
{json.dumps(ORGAOS_PRIORITARIOS, ensure_ascii=False)}

TIPOS DE ATO PRIORITÁRIOS, SEM EXCLUSIVIDADE
{json.dumps(TIPOS_PRIORITARIOS, ensure_ascii=False)}

EXCLUSÕES INICIAIS
{json.dumps(EXCLUSOES_INICIAIS, ensure_ascii=False)}

REGRAS
1. Avalie cada publicação individualmente.
2. Não aceite um item apenas porque o nome de um órgão prioritário aparece no texto.
3. Exija consequência regulatória concreta ou potencial para agentes externos, empresas, usuários, concessionárias, autorizadas ou mercados regulados.
4. Exclua atos meramente internos, atos de pessoal e comunicações sem conteúdo regulatório.
5. Preserve o título oficial quando identificável.
6. Preserve o link individual da publicação quando o link estiver presente no conteúdo coletado.
7. Se houver apenas o link da edição e nenhum link individual identificável, use string vazia em url_publicacao.
8. Não invente número, órgão, data, tipo, resumo ou URL.
9. O resumo deve explicar objetivamente o que o ato faz, em até 500 caracteres.
10. A justificativa deve explicar por que o ato pertence ao cluster Regulatório, em até 300 caracteres.
11. Se não houver atos aderentes, devolva a lista publicacoes vazia.
12. Retorne somente JSON válido.

FORMATO OBRIGATÓRIO
{{
  "data_dou": "DD-MM-AAAA",
  "secao": "Seção 1",
  "publicacoes": [
    {{
      "titulo": "título oficial",
      "orgao": "órgão responsável",
      "tipo_ato": "tipo do ato",
      "data_publicacao": "AAAA-MM-DD ou string vazia",
      "resumo": "informação específica extraída em texto",
      "justificativa_regulatorio": "por que entra no cluster Regulatório",
      "palavras_chave": ["termo 1", "termo 2"],
      "url_publicacao": "link individual oficial ou string vazia"
    }}
  ],
  "observacoes_tecnicas": ["limitações objetivas encontradas na coleta"]
}}

CONTEÚDO COLETADO DA EDIÇÃO
{conteudo}
""".strip()


def validar_resposta(texto):
    dados = json.loads(texto)
    if not isinstance(dados, dict):
        raise ValueError("A resposta do Gemini não é um objeto JSON.")
    publicacoes = dados.get("publicacoes")
    if not isinstance(publicacoes, list):
        raise ValueError("A resposta do Gemini não contém uma lista 'publicacoes'.")

    campos_texto = [
        "titulo", "orgao", "tipo_ato", "data_publicacao", "resumo",
        "justificativa_regulatorio", "url_publicacao",
    ]
    publicacoes_validas = []
    for item in publicacoes:
        if not isinstance(item, dict):
            continue
        normalizado = {}
        for campo in campos_texto:
            normalizado[campo] = str(item.get(campo, "")).strip()
        palavras = item.get("palavras_chave", [])
        normalizado["palavras_chave"] = [
            str(palavra).strip()
            for palavra in palavras
            if isinstance(palavra, str) and palavra.strip()
        ] if isinstance(palavras, list) else []
        if normalizado["titulo"] and normalizado["resumo"]:
            publicacoes_validas.append(normalizado)

    dados["publicacoes"] = publicacoes_validas
    observacoes = dados.get("observacoes_tecnicas", [])
    dados["observacoes_tecnicas"] = [
        str(item).strip()
        for item in observacoes
        if isinstance(item, str) and item.strip()
    ] if isinstance(observacoes, list) else []
    return dados


def gerar_com_cascata(prompt):
    cliente = genai.Client(api_key=GEMINI_API_KEY)
    tentativas = []
    try:
        for modelo in CASCATA_MODELOS:
            for tentativa in range(1, TENTATIVAS_POR_MODELO + 1):
                print(f"Gemini {modelo}: tentativa {tentativa}/{TENTATIVAS_POR_MODELO}")
                try:
                    resposta = cliente.models.generate_content(
                        model=modelo,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            temperature=0.1,
                            response_mime_type="application/json",
                        ),
                    )
                    texto = resposta.text or ""
                    dados = validar_resposta(texto)
                    tentativas.append({
                        "modelo": modelo,
                        "tentativa": tentativa,
                        "status": "sucesso",
                    })
                    return dados, modelo, tentativas
                except Exception as erro:
                    recuperavel = erro_recuperavel(erro) or isinstance(
                        erro, (json.JSONDecodeError, ValueError)
                    )
                    tentativas.append({
                        "modelo": modelo,
                        "tentativa": tentativa,
                        "status": "erro",
                        "recuperavel": recuperavel,
                        "erro": resumir_erro(erro),
                    })
                    print("  Erro: " + resumir_erro(erro))
                    if not recuperavel:
                        return None, "", tentativas
                if tentativa < TENTATIVAS_POR_MODELO:
                    espera = ESPERAS_GEMINI_SEGUNDOS[
                        min(tentativa - 1, len(ESPERAS_GEMINI_SEGUNDOS) - 1)
                    ]
                    time.sleep(espera)
        return None, "", tentativas
    finally:
        cliente.close()


def salvar_json_atomico(caminho, dados):
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    with temporario.open("w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, indent=2)
        arquivo.flush()
        os.fsync(arquivo.fileno())
    os.replace(temporario, caminho)


def escapar(valor):
    return html.escape(str(valor or ""), quote=True)


def renderizar_html(resultado):
    publicacoes = resultado.get("publicacoes", [])
    if publicacoes:
        cards = []
        for item in publicacoes:
            palavras = ", ".join(escapar(p) for p in item["palavras_chave"])
            link = ""
            if item["url_publicacao"]:
                link = (
                    f'<a class="link" href="{escapar(item["url_publicacao"])}">'
                    "Abrir publicação oficial</a>"
                )
            cards.append(f"""
            <article class="ato">
              <div class="meta">{escapar(item['orgao'])} · {escapar(item['tipo_ato'])} · {escapar(item['data_publicacao'])}</div>
              <h2>{escapar(item['titulo'])}</h2>
              <p>{escapar(item['resumo'])}</p>
              <div class="justificativa"><strong>Aderência ao cluster Regulatório:</strong> {escapar(item['justificativa_regulatorio'])}</div>
              <div class="palavras"><strong>Palavras-chave:</strong> {palavras or 'Não informadas'}</div>
              {link}
            </article>
            """)
        corpo = "".join(cards)
    else:
        corpo = '<div class="vazio">Nenhuma publicação aderente ao cluster Regulatório foi identificada.</div>'

    observacoes = resultado.get("observacoes_tecnicas", [])
    observacoes_html = ""
    if observacoes:
        itens = "".join(f"<li>{escapar(item)}</li>" for item in observacoes)
        observacoes_html = f"<section class='observacoes'><h2>Observações técnicas</h2><ul>{itens}</ul></section>"

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Teste DOU · Cluster Regulatório</title>
  <style>
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:#f0f2f1; color:#1f2937; font-family:Arial,Helvetica,sans-serif; }}
    main {{ width:min(940px,calc(100% - 28px)); margin:24px auto 48px; }}
    header {{ background:#0d3320; color:#fff; padding:32px; border-radius:12px; }}
    header small {{ color:#a8d8b9; text-transform:uppercase; font-weight:700; letter-spacing:1.6px; }}
    header h1 {{ margin:10px 0 8px; font-size:30px; }}
    header p {{ margin:0; color:#a8d8b9; line-height:1.6; }}
    .ato, .observacoes, .vazio {{ background:#fff; border:1px solid #e5e7eb; border-radius:10px; margin-top:16px; padding:22px; }}
    .meta {{ color:#1a4d2e; font-size:11px; font-weight:700; text-transform:uppercase; }}
    h2 {{ color:#0d3320; font-size:18px; line-height:1.35; }}
    p {{ line-height:1.65; font-size:13px; }}
    .justificativa, .palavras {{ margin-top:12px; color:#6b7280; font-size:12px; line-height:1.55; }}
    .link {{ display:inline-block; margin-top:16px; color:#0d3320; font-size:12px; font-weight:700; text-decoration:none; border-bottom:2px solid #22c55e; padding-bottom:3px; }}
    .vazio {{ text-align:center; color:#6b7280; }}
  </style>
</head>
<body>
  <main>
    <header>
      <small>Prova de conceito</small>
      <h1>DOU · Cluster Regulatório</h1>
      <p>Edição de {escapar(resultado.get('data_dou'))} · {escapar(resultado.get('secao'))} · somente publicações específicas convertidas em texto</p>
    </header>
    {corpo}
    {observacoes_html}
  </main>
</body>
</html>
"""


def main():
    exigir_secrets()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    data = data_dou()
    secao = os.environ.get("DOU_SECAO", "do1").strip() or "do1"
    url = montar_url(data, secao)

    print("Teste DOU Regulatório")
    print("Data: " + data)
    print("Seção: " + secao)
    print("URL: " + url)

    conteudo = coletar_dou(url)
    print(f"Conteúdo coletado: {len(conteudo)} caracteres")

    prompt = montar_prompt(data, secao, url, conteudo)
    dados, modelo, tentativas = gerar_com_cascata(prompt)
    if dados is None:
        falha = {
            "status": "falha",
            "data_dou": data,
            "secao": secao,
            "url_edicao": url,
            "tentativas_gemini": tentativas,
        }
        salvar_json_atomico(OUTPUT_JSON, falha)
        raise SystemExit("ERRO: todos os modelos Gemini falharam no teste do DOU.")

    dados["data_dou"] = data
    dados["secao"] = "Seção 1" if secao == "do1" else secao
    dados["url_edicao"] = url
    dados["modelo_gemini_utilizado"] = modelo
    dados["tentativas_gemini"] = tentativas
    dados["total_publicacoes_regulatorias"] = len(dados["publicacoes"])

    salvar_json_atomico(OUTPUT_JSON, dados)
    html_resultado = renderizar_html(dados)
    temporario_html = OUTPUT_HTML.with_suffix(".html.tmp")
    temporario_html.write_text(html_resultado, encoding="utf-8")
    os.replace(temporario_html, OUTPUT_HTML)

    print("Publicações regulatórias identificadas: " + str(len(dados["publicacoes"])))
    print("JSON: " + str(OUTPUT_JSON))
    print("HTML: " + str(OUTPUT_HTML))


if __name__ == "__main__":
    main()
