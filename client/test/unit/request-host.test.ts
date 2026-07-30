import { describe, expect, it } from 'vitest'
import { resolveRequestHost } from '../../lib/request-host.js'

describe('resolveRequestHost', () => {
  it('prefers the CloudFront-overwritten viewer host', () => {
    expect(resolveRequestHost({
      'x-opnform-viewer-host': 'forms.example.test',
      'x-forwarded-host': 'function-url.lambda-url.us-east-1.on.aws',
      host: 'function-url.lambda-url.us-east-1.on.aws',
    })).toBe('forms.example.test')
  })

  it('uses the existing forwarded and host fallbacks', () => {
    expect(resolveRequestHost({ 'x-forwarded-host': 'proxy.example.test', host: 'origin.test' })).toBe('proxy.example.test')
    expect(resolveRequestHost({ host: ['origin.test'] })).toBe('origin.test')
  })
})
