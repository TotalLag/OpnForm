/**
 * CloudFront replaces this header at viewer request time. It carries the host
 * the visitor used while the Lambda origin receives its own Function URL host.
 */
export function resolveRequestHost(headers = {}, fallback = '') {
  const trustedHost = headers['x-opnform-viewer-host']
  const forwardedHost = headers['x-forwarded-host']
  const host = headers.host

  return headerValue(trustedHost) || headerValue(forwardedHost) || headerValue(host) || fallback
}

function headerValue(value) {
  return Array.isArray(value) ? value[0] : value || ''
}
