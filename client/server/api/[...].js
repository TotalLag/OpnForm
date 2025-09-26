export default defineEventHandler(async (event) => {
  const { privateApiBase } = useRuntimeConfig(event)

  if (!privateApiBase) {
    console.error('NUXT_PRIVATE_API_BASE is not defined')
    throw createError({
      statusCode: 500,
      statusMessage: 'Proxy not configured.',
    })
  }

  // Construct the target URL
  const path = event.path.replace(/^\/api/, '')
  const target = new URL(path, privateApiBase)

  const method = getMethod(event)
  const headers = getRequestHeaders(event)
  const body = ['POST', 'PUT', 'PATCH'].includes(method)
    ? await readRawBody(event)
    : undefined

  // Remove the host header, as it can cause issues with routing
  delete headers.host

  try {
    const response = await $fetch.raw(target.toString(), {
      method,
      headers,
      body,
      ignoreResponseError: true, // We'll handle the response status and body ourselves
    })

    // Forward all headers from the response
    for (const [key, value] of response.headers.entries()) {
      // Some headers like 'content-encoding' and 'content-length' are handled by the server
      // and should not be manually set.
      if (key.toLowerCase() !== 'content-encoding' && key.toLowerCase() !== 'content-length') {
        setHeader(event, key, value)
      }
    }

    setResponseStatus(event, response.status, response.statusText)

    return response._data
  } catch (error) {
    console.error('Error proxying request:', error)
    throw createError({
      statusCode: 502,
      statusMessage: 'Bad Gateway',
    })
  }
})