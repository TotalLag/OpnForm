import { defineEventHandler, getRouterParam, setResponseStatus, getRequestHeader } from 'h3'
import { useRuntimeConfig } from '#imports'

/**
 * Transparent asset proxy (no redirect)
 * - Frontend endpoint: /forms/assets/:file
 * - Calls backend to obtain a short‑lived signed URL, then streams bytes from storage to the client.
 * - The browser never sees the storage URL or its query signature.
 */
export default defineEventHandler(async (event) => {
  const file = getRouterParam(event, 'file')
  if (!file) {
    setResponseStatus(event, 400)
    return 'Missing asset filename'
  }

  const { privateApiBase } = useRuntimeConfig()
  const backendBase =
    (privateApiBase as string | undefined) ||
    (process.env.NUXT_PRIVATE_API_BASE as string | undefined) ||
    ''

  if (!backendBase) {
    setResponseStatus(event, 500)
    return 'NUXT_PRIVATE_API_BASE not configured'
  }

  // Step 1: Ask backend for redirect target (but don't follow it here)
  const backendUrl = `${backendBase.replace(/\/+$/, '')}/forms/assets/${encodeURIComponent(file)}`
  let presignRes: Response
  try {
    presignRes = await fetch(backendUrl, {
      redirect: 'manual',
      headers: { accept: 'application/json, text/plain, */*' },
    })
  } catch (e: any) {
    setResponseStatus(event, 502)
    return `Failed to reach backend: ${e?.message || 'unknown error'}`
  }

  if (presignRes.status < 300 || presignRes.status >= 400) {
    // Backend returned an error or non-redirect
    const ct = presignRes.headers.get('content-type') || 'text/plain; charset=utf-8'
    const text = await presignRes.text().catch(() => '')
    return new Response(
      text && text.length < 2000 ? text : `Upstream responded with status ${presignRes.status}`,
      { status: presignRes.status, headers: { 'Content-Type': ct } },
    )
  }

  const location = presignRes.headers.get('location')
  if (!location) {
    setResponseStatus(event, 502)
    return 'Backend did not provide Location for redirect'
  }

  // Step 2: Fetch the asset using the signed URL, forwarding only safe conditional/range headers
  const fwd: Record<string, string> = {}
  const copy = (name: string) => {
    const v = getRequestHeader(event, name)
    if (v) fwd[name] = v
  }
  copy('range')
  copy('if-none-match')
  copy('if-modified-since')
  copy('accept')

  let assetRes: Response
  try {
    assetRes = await fetch(location, { method: 'GET', headers: fwd, redirect: 'manual' })
  } catch (e: any) {
    setResponseStatus(event, 502)
    return `Failed to fetch asset: ${e?.message || 'unknown error'}`
  }

  // Build a safe header set to expose to the client (no Location leaks)
  const allowed = [
    'content-type',
    'content-length',
    'content-range',
    'accept-ranges',
    'etag',
    'last-modified',
    'cache-control',
    'content-disposition',
  ]
  const out = new Headers()
  for (const h of allowed) {
    const v = assetRes.headers.get(h)
    if (v) {
      // normalize common header casing
      const nice = h
        .split('-')
        .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
        .join('-')
      out.set(nice, v)
    }
  }
  // Provide a short caching policy if upstream doesn't specify one
  if (!out.has('Cache-Control')) {
    out.set('Cache-Control', 'public, max-age=60, s-maxage=300')
  }

  // Stream the body directly to the client so the signed URL is never exposed
  return new Response(assetRes.body, {
    status: assetRes.status, // 200/206/304 as provided by storage
    headers: out,
  })
})