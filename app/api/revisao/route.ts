import { NextResponse } from "next/server"

// Configuracao via env vars (setar no Vercel)
const GITHUB_TOKEN = process.env.GITHUB_TOKEN
const GITHUB_OWNER = process.env.GITHUB_OWNER || "EduardoBotticelli"
const GITHUB_REPO = process.env.GITHUB_REPO || "boletim-automacao"
const GITHUB_BRANCH = process.env.GITHUB_BRANCH || "main"
const DECISOES_PATH = "output/decisoes_alice.json"

interface DecisaoItem {
  id: string
  status: string
  boletins: string[]
  noticia?: unknown // Payload para itens manuais
}

interface RevisaoPayload {
  confirmadoEm: string
  itens: DecisaoItem[]
}

/**
 * Codifica string para base64 (Node.js runtime).
 * A API do GitHub exige conteudo em base64 para criar/atualizar arquivos.
 */
function toBase64(texto: string): string {
  return Buffer.from(texto, "utf-8").toString("base64")
}

/**
 * Busca o SHA atual do arquivo decisoes_alice.json (se existir).
 * Necessario para atualizar arquivo existente via API do GitHub.
 * Retorna null se o arquivo ainda nao existe.
 */
async function buscarSha(): Promise<string | null> {
  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${DECISOES_PATH}?ref=${GITHUB_BRANCH}`
  const resposta = await fetch(url, {
    headers: {
      Authorization: `Bearer ${GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    cache: "no-store",
  })

  if (resposta.status === 404) return null
  if (!resposta.ok) {
    const texto = await resposta.text()
    throw new Error(`Falha ao buscar SHA (${resposta.status}): ${texto}`)
  }

  const dados = (await resposta.json()) as { sha?: string }
  return dados.sha || null
}

/**
 * Cria ou atualiza o arquivo decisoes_alice.json no repo do backend.
 */
async function commitDecisoes(payload: RevisaoPayload): Promise<void> {
  const shaAtual = await buscarSha()

  const conteudoJson = JSON.stringify(payload, null, 2)
  const conteudoBase64 = toBase64(conteudoJson)

  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${DECISOES_PATH}`

  interface CommitBody {
    message: string
    content: string
    branch: string
    sha?: string
  }

  const body: CommitBody = {
    message: `chore: decisoes da revisao em ${payload.confirmadoEm}`,
    content: conteudoBase64,
    branch: GITHUB_BRANCH,
  }
  if (shaAtual) body.sha = shaAtual

  const resposta = await fetch(url, {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  })

  if (!resposta.ok) {
    const texto = await resposta.text()
    throw new Error(`Falha ao commitar decisoes (${resposta.status}): ${texto}`)
  }
}

/**
 * Dispara o workflow gerar_boletim_final.yml via repository_dispatch.
 */
async function dispararWorkflow(): Promise<void> {
  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/dispatches`
  const resposta = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      event_type: "confirmar-revisao",
      client_payload: {
        disparadoEm: new Date().toISOString(),
      },
    }),
  })

  // 204 No Content = sucesso
  if (resposta.status !== 204) {
    const texto = await resposta.text()
    throw new Error(`Falha ao disparar workflow (${resposta.status}): ${texto}`)
  }
}

export async function POST(request: Request) {
  // Verifica configuracao
  if (!GITHUB_TOKEN) {
    console.error("[api/revisao] GITHUB_TOKEN nao configurado no Vercel")
    return NextResponse.json(
      { erro: "Servidor nao configurado. Contate o administrador." },
      { status: 500 }
    )
  }

  // Le e valida o payload
  let payload: RevisaoPayload
  try {
    payload = (await request.json()) as RevisaoPayload
  } catch {
    return NextResponse.json({ erro: "Payload invalido (JSON malformado)" }, { status: 400 })
  }

  if (!payload || !Array.isArray(payload.itens)) {
    return NextResponse.json(
      { erro: "Payload invalido (campo 'itens' obrigatorio)" },
      { status: 400 }
    )
  }

  if (!payload.confirmadoEm) {
    payload.confirmadoEm = new Date().toISOString()
  }

  // 1. Commita decisoes no repo do backend
  try {
    await commitDecisoes(payload)
  } catch (erro) {
    console.error("[api/revisao] Erro ao commitar decisoes:", erro)
    return NextResponse.json(
      {
        erro: "Nao foi possivel salvar as decisoes.",
        detalhe: erro instanceof Error ? erro.message : String(erro),
      },
      { status: 502 }
    )
  }

  // 2. Dispara workflow
  try {
    await dispararWorkflow()
  } catch (erro) {
    console.error("[api/revisao] Erro ao disparar workflow:", erro)
    return NextResponse.json(
      {
        erro: "Decisoes salvas, mas nao foi possivel disparar a geracao dos boletins.",
        detalhe: erro instanceof Error ? erro.message : String(erro),
      },
      { status: 502 }
    )
  }

  return NextResponse.json({
    sucesso: true,
    mensagem: "Revisao confirmada. Boletins serao gerados em ate 2 minutos.",
    totalItens: payload.itens.length,
    confirmadoEm: payload.confirmadoEm,
  })
}
