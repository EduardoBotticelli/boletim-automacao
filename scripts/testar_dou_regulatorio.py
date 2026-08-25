"""Prova isolada do DOU com critério regulatório restrito."""

import json
import os
import time
from pathlib import Path

from firecrawl import Firecrawl
from google import genai
from google.genai import types

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "output"
OUT.mkdir(exist_ok=True)

DATA = os.getenv("DOU_DATA", "24-08-2026")
URL = f"https://www.in.gov.br/leiturajornal?data={DATA}&secao=do1"
MODELOS = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
]


def resumir_erro(erro, limite=500):
    return " ".join(str(erro).split())[:limite]


def normalizar_resposta(dados):
    """Aceita lista direta ou objeto contendo a chave publicacoes."""
    if isinstance(dados, list):
        publicacoes = [item for item in dados if isinstance(item, dict)]
        observacoes = []
        formato = "lista"
    elif isinstance(dados, dict):
        valor_publicacoes = dados.get("publicacoes", [])
        publicacoes = (
            [item for item in valor_publicacoes if isinstance(item, dict)]
            if isinstance(valor_publicacoes, list)
            else []
        )

        valor_observacoes = dados.get("observacoes_tecnicas", [])
        if isinstance(valor_observacoes, list):
            observacoes = valor_observacoes
        elif valor_observacoes:
            observacoes = [str(valor_observacoes)]
        else:
            observacoes = []

        formato = "objeto"
    else:
        raise ValueError(
            "Resposta Gemini inesperada: "
            f"era esperado objeto ou lista, mas foi recebido {type(dados).__name__}."
        )

    return publicacoes, observacoes, formato


def gerar_com_cascata(cliente, prompt):
    tentativas = []

    for modelo in MODELOS:
        for tentativa in (1, 2):
            try:
                resposta = cliente.models.generate_content(
                    model=modelo,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        response_mime_type="application/json",
                    ),
                )

                dados = json.loads(resposta.text or "")
                publicacoes, observacoes, formato = normalizar_resposta(dados)

                tentativas.append(
                    {
                        "modelo": modelo,
                        "tentativa": tentativa,
                        "status": "sucesso",
                        "formato_resposta": formato,
                    }
                )

                return publicacoes, observacoes, formato, modelo, tentativas

            except Exception as erro:
                tentativas.append(
                    {
                        "modelo": modelo,
                        "tentativa": tentativa,
                        "status": "erro",
                        "erro": resumir_erro(erro),
                    }
                )

                if tentativa == 1:
                    time.sleep(10)

    return None, [], "", "", tentativas


def gerar_html(publicacoes):
    artigos = []

    for publicacao in publicacoes:
        artigos.append(
            f"""
            <article>
                <small>
                    {publicacao.get('orgao', '')}
                    ·
                    {publicacao.get('tipo_ato', '')}
                </small>
                <h2>{publicacao.get('titulo', '')}</h2>
                <p>{publicacao.get('resumo', '')}</p>
                <p>
                    <strong>Aderência:</strong>
                    {publicacao.get('justificativa_regulatorio', '')}
                </p>
            </article>
            """
        )

    documento = f"""<!doctype html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width">
    <title>DOU · Regulatório</title>
    <style>
        body {{
            margin: 0;
            background: #eef1ef;
            font-family: Arial, sans-serif;
            color: #1f2937;
        }}
        main {{
            max-width: 900px;
            margin: 24px auto;
        }}
        header {{
            background: #0d3320;
            color: white;
            padding: 28px;
        }}
        article {{
            background: white;
            padding: 20px;
            margin-top: 14px;
            border-left: 4px solid #1a4d2e;
        }}
        small {{
            color: #5f6f66;
        }}
    </style>
</head>
<body>
    <main>
        <header>
            <h1>DOU · Cluster Regulatório</h1>
            <p>{DATA} · {len(publicacoes)} publicações</p>
        </header>
        {''.join(artigos)}
    </main>
</body>
</html>
"""

    (OUT / "teste_dou_regulatorio.html").write_text(
        documento,
        encoding="utf-8",
    )


def main():
    firecrawl_api_key = os.getenv("FIRECRAWL_API_KEY")
    gemini_api_key = os.getenv("GEMINI_API_KEY")

    if not firecrawl_api_key or not gemini_api_key:
        raise SystemExit(
            "FIRECRAWL_API_KEY e GEMINI_API_KEY são obrigatórias."
        )

    firecrawl = Firecrawl(api_key=firecrawl_api_key)
    resultado = firecrawl.scrape(
        URL,
        formats=["markdown"],
        only_main_content=True,
    )
    texto = (resultado.markdown or "")[:60000]

    prompt = """
Retorne JSON no formato:
{
  "publicacoes": [],
  "observacoes_tecnicas": []
}

Cada publicação deve conter:
- titulo
- orgao
- tipo_ato
- data_publicacao
- resumo
- justificativa_regulatorio
- url_publicacao
- palavras_chave

Inclua somente atos com impacto jurídico externo concreto sobre setores
regulados, agentes econômicos, concessionárias, autorizadas, fiscalização,
sanções, consultas públicas, outorgas ou obrigações regulatórias.

Exclua atos de pessoal, organização interna, aplicação orçamentária, planos
governamentais genéricos, eventos, capacitação, prêmios e portarias locais
sem impacto setorial nacional.

Não invente dados.
""" + "\n" + texto

    cliente = genai.Client(api_key=gemini_api_key)

    try:
        publicacoes, observacoes, formato, modelo, tentativas = gerar_com_cascata(
            cliente,
            prompt,
        )
    finally:
        cliente.close()

    if publicacoes is None:
        raise SystemExit("Toda a cascata Gemini falhou no teste do DOU.")

    saida = {
        "publicacoes": publicacoes,
        "observacoes_tecnicas": observacoes,
        "data_dou": DATA,
        "secao": "Seção 1",
        "url_edicao": URL,
        "modelo_gemini_utilizado": modelo,
        "formato_resposta_gemini": formato,
        "tentativas_gemini": tentativas,
        "total_publicacoes_regulatorias": len(publicacoes),
    }

    (OUT / "teste_dou_regulatorio.json").write_text(
        json.dumps(saida, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    gerar_html(publicacoes)

    print(
        "Teste do DOU concluído: "
        f"{len(publicacoes)} publicações, modelo {modelo}, formato {formato}."
    )


if __name__ == "__main__":
    main()
