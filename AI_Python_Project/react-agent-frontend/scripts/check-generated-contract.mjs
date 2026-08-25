import { spawnSync } from 'node:child_process'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const snapshotUrl = new URL('../contracts/backend-openapi.json', import.meta.url)
const generatedUrl = new URL(
  '../src/api/generated/backend-schema.ts',
  import.meta.url,
)
const cliUrl = new URL(
  '../node_modules/openapi-typescript/bin/cli.js',
  import.meta.url,
)
const temporaryDirectory = await mkdtemp(
  join(tmpdir(), 'react-agent-contract-'),
)
const temporaryOutput = join(temporaryDirectory, 'backend-schema.ts')

try {
  const generation = spawnSync(
    process.execPath,
    [
      fileURLToPath(cliUrl),
      fileURLToPath(snapshotUrl),
      '--output',
      temporaryOutput,
    ],
    { encoding: 'utf8' },
  )

  if (generation.status !== 0) {
    throw new Error('Unable to regenerate the backend contract for drift checking.')
  }

  const expected = await readFile(temporaryOutput, 'utf8')
  const actual = await readFile(generatedUrl, 'utf8')

  if (actual !== expected) {
    throw new Error(
      'Generated backend contract is stale. Run `pnpm contracts:generate` and commit the result.',
    )
  }
} finally {
  await rm(temporaryDirectory, { force: true, recursive: true })
}
