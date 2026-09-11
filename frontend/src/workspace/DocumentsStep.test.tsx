import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DocumentsStep } from './DocumentsStep'
import { doc, engagement } from '../test-fixtures'
import { mockApi } from '../test-utils'

const E = engagement.engagement.engagement_id

afterEach(() => vi.restoreAllMocks())

describe('DocumentsStep', () => {
  it('shows document statuses, pages, chunks and errors', () => {
    const detail = {
      ...engagement,
      documents: [
        doc({ file_name: 'questionnaire.pdf', status: 'indexed', pages: 2, chunks: 3 }),
        doc({ file_name: 'locations.docx', doc_type: 'locations', status: 'processing' }),
        doc({ file_name: 'sales.csv', kind: 'sales_csv', doc_type: 'other', status: 'validated' }),
        doc({ file_name: 'bad.pdf', doc_type: 'other', status: 'failed', error: 'HttpResponseError: 400' }),
      ],
    }
    render(<DocumentsStep detail={detail} onChanged={vi.fn()} />)

    const rows = screen.getAllByRole('row').slice(1)
    expect(within(rows[0]).getByText('questionnaire.pdf')).toBeInTheDocument()
    expect(within(rows[0]).getByText('Indexed')).toBeInTheDocument()
    expect(within(rows[0]).getByText(/2 pages · 3 chunks/)).toBeInTheDocument()
    expect(within(rows[1]).getByText('Processing…')).toBeInTheDocument()
    expect(within(rows[2]).getByText('Validated')).toBeInTheDocument()
    expect(within(rows[3]).getByText(/HttpResponseError: 400/)).toBeInTheDocument()
  })

  it('uploads a file with the chosen document type and notifies the parent', async () => {
    const onChanged = vi.fn()
    const calls = mockApi({
      [`POST /api/engagements/${E}/documents`]: (init) => {
        const form = init?.body as FormData
        expect((form.get('file') as File).name).toBe('q.pdf')
        expect(form.get('doc_type')).toBe('questionnaire')
        return { status: 201, body: doc({ file_name: 'q.pdf' }) }
      },
    })
    render(<DocumentsStep detail={engagement} onChanged={onChanged} />)

    await userEvent.selectOptions(screen.getByLabelText(/Document type/), 'questionnaire')
    await userEvent.upload(
      screen.getByLabelText(/Choose file/),
      new File(['%PDF'], 'q.pdf', { type: 'application/pdf' }),
    )
    await userEvent.click(screen.getByRole('button', { name: /Upload/ }))

    expect(calls).toContain(`POST /api/engagements/${E}/documents`)
    expect(onChanged).toHaveBeenCalled()
  })

  it('shows the backend reason when an upload is rejected', async () => {
    mockApi({
      [`POST /api/engagements/${E}/documents`]: () => ({
        status: 400,
        body: { detail: "unsupported file type '.txt'; upload PDF, DOCX or CSV" },
      }),
    })
    render(<DocumentsStep detail={engagement} onChanged={vi.fn()} />)

    await userEvent.upload(screen.getByLabelText(/Choose file/), new File(['x'], 'notes.txt'), {
      applyAccept: false,
    })
    await userEvent.click(screen.getByRole('button', { name: /Upload/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/upload PDF, DOCX or CSV/)
  })

  it('process and demo buttons call the backend and notify the parent', async () => {
    const onChanged = vi.fn()
    const calls = mockApi({
      [`POST /api/engagements/${E}/documents/process`]: () => ({ status: 202, body: { engagement_id: E, queued: 1 } }),
      [`POST /api/engagements/${E}/demo-files`]: () => ({
        status: 202,
        body: { engagement_id: E, documents: [doc({})], queued: 2 },
      }),
    })
    const withPending = { ...engagement, documents: [doc({ status: 'uploaded' })] }
    render(<DocumentsStep detail={withPending} onChanged={onChanged} />)

    await userEvent.click(screen.getByRole('button', { name: /Process documents/ }))
    await userEvent.click(screen.getByRole('button', { name: /Load synthetic demo/ }))

    expect(calls).toContain(`POST /api/engagements/${E}/documents/process`)
    expect(calls).toContain(`POST /api/engagements/${E}/demo-files`)
    expect(onChanged).toHaveBeenCalledTimes(2)
  })

  it('disables Process when nothing is waiting', () => {
    render(<DocumentsStep detail={engagement} onChanged={vi.fn()} />)
    expect(screen.getByRole('button', { name: /Process documents/ })).toBeDisabled()
  })
})
