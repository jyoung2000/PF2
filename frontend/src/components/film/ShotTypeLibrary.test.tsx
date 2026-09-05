import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ShotType } from '../../lib/film'
import { ShotTypeLibrary } from './ShotTypeLibrary'

const st = (key: string, label: string, extra: Partial<ShotType> = {}): ShotType => ({
  key, label, abbr: key.slice(0, 3).toUpperCase(), what: `${label} what`, use: `${label} use`,
  camera: { shot_size: 'medium', angle: 'eye_level', lens_mm: 50, height_m: 1.5, movement: 'static' }, figure: 0.7, ...extra,
})
const types = [st('wide', 'Wide Shot', { figure: 0.3 }), st('close_up', 'Close-Up', { figure: 1 }), st('two_shot', 'Two Shot', { figures: 2 }), st('top_down', 'Top-Down', { camera: { shot_size: 'wide', angle: 'overhead', lens_mm: 24, height_m: 5, movement: 'static' } })]

describe('<ShotTypeLibrary>', () => {
  it('renders one visual card per shot type with name, explanation and use case', () => {
    render(<ShotTypeLibrary types={types} favorites={[]} onPick={() => undefined} />)
    expect(screen.getAllByRole('button', { name: /what/ })).toHaveLength(4)
    expect(screen.getByText('Use for: Close-Up use')).toBeInTheDocument()
    expect(document.querySelectorAll('svg').length).toBeGreaterThanOrEqual(4)
  })
  it('filters by search and by favourites', () => {
    render(<ShotTypeLibrary types={types} favorites={['top_down']} onPick={() => undefined} onToggleFavorite={() => undefined} />)
    fireEvent.change(screen.getByLabelText('Search shot types'), { target: { value: 'two' } })
    expect(screen.getByText('Two Shot')).toBeInTheDocument()
    expect(screen.queryByText('Wide Shot')).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Search shot types'), { target: { value: '' } })
    fireEvent.click(screen.getByText('★ favourites'))
    expect(screen.getByText('Top-Down')).toBeInTheDocument()
    expect(screen.queryByText('Close-Up')).not.toBeInTheDocument()
  })
  it('applies a preset on click and toggles favourites', () => {
    const onPick = vi.fn()
    const onFav = vi.fn()
    render(<ShotTypeLibrary types={types} favorites={[]} value="wide" onPick={onPick} onToggleFavorite={onFav} />)
    fireEvent.click(screen.getByText('Close-Up'))
    expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ key: 'close_up' }))
    fireEvent.click(screen.getAllByLabelText('Add favourite')[0])
    expect(onFav).toHaveBeenCalledWith('wide')
    expect(document.querySelector('[data-shot-type="wide"]')).toBeTruthy()
  })
})
