import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'

import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'


function DialogHarness() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button onClick={() => setOpen(true)}>打开确认</Button>
      <Dialog label="确认操作" onClose={() => setOpen(false)} open={open}>
        <Button onClick={() => setOpen(false)}>完成</Button>
      </Dialog>
    </>
  )
}

describe('Dialog', () => {
  it('focuses the close action and returns focus to the trigger after closing', async () => {
    const user = userEvent.setup()
    render(<DialogHarness />)
    const trigger = screen.getByRole('button', { name: '打开确认' })

    await user.click(trigger)
    expect(screen.getByRole('button', { name: '关闭确认操作' })).toHaveFocus()

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: '确认操作' })).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })
})
