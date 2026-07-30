import { mkdir, rm, stat, writeFile } from 'node:fs/promises'
import { execFile, spawn } from 'node:child_process'
import { promisify } from 'node:util'
import { dirname, join, resolve } from 'node:path'

const execFileAsync = promisify(execFile)
const root = process.cwd()
const server = join(root, '.output/server')
const work = join(root, '.aws-shadow/package')
const output = resolve(root, process.env.AWS_LAMBDA_ZIP || '.aws-shadow/lambda.zip')
const packageScript = String.raw`
package_root=$1
output=$2
epoch='1980-01-01 00:00:00 UTC'
export LC_ALL=C TZ=UTC

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

unsupported=$(find -P "$package_root" -mindepth 1 ! \( -type d -o -type f -o -type l \) -print -quit)
[[ -z "$unsupported" ]] || fail 'Packaged Lambda contains an unsupported entry'

find -P "$package_root" -mindepth 1 -print0 |
  while IFS= read -r -d '' entry; do
    case "$entry" in
      *$'\n'*) fail 'Packaged Lambda contains a newline in an entry name' ;;
    esac
  done

find -P "$package_root" -type l -print0 |
  while IFS= read -r -d '' entry; do
    target=$(readlink -- "$entry") || fail "Packaged Lambda contains an unreadable symbolic link: $entry"
    [[ "$target" != /* ]] || fail "Packaged Lambda contains an absolute symbolic link: $entry"

    resolved=$(realpath -e -- "$entry") || fail "Packaged Lambda contains a missing symbolic link target: $entry"
    [[ "$resolved" == "$package_root" || "$resolved" == "$package_root/"* ]] || fail "Packaged Lambda contains a symbolic link outside the package: $entry"
  done

find -P "$package_root" -mindepth 1 -exec touch -h -d "$epoch" -- {} +
(
  cd "$package_root"
  find -P . -mindepth 1 -printf '%P\0' |
    LC_ALL=C sort -z -S 64M |
    tr '\0' '\n' |
    zip -X -y -q "$output" -@
)
`

await stat(join(server, 'index.mjs'))
await rm(work, { recursive: true, force: true })
await mkdir(work, { recursive: true })
await run('cp', ['-RP', `${server}/.`, work])
await mkdir(dirname(output), { recursive: true })
await rm(output, { force: true })
await run('bash', ['-euo', 'pipefail', '-c', packageScript, 'package-aws-lambda', work, output])

const archive = await stat(output)
const { stdout } = await execFileAsync('sha256sum', ['-b', '--', output], { maxBuffer: 1024 })
const sha256 = stdout.slice(0, 64)
if (!/^[a-f0-9]{64}$/.test(sha256)) {
  throw new Error('Unable to calculate packaged Lambda SHA-256')
}

const metadata = {
  handler: 'index.handler',
  bytes: archive.size,
  sha256,
}
await writeFile(`${output}.json`, `${JSON.stringify(metadata, null, 2)}\n`)
console.log(JSON.stringify(metadata))

function run(command, args) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(command, args, { stdio: 'inherit' })
    child.once('error', reject)
    child.once('close', (code, signal) => {
      if (code === 0) {
        resolvePromise()
      } else {
        reject(new Error(`${command} exited with ${signal ? `signal ${signal}` : `code ${code}`}`))
      }
    })
  })
}
