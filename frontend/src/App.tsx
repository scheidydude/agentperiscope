import { useState } from 'react'
import { useStore } from './useStore'
import { SessionView } from './SessionView'
import type { SessionState } from './types'

const STATUS_LABEL: Record<string, string> = {
  connecting: '⟳ connecting…',
  connected: '● live',
  disconnected: '○ disconnected',
}

const STATUS_CLS: Record<string, string> = {
  connecting: 'text-zinc-400',
  connected: 'text-emerald-400',
  disconnected: 'text-red-400',
}

function matchesQuery(s: SessionState, q: string): boolean {
  const lq = q.toLowerCase()
  if (s.cwd.toLowerCase().includes(lq)) return true
  if (s.project_slug.toLowerCase().includes(lq)) return true
  return Object.values(s.agents).some(
    (a) =>
      (a.description?.toLowerCase().includes(lq) ?? false) ||
      (a.last_text?.toLowerCase().includes(lq) ?? false)
  )
}

export default function App() {
  const { sessions, status } = useStore()
  const [query, setQuery] = useState('')

  const sorted = Object.values(sessions)
    .filter((s) => s.cwd && s.last_activity_ts)
    .filter((s) => !query || matchesQuery(s, query))
    .sort((a, b) => b.last_activity_ts.localeCompare(a.last_activity_ts))

  const running = sorted.filter((s) =>
    Object.values(s.agents).some((a) => a.status === 'running')
  )
  const done = sorted.filter((s) =>
    Object.values(s.agents).every((a) => a.status !== 'running')
  )

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <header className="border-b border-zinc-800 px-4 py-2 flex items-center gap-3">
        <span className="font-mono font-bold text-zinc-100 text-sm">ccview</span>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="search sessions…"
          className="ml-4 flex-1 max-w-xs bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs font-mono text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
        />
        <span className={`font-mono text-xs ml-auto ${STATUS_CLS[status]}`}>
          {STATUS_LABEL[status]}
        </span>
        <span className="text-xs text-zinc-500">
          {sorted.length} session{sorted.length !== 1 ? 's' : ''}
        </span>
      </header>

      <main className="p-4 space-y-6">
        {running.length > 0 && (
          <section>
            <h2 className="font-mono text-xs uppercase tracking-widest text-zinc-500 mb-2">
              Active
            </h2>
            <div className="space-y-3">
              {running.map((s) => <SessionView key={s.id} session={s} />)}
            </div>
          </section>
        )}

        {done.length > 0 && (
          <section>
            <h2 className="font-mono text-xs uppercase tracking-widest text-zinc-500 mb-2">
              History
            </h2>
            <div className="space-y-3">
              {done.map((s) => <SessionView key={s.id} session={s} />)}
            </div>
          </section>
        )}

        {sorted.length === 0 && status === 'connected' && (
          <div className="text-center py-24 text-zinc-500 font-mono text-sm">
            {query ? 'No sessions match.' : 'No sessions yet. Start a Claude Code session to see activity.'}
          </div>
        )}
      </main>
    </div>
  )
}
