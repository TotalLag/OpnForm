import { beforeEach, describe, expect, it, vi } from 'vitest'

const { featureFlagsList, plansList } = vi.hoisted(() => ({
  featureFlagsList: vi.fn(),
  plansList: vi.fn(),
}))

vi.mock('~/api/content', () => ({
  contentApi: {
    featureFlags: { list: featureFlagsList },
    plans: { list: plansList },
  },
}))

function setupPluginState() {
  const state = { value: undefined }

  globalThis.defineNuxtPlugin = (plugin) => plugin
  globalThis.useState = vi.fn((key, initialValue) => {
    if (state.value === undefined) {
      state.value = initialValue()
    }
    return state
  })

  return state
}

async function loadPlanCatalogPlugin(routeName, isAuthenticated) {
  const state = setupPluginState()
  globalThis.useRoute = () => ({ name: routeName })
  globalThis.useIsAuthenticated = () => ({
    isAuthenticated: { value: isAuthenticated },
  })

  const { default: plugin } = await import('../../plugins/plan-catalog.server.js')
  return { plugin, state }
}

async function loadFeatureFlagsPlugin() {
  const state = setupPluginState()
  const { default: plugin } = await import('../../plugins/feature-flags.server.js')
  return { plugin, state }
}

describe('SSR bootstrap plugins', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.clearAllMocks()
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('skips plan loading for anonymous public forms and installs refreshPlanCatalog', async () => {
    const { plugin, state } = await loadPlanCatalogPlugin('forms-slug', false)
    const nuxtApp = { provide: vi.fn() }

    await plugin(nuxtApp)

    expect(plansList).not.toHaveBeenCalled()
    expect(state.value).toEqual({ tiers: {} })
    expect(nuxtApp.provide).toHaveBeenCalledWith('refreshPlanCatalog', expect.any(Function))
  })

  it('loads plans for authenticated public forms', async () => {
    plansList.mockResolvedValue({ tiers: { pro: {} } })
    const { plugin } = await loadPlanCatalogPlugin('forms-slug', true)

    await plugin({ provide: vi.fn() })

    expect(plansList).toHaveBeenCalledWith({ server: true })
  })

  it('loads plans for anonymous non-public routes', async () => {
    plansList.mockResolvedValue({ tiers: { pro: {} } })
    const { plugin } = await loadPlanCatalogPlugin('dashboard', false)

    await plugin({ provide: vi.fn() })

    expect(plansList).toHaveBeenCalledWith({ server: true })
  })

  it('loads valid feature flags from the cached Nitro endpoint', async () => {
    const flags = { payments: true }
    globalThis.$fetch = vi.fn().mockResolvedValue(flags)
    const { plugin, state } = await loadFeatureFlagsPlugin()

    await plugin({ provide: vi.fn() })

    expect(globalThis.$fetch).toHaveBeenCalledWith('/api/feature-flags')
    expect(featureFlagsList).not.toHaveBeenCalled()
    expect(state.value).toEqual(flags)
  })

  it.each([null, []])('falls back to empty feature flags for invalid response %j', async (response) => {
    globalThis.$fetch = vi.fn().mockResolvedValue(response)
    const { plugin, state } = await loadFeatureFlagsPlugin()

    await plugin({ provide: vi.fn() })

    expect(state.value).toEqual({})
  })

  it('falls back to empty feature flags when the cached endpoint rejects', async () => {
    globalThis.$fetch = vi.fn().mockRejectedValue(new Error('Failed'))
    const { plugin, state } = await loadFeatureFlagsPlugin()

    await plugin({ provide: vi.fn() })

    expect(state.value).toEqual({})
  })
})
