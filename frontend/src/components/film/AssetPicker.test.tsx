import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const listAssets = vi.fn()
const createAsset = vi.fn()
vi.mock('../../lib/film', async () => {
  const actual = await vi.importActual<typeof import('../../lib/film')>('../../lib/film')
  return { ...actual, film: { ...actual.film, listAssets: (...a: unknown[]) => listAssets(...a), createAsset: (...a: unknown[]) => createAsset(...a), getAsset: vi.fn() } }
})
vi.mock('../../lib/toast', () => ({ toastError: vi.fn(), toastSuccess: vi.fn() }))

import { AssetPicker } from './AssetPicker'

const asset = (id: number, name: string, type: string, versions = 1) => ({
  id, type, name, description: null, tags: [], notes: null, favorite: false, pinned: false, approved: false, project_id: null, owner_asset_id: null, provenance: {},
  current_version_id: id * 10, current_version: { id: id * 10, asset_id: id, number: 1, label: 'v1', data: {}, locks: [], identity_anchors: [], continuity_rules: [], negative_constraints: [], primary_ref_id: null, primary_thumb_url: null, frozen: false, provenance: {}, note: null, refs: [], created_at: null, updated_at: null },
  version_count: versions, ref_count: 0, thumb_url: null, created_at: null, updated_at: null,
})

describe('<AssetPicker>', () => {
  beforeEach(() => {
    listAssets.mockReset()
    createAsset.mockReset()
    listAssets.mockResolvedValue({ assets: [asset(1, 'Jack', 'character', 3), asset(2, 'Sarah', 'character')] })
  })
  it('lists assets with their current version and lets the user pick a selection', async () => {
    const onPick = vi.fn()
    render(<AssetPicker types={['character']} onClose={() => undefined} onPick={onPick} />)
    await waitFor(() => expect(screen.getByText('Jack')).toBeInTheDocument())
    expect(screen.getByText('v1 · 3 versions')).toBeInTheDocument()
    expect(screen.getByText('exact version…')).toBeInTheDocument()      // only for multi-version assets
    fireEvent.click(screen.getByText('Jack'))
    expect(screen.getByText('1 selected')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Use selection'))
    expect(onPick).toHaveBeenCalledWith([expect.objectContaining({ asset_id: 1, version_id: null, role: 'character', version_label: 'v1 (current)' })])
  })
  it('single-select picks immediately', async () => {
    const onPick = vi.fn()
    render(<AssetPicker types={['character']} multi={false} onClose={() => undefined} onPick={onPick} />)
    await waitFor(() => screen.getByText('Sarah'))
    fireEvent.click(screen.getByText('Sarah'))
    expect(onPick).toHaveBeenCalledWith([expect.objectContaining({ asset_id: 2 })])
  })
  it('creates a new asset inline and selects it', async () => {
    createAsset.mockResolvedValue(asset(3, 'Mira', 'character'))
    render(<AssetPicker types={['character']} onClose={() => undefined} onPick={() => undefined} />)
    await waitFor(() => screen.getByText('Jack'))
    fireEvent.click(screen.getByText('+ New'))
    fireEvent.change(screen.getByPlaceholderText('Name'), { target: { value: 'Mira' } })
    fireEvent.click(screen.getByText('Create'))
    await waitFor(() => expect(createAsset).toHaveBeenCalledWith({ type: 'character', name: 'Mira' }))
    await waitFor(() => expect(screen.getByText('Mira')).toBeInTheDocument())
    expect(screen.getByText('1 selected')).toBeInTheDocument()
  })
  it('searches through the API as the query changes', async () => {
    render(<AssetPicker onClose={() => undefined} onPick={() => undefined} />)
    await waitFor(() => screen.getByText('Jack'))
    fireEvent.change(screen.getByLabelText('Search assets'), { target: { value: 'sa' } })
    await waitFor(() => expect(listAssets).toHaveBeenLastCalledWith({ type: undefined, q: 'sa' }))
  })
})
