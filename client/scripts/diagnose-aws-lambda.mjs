import { createHash } from 'node:crypto'
import { access, mkdir, realpath, rm } from 'node:fs/promises'
import { execFile } from 'node:child_process'
import { basename, dirname, isAbsolute, relative, resolve } from 'node:path'
import { performance } from 'node:perf_hooks'
import { promisify } from 'node:util'
import { fileURLToPath, pathToFileURL } from 'node:url'

const execFileAsync = promisify(execFile)
const candidates = new Set(['baseline-unknown', 'representative-root'])
const clientRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const worktreeRoot = resolve(clientRoot, '..')
const archive = resolve(clientRoot, '.aws-shadow/lambda.zip')
const usage = 'Usage: PAPERCLIP_RUN_SCRATCH_DIR=/run-owned/scratch node scripts/diagnose-aws-lambda.mjs <baseline-unknown|representative-root> | node scripts/diagnose-aws-lambda.mjs <baseline-unknown|representative-root> --output-dir /run-owned/scratch/<candidate>'

const frozenUnknownEvent = {
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
}

let phase = 'setup'

class UsageError extends Error {}

main().catch((error) => {
  writeLine(JSON.stringify({
    error: {
      class: errorName(error),
      message: errorMessage(error, phase),
    },
  }))
  process.exitCode = 1
})

async function main() {
  const { candidate, outputDirectory } = await parseInvocation(process.argv.slice(2))
  const event = createEvent(candidate)
  const eventSha256 = createHash('sha256').update(stableSerialize(event), 'utf8').digest('hex')
  writeLine(JSON.stringify({ candidate, eventSha256 }))
  const totalStartedAt = performance.now()

  await access(archive)

  phase = 'extraction'
  marker('before_extraction')
  await rm(outputDirectory, { recursive: true, force: true })
  await mkdir(outputDirectory, { recursive: true })
  await execFileAsync('unzip', ['-q', archive, '-d', outputDirectory])
  marker('after_extraction')

  const entry = resolve(outputDirectory, 'index.mjs')
  await access(entry)

  phase = 'import'
  marker('before_import')
  const importStartedAt = performance.now()
  const runtime = await import(pathToFileURL(entry).href)
  const importMs = elapsedMs(importStartedAt)
  marker('after_import')

  if (typeof runtime.handler !== 'function') {
    throw new Error('Packaged Nitro Lambda must export handler from index.mjs')
  }

  phase = 'handler invocation'
  marker('before_handler_invocation')
  const handlerStartedAt = performance.now()
  const response = await runtime.handler(event)
  const handlerMs = elapsedMs(handlerStartedAt)
  marker('after_response_completion')

  validateResponse(response)

  writeLine(JSON.stringify({
    candidate,
    eventSha256,
    wallTimeMs: {
      import: importMs,
      handler: handlerMs,
      total: elapsedMs(totalStartedAt),
    },
    statusCode: response.statusCode,
    responseShape: summarizeResponse(response),
    process: {
      pid: process.pid,
      node: process.version,
      architecture: process.arch,
    },
  }))
}

async function parseInvocation(args) {
  const [candidate, ...options] = args
  if (!candidates.has(candidate)) {
    throw new UsageError(usage)
  }

  const hasScratchDirectory = Boolean(process.env.PAPERCLIP_RUN_SCRATCH_DIR)
  const hasOutputDirectory = options.length === 2 && options[0] === '--output-dir'
  if (options.length !== 0 && !hasOutputDirectory) {
    throw new UsageError(usage)
  }
  if (hasScratchDirectory && hasOutputDirectory) {
    throw new UsageError('Pass either PAPERCLIP_RUN_SCRATCH_DIR or --output-dir, not both. ' + usage)
  }
  if (!hasScratchDirectory && !hasOutputDirectory) {
    throw new UsageError(usage)
  }

  const protectedWorktree = await realpath(worktreeRoot)
  let outputDirectory
  if (hasOutputDirectory) {
    outputDirectory = await resolveExplicitOutputDirectory(options[1], candidate)
  } else {
    outputDirectory = await resolveScratchOutputDirectory(process.env.PAPERCLIP_RUN_SCRATCH_DIR, candidate)
  }

  if (isWithin(outputDirectory, protectedWorktree) || isWithin(outputDirectory, '/tmp')) {
    throw new UsageError('Output directory must be outside /tmp and the worktree. ' + usage)
  }

  return { candidate, outputDirectory }
}

async function resolveScratchOutputDirectory(scratchDirectory, candidate) {
  if (!isAbsolute(scratchDirectory)) {
    throw new UsageError('PAPERCLIP_RUN_SCRATCH_DIR must be an absolute, existing run-owned directory. ' + usage)
  }

  const resolvedScratchDirectory = await realpath(scratchDirectory)
  return resolve(resolvedScratchDirectory, candidate)
}

