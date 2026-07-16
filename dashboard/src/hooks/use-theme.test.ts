import { describe, expect, it } from 'vitest'

import { getTheme, setTheme } from './use-theme'

describe('theme', () => {
  it('applies a manual choice to the document and persists it', () => {
    setTheme('light')
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(localStorage.getItem('theme')).toBe('light')
    expect(getTheme()).toBe('light')

    setTheme('dark')
    expect(getTheme()).toBe('dark')
    expect(localStorage.getItem('theme')).toBe('dark')
  })
})
