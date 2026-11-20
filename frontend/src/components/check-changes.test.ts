import { describe, expect, it } from 'vitest'

import { changeText } from '@/lib/check-results'

describe('changeText', () => {
  it('uses the words of the source', () => {
    expect(changeText({ source: 'VIES', previous_status: 'OK', status: 'FINDING' })).toBe('Valid → Invalid')
    expect(changeText({ source: 'BMF', previous_status: 'OK', status: 'FINDING' })).toBe('Not listed → Listed')
    expect(changeText({ source: 'HFU', previous_status: 'ERROR', status: 'OK' })).toBe('Error → Listed')
    expect(changeText({ source: 'FIRMENBUCH', previous_status: 'OK', status: 'FINDING' })).toBe('Registered → Flagged')
    expect(changeText({ source: 'GISA', previous_status: 'OK', status: 'FINDING' })).toBe('Active licence → No active licence')
  })
})
