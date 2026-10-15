import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { useStudio } from '../store'
import { cell, pollData, pollView } from '../test/fixtures'
import { PollWindow } from './PollWindow'

const initial = useStudio.getState()

beforeEach(() => {
  localStorage.clear()
  useStudio.setState(initial, true)
})

describe('PollWindow', () => {
  it('shows live values and the Tx/Err line', () => {
    const view = pollView('w1')
    useStudio.getState().handle({ type: 'snapshot', connections: [], polls: [view] })
    render(<PollWindow view={view} />)
    expect(screen.getByText('Waiting for data…')).toBeInTheDocument()

    act(() => {
      useStudio.getState().handle({
        type: 'poll',
        data: pollData('w1', 5, [cell(0, 42, { alias: 'level', unit: 'm' }), cell(1, -3)]),
      })
    })
    expect(screen.getByTestId('poll-status')).toHaveTextContent(
      'Tx = 5: Err = 0: ID = 1: F = 03: SR = 1000ms',
    )
    expect(screen.getByText('42')).toBeInTheDocument()
    expect(screen.getByText('level')).toBeInTheDocument()
    expect(screen.getByText('-3')).toBeInTheDocument()
  })

  it('shows the error but keeps the previous values', () => {
    const view = pollView('w1')
    const { handle } = useStudio.getState()
    handle({ type: 'snapshot', connections: [], polls: [view] })
    handle({ type: 'poll', data: pollData('w1', 1, [cell(0, 9)]) })
    render(<PollWindow view={view} />)

    act(() => handle({ type: 'poll', data: pollData('w1', 2, null, 1) }))
    expect(screen.getByText('Timeout error')).toBeInTheDocument()
    expect(screen.getByText('9')).toBeInTheDocument()
    expect(screen.getByTestId('poll-status')).toHaveTextContent('Tx = 2: Err = 1')
  })

  it('plots the selected values, one series per 32-bit value', () => {
    const view = pollView('w1')
    const { handle } = useStudio.getState()
    handle({ type: 'snapshot', connections: [], polls: [view] })
    handle({
      type: 'poll',
      data: pollData('w1', 1, [cell(0, 5), cell(1, 70000), cell(2, 0, { covered_by: 1 })]),
    })
    render(<PollWindow view={view} />)
    const plotButton = screen.getByRole('button', { name: 'Plot' })
    expect(plotButton).toBeDisabled()

    const rows = screen.getAllByRole('row').slice(1)
    fireEvent.click(rows[0])
    fireEvent.click(rows[2], { shiftKey: true })
    fireEvent.click(plotButton)
    expect(useStudio.getState().plotted).toEqual([
      { poll: 'w1', address: 0 },
      { poll: 'w1', address: 1 },
    ])
    expect(screen.getByTestId('plotted-0')).toBeInTheDocument()
    expect(screen.getByTestId('plotted-1')).toBeInTheDocument()
    expect(screen.queryByTestId('plotted-2')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Unplot' }))
    expect(useStudio.getState().plotted).toEqual([])
    expect(screen.queryByTestId('plotted-0')).toBeNull()
  })
})
