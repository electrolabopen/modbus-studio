import { act, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { useStudio } from '../store'
import { cell, pollData, pollView } from '../test/fixtures'
import { PollWindow } from './PollWindow'

const initial = useStudio.getState()

beforeEach(() => {
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
})
