// Component tests for components/CorpusPanel.tsx: the Database tab's corpus versions (issue #114).
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';

import CorpusPanel, { type CorpusStatus, type HistoryRow, sendParts } from '@/components/CorpusPanel';

import { server } from '../../mocks/server';

const ACTIVE = {
  built: '2026-11-14T19:45:32+00:00',
  model: 'st-bge-m3',
  dim: 1024,
  chunks: 2_400_000,
  kommuner: 290,
  uploaded: { by: 'owner@kth.se', at: '2026-11-14T19:46:04+00:00', file: 'b.dump' },
};
const PREVIOUS = { ...ACTIVE, built: '2026-10-25T10:00:00+00:00', chunks: 1_900_000, uploaded: null };

const DONE: HistoryRow = {
  id: 1, action: 'replace', status: 'done', user_email: 'owner@kth.se', file_name: 'b.dump', model: 'st-bge-m3',
  chunks: 2_400_000, kommuner: 290, built: ACTIVE.built, progress: { phase: 'done', percent: 100, message: 'Live' },
  detail: 'Live: 2,400,000 chunks of st-bge-m3', started_at: '2026-11-14T19:45:40+00:00', finished_at: '2026-11-14T19:46:04+00:00',
};

function status(changes: Partial<CorpusStatus> = {}): CorpusStatus {
  return {
    active: ACTIVE, previous: PREVIOUS, job: DONE, uploads: [], history: [DONE], serving: true, part_bytes: 4,
    upload_free_bytes: 25e9, database_bytes: 30e9, disk_limit_bytes: 40e9, ...changes,
  };
}

function serve(body: CorpusStatus) {
  server.use(http.get('*/api/corpus', () => HttpResponse.json(body)));
}

