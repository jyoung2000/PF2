import { describe, expect, it } from 'vitest'
import { errorMessage } from '../api'

describe('errorMessage', () => {
  it('renders a structured tool failure as an actionable sentence', () => {
    expect(errorMessage(
      { message: 'Generate image is not available: no connected provider declares text to image',
        recoverable: true, next_action: 'connect a provider under Settings → AI providers' },
      'fallback',
    )).toBe('Generate image is not available: no connected provider declares text to image — connect a provider under Settings → AI providers')
  })
  it('passes plain strings through and never leaks JSON', () => {
    expect(errorMessage('Prompt is empty.', 'x')).toBe('Prompt is empty.')
    expect(errorMessage({ errors: ['a', 'b'] }, 'Request failed')).toBe('Request failed')
    expect(errorMessage(undefined, 'Request failed')).toBe('Request failed')
  })
  it('summarises FastAPI validation errors', () => {
    expect(errorMessage([{ loc: ['body', 'idea'], msg: 'field required', type: 'missing' }], 'x'))
      .toBe('field required')
  })
})
