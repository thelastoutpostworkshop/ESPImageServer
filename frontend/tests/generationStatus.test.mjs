import test from 'node:test'
import assert from 'node:assert/strict'
import { generationJobDetail, generationHasMeasuredProgress } from '../src/generationStatus.js'

test('loading has elapsed time without a fictitious percentage or step count', () => {
  const job = { status: 'running', stage: 'Loading SDXL from disk', steps: 0, elapsed_seconds: 125 }
  assert.equal(generationJobDetail(job), 'Loading SDXL from disk · 2m 5s elapsed')
  assert.equal(generationHasMeasuredProgress(job), false)
})

test('download counts are files, whereas generation counts are steps', () => {
  const job = { status: 'running', stage: 'Downloading SDXL: 2 of 8 files', step: 2, steps: 8, elapsed_seconds: 10 }
  assert.equal(generationHasMeasuredProgress(job), true)
  assert.doesNotMatch(generationJobDetail(job), /Step/)
  assert.match(generationJobDetail({ ...job, stage: 'Generating image' }), /Step 2 of 8/)
})

test('cancellation explains the wait and preserves the operation', () => {
  const job = { status: 'cancelling', stage: 'Loading SDXL from disk', steps: 0, elapsed_seconds: 90 }
  assert.match(generationJobDetail(job), /Cancellation requested.*Loading SDXL.*1m 30s elapsed/)
  assert.match(generationJobDetail(job), /next job will wait/)
  assert.equal(generationHasMeasuredProgress(job), false)
  assert.match(generationJobDetail({ ...job, status: 'cancelled', stage: 'Image generation cancelled' }), /^Image generation cancelled/)
})
