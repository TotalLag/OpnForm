import { defineEventHandler, proxyRequest } from 'nitropack'

export default defineEventHandler(async (event) => {
  const { public: { apiBase } } = useRuntimeConfig(event)

  if (!apiBase) {
    console.error('NUXT_PUBLIC_API_BASE is not defined')
    throw createError({
      statusCode: 500,
      statusMessage: 'Internal Server Error',
    })
  }

  return proxyRequest(event, apiBase, {})
})