// The generated types must describe the shared contract fixtures: the typed
// literal below is checked by tsc against the generated Verdict interface,
// and vitest checks it stays byte-equal to the engine-side fixture. Drift in
// either direction turns one of the two red.
import { expect, test } from 'vitest'
import verdictFixture from '../../../tests/fixtures/contracts/verdict.json'
import type { Verdict, WsEnvelope } from './index'

const verdict: Verdict = {
  type: 'verdict',
  incident_id: 'inc-007',
  classes: [
    { class: 'attack', p: 0.87 },
    { class: 'expected_surge', p: 0.09 },
    { class: 'operational_fault', p: 0.02 },
    { class: 'code_fault', p: 0.02 },
  ],
  combination: false,
  confidence: 0.87,
  evidence: [
    {
      feature: 'ja3_novelty',
      value: 0.41,
      baseline: 0.03,
      direction: 'up',
      note: 'new client fingerprints inside event window',
    },
    {
      feature: 'uniq_ip_entropy',
      value: 4.1,
      baseline: 7.8,
      direction: 'down',
      note: 'traffic concentration inconsistent with organic fan surge',
    },
  ],
}

test('typed verdict literal matches the shared fixture', () => {
  expect(verdict).toEqual(verdictFixture)
})

test('envelope payload union narrows on the type discriminator', () => {
  const envelope: WsEnvelope = {
    seq: 10452,
    wall_ts: 1789460010.211,
    sim_ts: 1789455631.0,
    payload: verdict,
  }
  // Compile-time proof: after narrowing (telemetry records carry `kind`,
  // engine payloads carry `type`), verdict-only fields are reachable.
  if ('type' in envelope.payload && envelope.payload.type === 'verdict') {
    expect(envelope.payload.evidence.length).toBeGreaterThan(0)
  }
})
