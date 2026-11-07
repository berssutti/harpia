const ALLOWED_PATHS: RegExp[] = [
  /^system\/status$/,
  /^watchlist$/,
  /^watchlist\/bulk$/,
  /^watchlist\/\d+$/,
  /^groups$/,
  /^groups\/bulk$/,
  /^groups\/\d+$/,
  /^credentials$/,
  /^credentials\/[a-z0-9_-]{1,64}$/,
  /^telegram\/auth-code$/,
  /^telegram\/new-session$/,
  /^feed\/history$/,
  /^feed\/stream$/,
]

// FastAPI redirects collection paths without a trailing slash, and a 307 is not
// followed reliably for streamed request bodies. Hit the canonical path.
const COLLECTION_PATHS = new Set(['watchlist', 'groups', 'credentials'])

const ALLOWED_METHODS = new Set(['GET', 'POST', 'DELETE'])
const MAX_BODY_BYTES = 2 * 1024 * 1024

const isAllowed = (path: string): boolean =>
  ALLOWED_PATHS.some((pattern) => pattern.test(path))

/**
 * Same-origin proxy for the FastAPI backend. It injects the server-side API
 * key, so the secret is never shipped to the browser. Only the endpoints the
 * dashboard actually uses are forwarded; /internal/* is deliberately blocked.
 */
export default defineEventHandler(async (event) => {
  const path = (getRouterParam(event, 'path') || '')
    .replace(/^\/+/, '')
    .replace(/\/+$/, '')

  if (!path || path.includes('..') || path.includes('\\') || path.includes('//')) {
    throw createError({ statusCode: 404, statusMessage: 'Not Found' })
  }

  if (!isAllowed(path)) {
    throw createError({ statusCode: 404, statusMessage: 'Not Found' })
  }

  const method = event.method
  if (!ALLOWED_METHODS.has(method)) {
    throw createError({ statusCode: 405, statusMessage: 'Method Not Allowed' })
  }

  const config = useRuntimeConfig(event)
  const backendUrl = String(config.backendUrl || '').replace(/\/+$/, '')
  const apiKey = String(config.apiKey || '')

  if (!backendUrl || !apiKey) {
    throw createError({
      statusCode: 503,
      statusMessage: 'Backend proxy is not configured',
    })
  }

  const query = getRequestURL(event).search
  const targetPath = COLLECTION_PATHS.has(path) ? `${path}/` : path
  const target = `${backendUrl}/${targetPath}${query}`

  const headers: Record<string, string> = { 'x-api-key': apiKey }

  const contentType = getHeader(event, 'content-type')
  if (contentType) headers['content-type'] = contentType

  const accept = getHeader(event, 'accept')
  if (accept) headers['accept'] = accept

  const declaredLength = Number(getHeader(event, 'content-length') || 0)
  if (declaredLength > MAX_BODY_BYTES) {
    throw createError({ statusCode: 413, statusMessage: 'Payload Too Large' })
  }

  const body = method === 'GET' ? undefined : await readRawBody(event, false)

  if (body && body.length > MAX_BODY_BYTES) {
    throw createError({ statusCode: 413, statusMessage: 'Payload Too Large' })
  }

  let response
  try {
    response = await $fetch.raw(target, {
      method: method as 'GET' | 'POST' | 'DELETE',
      headers,
      body: body ?? undefined,
      responseType: 'stream',
      ignoreResponseError: true,
      retry: 0,
    })
  } catch (error) {
    console.error('[api-proxy] upstream request failed', {
      path,
      method,
      reason: error instanceof Error ? error.message : String(error),
    })
    throw createError({ statusCode: 502, statusMessage: 'Backend unavailable' })
  }

  setResponseStatus(event, response.status)

  const upstreamType = response.headers.get('content-type')
  if (upstreamType) setHeader(event, 'content-type', upstreamType)

  if (path === 'feed/stream') {
    setHeader(event, 'cache-control', 'no-cache, no-transform')
    setHeader(event, 'x-accel-buffering', 'no')
    setHeader(event, 'connection', 'keep-alive')
    // Flush the SSE headers immediately instead of waiting for the first
    // event (the backend only pings after ~15s).
    event.node.res.flushHeaders?.()
  }

  return sendStream(event, response._data as ReadableStream)
})
