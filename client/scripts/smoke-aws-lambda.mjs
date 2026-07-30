import { access, mkdir, rm } from 'node:fs/promises'
import { execFile } from 'node:child_process'
import { resolve } from 'node:path'
import { promisify } from 'node:util'
import { pathToFileURL } from 'node:url'

const execFileAsync = promisify(execFile)
const root = process.cwd()
const archive = resolve(root, '.aws-shadow/lambda.zip')
const scratch = resolve(root, '.aws-shadow/smoke')

await access(archive)
await rm(scratch, { recursive: true, force: true })
await mkdir(scratch, { recursive: true })
await execFileAsync('unzip', ['-q', archive, '-d', scratch])
console.log('smoke_phase=archive_extracted')

const entry = resolve(scratch, 'index.mjs')
await access(entry)
const runtime = await import(pathToFileURL(entry).href)
console.log('smoke_phase=handler_imported')
if (typeof runtime.handler !== 'function') {
  throw new Error('Packaged Nitro Lambda must export handler from index.mjs')
}

const response = await runtime.handler({
  version: '2.0',
  routeKey: '$default',
  rawPath: '/__opnform_shadow_smoke__',
  rawQueryString: '',
  headers: { host: 'shadow.invalid', 'x-forwarded-proto': 'https' },
  requestContext: {
    accountId: 'shadow',
    apiId: 'shadow',
    domainName: 'shadow.invalid',
    domainPrefix: 'shadow',
    http: { method: 'GET', path: '/__opnform_shadow_smoke__', protocol: 'HTTP/1.1', sourceIp: '127.0.0.1', userAgent: 'smoke' },
    requestId: 'shadow',
    routeKey: '$default',
    stage: '$default',
    time: '01/Jan/2026:00:00:00 +0000',
    timeEpoch: 0,
  },
  isBase64Encoded: false,
})
if (!response || typeof response.statusCode !== 'number') {
  throw new Error('Packaged Nitro Lambda handler did not return an HTTP response')
}
if (response.statusCode >= 500) {
  throw new Error(`Packaged Nitro Lambda handler returned ${response.statusCode}`)
}
console.log('smoke_phase=handler_responded')
console.log(JSON.stringify({ handler: 'index.handler', statusCode: response.statusCode }))
