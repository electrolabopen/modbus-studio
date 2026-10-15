import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Cell } from '../api/types'
import { useStudio } from '../store'
import { cell, pollData, pollView } from '../test/fixtures'
import { PollWindow } from './PollWindow'

const initial = useStudio.getState()

let calls: { url: string; method: string; body: unknown }[]

beforeEach(() => {
  useStudio.setState(initial, true)
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, method: init.method ?? 'GET', body: JSON.parse(String(init.body)) })
      return new Response(JSON.stringify(pollView('w1')), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderWindow(cells: Cell[]) {
  const view = pollView('w1')
  const { handle } = useStudio.getState()
  handle({ type: 'snapshot', connections: [], polls: [view] })
  handle({ type: 'poll', data: pollData('w1', 1, cells) })
  render(<PollWindow view={view} />)
}

const row = (address: number) => screen.getByText(String(address), { selector: 'td.addr' })

describe('cell formats', () => {
  it('formats a Shift+click range', async () => {
    renderWindow([cell(0, 10), cell(1, 11), cell(2, 12)])
    const format = screen.getByRole('button', { name: 'Format…' })
    expect(format).toBeDisabled()

    fireEvent.click(row(0))
    fireEvent.click(row(2), { shiftKey: true })
    expect(screen.getAllByRole('row', { selected: true })).toHaveLength(3)
    fireEvent.click(format)

    expect(screen.getByText(/addresses 0–2/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Data type'), { target: { value: 'float32' } })
    expect(screen.getByText(/2 registers per value, 2 values starting at 0/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Unit'), { target: { value: ' bar ' } })
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Apply' })))

    expect(calls).toEqual([
      {
        url: '/api/polls/w1/formats',
        method: 'PATCH',
        body: { start: 0, end: 2, dtype: 'float32', order: 'ABCD', scale: 1, unit: 'bar' },
      },
    ])
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('selects whole 32-bit values and resets them', async () => {
    renderWindow([
      cell(0, 1.5, { raw: [0x3fc0, 0] }),
      cell(1, 0, { text: '', covered_by: 0 }),
      cell(2, 7),
    ])
    // Clicking the second register selects the value that starts at 0.
    fireEvent.click(screen.getByText('1', { selector: 'td.addr' }))
    fireEvent.click(screen.getByRole('button', { name: 'Format…' }))
    expect(screen.getByText(/addresses 0–1/)).toBeInTheDocument()
    await act(async () =>
      fireEvent.click(screen.getByRole('button', { name: 'Reset to window format' })),
    )
    expect(calls[0].body).toEqual({ start: 0, end: 1, reset: true })
  })

  it('rejects a zero scale', () => {
    renderWindow([cell(0, 10)])
    fireEvent.doubleClick(row(0))
    fireEvent.change(screen.getByLabelText('Scale'), { target: { value: '0' } })
    expect(screen.getByText('Scale must be a non-zero number')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled()
  })
})

describe('alias editing', () => {
  it('saves on Enter', async () => {
    renderWindow([cell(0, 10), cell(1, 11)])
    const aliasCells = document.querySelectorAll('td.alias')
    fireEvent.doubleClick(aliasCells[1])
    const input = screen.getByLabelText('Alias')
    fireEvent.change(input, { target: { value: '  pump  ' } })
    await act(async () => fireEvent.keyDown(input, { key: 'Enter' }))
    // Enter is followed by a blur when the input unmounts: still one request.
    expect(calls).toEqual([
      { url: '/api/polls/w1/formats', method: 'PATCH', body: { start: 1, end: 1, alias: 'pump' } },
    ])
    expect(screen.queryByLabelText('Alias')).not.toBeInTheDocument()
  })

  it('cancels on Escape and skips unchanged values', () => {
    renderWindow([cell(0, 10)])
    const aliasCell = document.querySelector('td.alias')!
    fireEvent.doubleClick(aliasCell)
    fireEvent.change(screen.getByLabelText('Alias'), { target: { value: 'x' } })
    fireEvent.keyDown(screen.getByLabelText('Alias'), { key: 'Escape' })
    fireEvent.doubleClick(aliasCell)
    fireEvent.blur(screen.getByLabelText('Alias'))
    expect(calls).toEqual([])
  })
})