describe('CorpusPanel', () => {
  it('shows the active and previous versions with the owner buttons', async () => {
    serve(status());
    render(<CorpusPanel canManage />);

    expect(await screen.findByText('2,400,000 · 290 kommuner')).toBeInTheDocument();
    expect(screen.getByText(/owner@kth\.se, /)).toBeInTheDocument();
    expect(screen.getByText('by hand (before the panel)')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Download/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Roll back/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Upload and replace/ })).toBeDisabled(); // no file picked
  });

  it('shows developers the versions and the history without any button', async () => {
    serve(status());
    render(<CorpusPanel canManage={false} />);

    expect(await screen.findByText('2,400,000 · 290 kommuner')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getByRole('table')).toHaveTextContent('Live: 2,400,000 chunks of st-bge-m3');
  });

  it('says there is no corpus yet', async () => {
    serve(status({ active: null, previous: null, job: null, history: [] }));
    render(<CorpusPanel canManage />);

    expect(await screen.findAllByText('None')).toHaveLength(2);
    expect(screen.getByText('Nothing yet.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Roll back/ })).not.toBeInTheDocument();
  });

  it('follows a running job and reloads the view when it goes live', async () => {
    const running: HistoryRow = { ...DONE, id: 2, status: 'running', progress: { phase: 'restoring', percent: 42, message: 'Restoring: TABLE DATA corpus_chunks' } };
    let calls = 0;
    server.use(http.get('*/api/corpus', () => HttpResponse.json(status({ job: calls++ === 0 ? running : { ...DONE, id: 2 } }))));
    const onSwapped = vi.fn();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      render(<CorpusPanel canManage onSwapped={onSwapped} />);
      expect(await screen.findByText('42 %')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Roll back/ })).toBeDisabled();
      await vi.advanceTimersByTimeAsync(3100);
      await waitFor(() => expect(onSwapped).toHaveBeenCalled());
      expect(screen.getByText(/Last replace: Live/)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('says a failed replace left the live corpus as it was', async () => {
    serve(status({ job: { ...DONE, status: 'failed', detail: 'The restored corpus is not valid: Chunk counts differ' } }));
    render(<CorpusPanel canManage />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/Chunk counts differ.*The live corpus was not changed/);
  });

  it('rolls back after a confirmation', async () => {
    serve(status());
    const rollback = vi.fn();
    server.use(http.post('*/api/corpus/rollback', () => { rollback(); return HttpResponse.json({ ...DONE, action: 'rollback' }); }));
    const onSwapped = vi.fn();
    render(<CorpusPanel canManage onSwapped={onSwapped} />);

    await userEvent.click(await screen.findByRole('button', { name: /Roll back/ }));
    expect(rollback).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Make it live' }));
    await waitFor(() => expect(rollback).toHaveBeenCalledOnce());
    expect(onSwapped).toHaveBeenCalled();
  });

  it('shows a refused roll back', async () => {
    serve(status());
    server.use(http.post('*/api/corpus/rollback', () => HttpResponse.json({ detail: 'A corpus job is running' }, { status: 409 })));
    render(<CorpusPanel canManage />);

    await userEvent.click(await screen.findByRole('button', { name: /Roll back/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Make it live' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('A corpus job is running');
  });

  it('uploads the dump in parts, then starts the restore', async () => {
    serve(status());
    const file = new File(['0123456789'], 'b.dump');
    const manifest = new File([JSON.stringify({ format: 'pyrmit-corpus-dump', sha256: 'ab' })], 'b.manifest.json');
    let created: any = null;
    const parts: string[] = [];
    let received = 0;
    let restored = false;
    server.use(
      http.post('*/api/corpus/uploads', async ({ request }) => {
        created = await request.json();
        return HttpResponse.json({ id: 'u1', size: 10, received: 0, complete: false, part_bytes: 4 });
      }),
      http.put('*/api/corpus/uploads/u1', async ({ request }) => {
        const offset = Number(new URL(request.url).searchParams.get('offset'));
        const body = await request.text();
        parts.push(`${offset}:${body}`);
        received = offset + body.length;
        return HttpResponse.json({ id: 'u1', size: 10, received, complete: received === 10, part_bytes: 4 });
      }),
      http.post('*/api/corpus/uploads/u1/restore', () => { restored = true; return HttpResponse.json(DONE); }),
    );
    render(<CorpusPanel canManage />);

    await userEvent.upload(await screen.findByLabelText('Dump file'), file);
    await userEvent.upload(screen.getByLabelText('Manifest file'), manifest);
    await userEvent.click(screen.getByRole('button', { name: /Upload and replace/ }));

    await waitFor(() => expect(restored).toBe(true));
    expect(created).toEqual({ file_name: 'b.dump', size: 10, manifest: { format: 'pyrmit-corpus-dump', sha256: 'ab' } });
    expect(parts).toEqual(['0:0123', '4:4567', '8:89']);
  });

  it('refuses a manifest that is not JSON', async () => {
    serve(status());
    render(<CorpusPanel canManage />);

    await userEvent.upload(await screen.findByLabelText('Dump file'), new File(['x'], 'b.dump'));
    await userEvent.upload(screen.getByLabelText('Manifest file'), new File(['not json'], 'b.manifest.json'));
    await userEvent.click(screen.getByRole('button', { name: /Upload and replace/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The manifest is not JSON');
  });

  it('offers to resume an unfinished upload of the same file', async () => {
    serve(status({ uploads: [{ id: 'u1', file_name: 'b.dump', size: 10, received: 4, complete: false, user_email: 'owner@kth.se', created: '' }] }));
    render(<CorpusPanel canManage />);

    expect(await screen.findByText(/Unfinished upload: b\.dump/)).toHaveTextContent('pick the same file to resume');
    await userEvent.upload(screen.getByLabelText('Dump file'), new File(['0123456789'], 'b.dump'));
    expect(screen.getByRole('button', { name: /Resume upload/ })).toBeInTheDocument();
  });

  it('downloads through a link the browser follows itself', async () => {
    serve(status());
    server.use(http.post('*/api/corpus/download-link', () => HttpResponse.json({ url: '/api/corpus/download?token=t', expires_minutes: 5 })));
    const assign = vi.fn();
    const original = window.location;
    Object.defineProperty(window, 'location', { configurable: true, value: { ...original, assign } });
    try {
      render(<CorpusPanel canManage />);
      await userEvent.click(await screen.findByRole('button', { name: /Download/ }));
      await waitFor(() => expect(assign).toHaveBeenCalledWith('/api/corpus/download?token=t'));
    } finally {
      Object.defineProperty(window, 'location', { configurable: true, value: original });
    }
  });

  it('says so when the status cannot be read', async () => {
    server.use(http.get('*/api/corpus', () => HttpResponse.json({ detail: 'No DATABASE_URL' }, { status: 503 })));
    render(<CorpusPanel canManage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('No DATABASE_URL');
  });

  it('lists the history', async () => {
    const rows: HistoryRow[] = [
      { ...DONE, id: 3, action: 'rollback', file_name: null, detail: 'The previous version is live again' },
      { ...DONE, id: 2, status: 'failed', file_name: 'bad.dump', detail: 'sha256 differs' },
      DONE,
    ];
    serve(status({ history: rows }));
    render(<CorpusPanel canManage={false} />);

    const table = await screen.findByRole('table');
    expect(within(table).getAllByRole('row')).toHaveLength(4);
    expect(table).toHaveTextContent('Roll back');
    expect(table).toHaveTextContent('failed: sha256 differs');
  });
});

describe('sendParts', () => {
  it('resumes from the offset the server holds after a lost answer', async () => {
    const file = new Blob(['0123456789']);
    const sent: number[] = [];
    let held = 0;
    let fail = true;
    server.use(
      http.put('*/api/corpus/uploads/u1', async ({ request }) => {
        const offset = Number(new URL(request.url).searchParams.get('offset'));
        sent.push(offset);
        held = offset + (await request.text()).length;
        if (offset === 4 && fail) {
          fail = false;
          return HttpResponse.json({ detail: 'proxy hiccup' }, { status: 502 }); // the part arrived, its answer did not
        }
        return HttpResponse.json({ id: 'u1', size: 10, received: held, complete: held === 10, part_bytes: 4 });
      }),
      http.get('*/api/corpus/uploads/u1', () => HttpResponse.json({ id: 'u1', size: 10, received: held, complete: false, part_bytes: 4 })),
    );
    const progress: number[] = [];
    const done = await sendParts(file, { id: 'u1', size: 10, received: 0, complete: false, part_bytes: 4 },
      (r) => progress.push(r), () => false, async () => {});

    expect(done.received).toBe(10);
    expect(sent).toEqual([0, 4, 8]); // the part at 4 is not sent twice: the server already had it
    expect(progress).toEqual([4, 8, 10]);
  });

  it('stops when paused and gives up after repeated failures', async () => {
    const file = new Blob(['0123456789']);
    const start = { id: 'u1', size: 10, received: 0, complete: false, part_bytes: 4 };
    expect((await sendParts(file, start, () => {}, () => true)).received).toBe(0);

    server.use(
      http.put('*/api/corpus/uploads/u1', () => HttpResponse.json({}, { status: 503 })),
      http.get('*/api/corpus/uploads/u1', () => HttpResponse.json(start)),
    );
    await expect(sendParts(file, start, () => {}, () => false, async () => {})).rejects.toThrow('keeps failing');
  });

  it('stops at once on a refusal', async () => {
    server.use(http.put('*/api/corpus/uploads/u1', () => HttpResponse.json({ detail: 'A part is at most 4 bytes' }, { status: 413 })));
    await expect(
      sendParts(new Blob(['0123456789']), { id: 'u1', size: 10, received: 0, complete: false, part_bytes: 4 }, () => {}, () => false),
    ).rejects.toThrow('A part is at most 4 bytes');
  });
});
