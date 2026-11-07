import { timingSafeEqual } from 'node:crypto'

const safeEqual = (a: string, b: string): boolean => {
  const aBuf = Buffer.from(a, 'utf8')
  const bBuf = Buffer.from(b, 'utf8')
  if (aBuf.length !== bBuf.length) return false
  return timingSafeEqual(aBuf, bBuf)
}

/**
 * Gates every proxied API call behind HTTP Basic auth. The page shell stays
 * public so container health checks keep working, but no data or mutation is
 * reachable without the UI credentials.
 */
export default defineEventHandler((event) => {
  const path = getRequestURL(event).pathname
  if (!path.startsWith('/api/')) return

  const config = useRuntimeConfig(event)
  const user = String(config.uiUser || '')
  const password = String(config.uiPassword || '')

  if (!user || !password) {
    throw createError({
      statusCode: 503,
      statusMessage: 'UI credentials are not configured',
    })
  }

  const header = getHeader(event, 'authorization') || ''
  if (!header.toLowerCase().startsWith('basic ')) {
    setHeader(event, 'www-authenticate', 'Basic realm="Harpia", charset="UTF-8"')
    throw createError({ statusCode: 401, statusMessage: 'Unauthorized' })
  }

  const decoded = Buffer.from(header.slice(6), 'base64').toString('utf8')
  const separator = decoded.indexOf(':')
  const providedUser = separator >= 0 ? decoded.slice(0, separator) : ''
  const providedPassword = separator >= 0 ? decoded.slice(separator + 1) : ''

  if (!safeEqual(providedUser, user) || !safeEqual(providedPassword, password)) {
    setHeader(event, 'www-authenticate', 'Basic realm="Harpia", charset="UTF-8"')
    throw createError({ statusCode: 401, statusMessage: 'Unauthorized' })
  }
})