async function resolveExplicitOutputDirectory(outputDirectory, candidate) {
  if (!isAbsolute(outputDirectory) || basename(resolve(outputDirectory)) !== candidate) {
    throw new UsageError(`--output-dir must be an absolute run-owned directory ending in ${candidate}. ` + usage)
  }

  const resolvedParentDirectory = await realpath(dirname(resolve(outputDirectory)))
  return resolve(resolvedParentDirectory, basename(resolve(outputDirectory)))
}

function createEvent(candidate) {
  const event = JSON.parse(stableSerialize(frozenUnknownEvent))
  if (candidate === 'representative-root') {
    event.rawPath = '/'
    event.requestContext.http.path = '/'
    assertRootOnlyChangesPaths(event)
  }
  return event
}

function assertRootOnlyChangesPaths(rootEvent) {
  const differences = []
  collectDifferences(frozenUnknownEvent, rootEvent, '', differences)
  const expectedPaths = new Set(['rawPath', 'requestContext.http.path'])
  if (differences.length !== 2 || differences.some(({ path, value }) => !expectedPaths.has(path) || value !== '/')) {
    throw new Error('Representative root event must differ from the frozen event only by its two path fields')
  }
}

function collectDifferences(expected, actual, path, differences) {
  if (isObject(expected) && isObject(actual)) {
    const keys = [...new Set([...Object.keys(expected), ...Object.keys(actual)])].sort()
    for (const key of keys) {
      collectDifferences(expected[key], actual[key], path ? `${path}.${key}` : key, differences)
    }
    return
  }
  if (expected !== actual) {
    differences.push({ path, value: actual })
  }
}

function validateResponse(response) {
  if (!response || typeof response.statusCode !== 'number' || !Number.isFinite(response.statusCode)) {
    throw new Error('Packaged Nitro Lambda handler did not return an HTTP response with a numeric statusCode')
  }
  if (response.statusCode >= 500) {
    throw new Error(`Packaged Nitro Lambda handler returned ${response.statusCode}`)
  }
}

function summarizeResponse(response) {
  const fieldNames = new Set(['body', 'cookies', 'headers', 'isBase64Encoded', 'multiValueHeaders', 'statusCode'])
  for (const key of Object.keys(response)) {
    fieldNames.add(key)
  }

  const fields = {}
  for (const key of [...fieldNames].sort()) {
    const present = Object.hasOwn(response, key)
    const value = response[key]
    fields[key] = {
      present,
      type: present ? valueType(value) : 'absent',
      byteLength: present ? valueByteLength(value) : 0,
    }
  }
  return {
    type: valueType(response),
    fields,
  }
}

function valueByteLength(value) {
  if (value === undefined || value === null) {
    return 0
  }
  if (typeof value === 'string') {
    return Buffer.byteLength(value, 'utf8')
  }
  if (Buffer.isBuffer(value) || value instanceof Uint8Array) {
    return value.byteLength
  }
  try {
    return Buffer.byteLength(stableSerialize(value), 'utf8')
  } catch {
    return null
  }
}

function valueType(value) {
  if (value === null) {
    return 'null'
  }
  if (Array.isArray(value)) {
    return 'array'
  }
  return typeof value
}

function stableSerialize(value) {
  if (value === null || typeof value !== 'object') {
    const serialized = JSON.stringify(value)
    if (serialized === undefined) {
      throw new TypeError('Cannot canonically serialize undefined or function values')
    }
    return serialized
  }
  if (Array.isArray(value)) {
    return `[${value.map(stableSerialize).join(',')}]`
  }
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableSerialize(value[key])}`).join(',')}}`
}

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function isWithin(target, directory) {
  const path = resolve(target)
  const root = resolve(directory)
  const pathRelative = relative(root, path)
  return path === root || (pathRelative !== '' && !pathRelative.startsWith('..') && !isAbsolute(pathRelative))
}

function elapsedMs(startedAt) {
  return Number((performance.now() - startedAt).toFixed(3))
}

function marker(name) {
  writeLine(`diagnostic_phase=${name}`)
}

function writeLine(line) {
  process.stdout.write(`${line}\n`)
}

function errorName(error) {
  const name = typeof error?.name === 'string' ? error.name : 'Error'
  return ['Error', 'RangeError', 'SyntaxError', 'TypeError', 'UsageError'].includes(name) ? name : 'Error'
}

function errorMessage(error, failedPhase) {
  if (error instanceof UsageError) {
    return error.message
  }
  const messages = {
    setup: 'diagnostic setup failed',
    extraction: 'archive extraction failed',
    import: 'handler import failed',
    'handler invocation': 'handler invocation failed',
  }
  return messages[failedPhase] || 'diagnostic failed'
}
