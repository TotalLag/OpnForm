import { createHash } from 'node:crypto'

const branch = process.argv[2]
if (!branch) {
  throw new Error('Pass the branch name as the only argument')
}

const slug = branch
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, '-')
  .replace(/^-+|-+$/g, '')
  .slice(0, 12) || 'branch'
const digest = createHash('sha256').update(branch).digest('hex').slice(0, 12)
const name = `opnform-ui-shadow-${slug}-${digest}`

if (!/^opnform-ui-shadow-[a-z0-9-]{1,12}-[a-f0-9]{12}$/.test(name) || name.includes('opnform-prod')) {
  throw new Error(`Unsafe shadow name: ${name}`)
}

console.log(name)
