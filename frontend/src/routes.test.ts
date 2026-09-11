import { describe, expect, it } from 'vitest'
import { parseRoute } from './routes'

describe('parseRoute', () => {
  it('maps hashes to pages and steps', () => {
    expect(parseRoute('')).toEqual({ page: 'home' })
    expect(parseRoute('#/')).toEqual({ page: 'home' })
    expect(parseRoute('#/e/acme-2025-ab12')).toMatchObject({ page: 'workspace', step: 'documents' })
    expect(parseRoute('#/e/acme-2025-ab12/review')).toMatchObject({ step: 'review', reviewId: undefined })
    expect(parseRoute('#/e/acme-2025-ab12/findings/rev_1')).toMatchObject({ step: 'findings', reviewId: 'rev_1' })
    expect(parseRoute('#/e/acme-2025-ab12/bogus')).toMatchObject({ step: 'documents' })
    expect(parseRoute('#/e/../etc')).toEqual({ page: 'home' })
  })
})
