import { contentApi } from '~/api/content'

function isPlainObject(value) {
  if (value === null || typeof value !== 'object') {
    return false
  }

  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}

export default defineNuxtPlugin(async (nuxtApp) => {
  // Load feature flags during SSR using cached server route
  const featureFlagsState = useState('featureFlags', () => ({}))
  
  try {
    const flags = await $fetch('/api/feature-flags')
    featureFlagsState.value = isPlainObject(flags) ? flags : {}
  } catch (error) {
    console.error('Failed to load feature flags on server:', error)
    featureFlagsState.value = {}
  }

  // Provide simple refresh capability
  nuxtApp.provide('refreshFeatureFlags', async () => {
    try {
      // Force fresh fetch by adding cache-busting timestamp
      const flags = await contentApi.featureFlags.list({
        query: { t: Date.now() }
      })
      featureFlagsState.value = flags
      return flags
    } catch (error) {
      console.error('Failed to refresh feature flags:', error)
      throw error
    }
  })
}) 