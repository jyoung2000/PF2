import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/inspiration', () => ({
  listResearch: vi.fn(),
  getResearch: vi.fn(),
  researchPresets: vi.fn(),
  startResearch: vi.fn(),
  controlResearch: vi.fn(),
  getDiscoveryStatus: vi.fn(),
  researchExportUrl: (id: number, fmt: string) => `/api/inspiration/research/${id}/export.${fmt}`,
}))
vi.mock('../lib/toast', () => ({ toastError: vi.fn(), toastSuccess: vi.fn() }))

import {
  getDiscoveryStatus,
  listResearch,
  researchPresets,
  startResearch,
} from '../lib/inspiration'
import { ResearchTab } from './ResearchTab'

const job = {
  id: 7,
  query: 'kling camera movement prompts',
  label: null,
  status: 'partial' as const,
  sources: ['reddit', 'youtube'],
  params: {
    intent: { wants_prompt: true, models: ['kling'], media_type: 'video', rank: 'relevance' },
    routing: [{ source: 'reddit', score: 0.9, why: 'strong for prompts' }],
  },
  progress: {
    reddit: { state: 'done', found: 20, kept: 12 },
    youtube: { state: 'failed', reason: 'YouTube changed its page shape' },
  },
  stats: {},
  error: null,
  result_post_ids: [1],
  created_at: new Date().toISOString(),
  started_at: null,
  finished_at: null,
  items: [
    {
      id: 1,
      platform: 'reddit',
      prompt: 'slow dolly through a rainy alley',
      thumb_url: null,
      media_type: 'image',
      why: ['carries a published prompt', 'matches kling'],
      relevance: 0.92,
    },
  ],
}

describe('ResearchTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(listResearch).mockResolvedValue({ jobs: [job] } as never)
    vi.mocked(researchPresets).mockResolvedValue({
      presets: [{ key: 'prompt_discovery', label: 'Prompt discovery', query: 'full prompt' }],
    } as never)
    vi.mocked(getDiscoveryStatus).mockResolvedValue({
      searchable_sources: ['reddit', 'bluesky', 'youtube'],
      usable: true,
      requires_grok: false,
      grok_available: false,
      detail: '3 source(s) can answer a research query without any AI provider.',
    } as never)
    vi.mocked(startResearch).mockResolvedValue({ ...job, status: 'complete' } as never)
  })

  it('shows what the query was read as, and every source outcome including failures', async () => {
    render(<ResearchTab onOpen={() => {}} />)
    await screen.findByText(/kling camera movement prompts/)
    expect(screen.getByText(/wants published prompts/)).toBeTruthy()
    expect(screen.getByText(/strong for prompts/)).toBeTruthy()
    // a source that could not answer is still listed, with its reason
    const failed = screen.getByTitle('YouTube changed its page shape')
    expect(failed.textContent).toContain('youtube')
    // per-result reasons are rendered, not just the media
    expect(screen.getByText(/carries a published prompt/)).toBeTruthy()
    expect(screen.getByText('92%')).toBeTruthy()
  })

  it('says plainly that Grok and X are not required', async () => {
    render(<ResearchTab onOpen={() => {}} />)
    await waitFor(() =>
      expect(screen.getByText(/Grok and X are optional/)).toBeTruthy(),
    )
  })

  it('sends the chosen sources, and auto-routes when none are picked', async () => {
    const user = userEvent.setup()
    render(<ResearchTab onOpen={() => {}} />)
    await screen.findByText('auto-route')
    await user.type(screen.getByPlaceholderText(/What do you want to find/), 'veo prompts')
    await user.click(screen.getByRole('button', { name: 'Research' }))
    expect(vi.mocked(startResearch).mock.calls[0][0]).toEqual({
      query: 'veo prompts',
      sources: null,
    })

    await user.click(screen.getByRole('button', { name: 'reddit' }))
    await user.click(screen.getByRole('button', { name: 'Research' }))
    expect(vi.mocked(startResearch).mock.calls[1][0]).toEqual({
      query: 'veo prompts',
      sources: ['reddit'],
    })
  })

  it('runs a preset without needing a typed query', async () => {
    const user = userEvent.setup()
    render(<ResearchTab onOpen={() => {}} />)
    await user.click(await screen.findByRole('button', { name: 'Prompt discovery' }))
    expect(vi.mocked(startResearch).mock.calls[0][0]).toEqual({
      preset: 'prompt_discovery',
      sources: null,
    })
  })
})
