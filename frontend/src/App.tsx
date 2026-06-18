import { useState } from 'react'
import { useStore } from './useStore'
import { SessionView } from './SessionView'
import { ProviderFilter } from './ProviderFilter'
import type { SessionState } from './types'

const ALL_PROVIDERS = ['claude-code', 'codex-cli', 'opencode']

function Section({
  title,
  count,
  defaultOpen,
  children,
}: {
  title: string
  count: number
  defaultOpen: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section>
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 py-1 focus:outline-none group"
      >
        <span className="font-mono text-xs uppercase tracking-widest text-zinc-500 group-hover:text-zinc-300 transition-colors">
          {title}
        </span>
        <span className="font-mono text-xs text-zinc-600 group-hover:text-zinc-400 transition-colors">
          ({count})
        </span>
        <span className="font-mono text-xs text-zinc-600 group-hover:text-zinc-400 transition-colors ml-auto">
          {open ? '▲' : '▼'}
        </span>
      </button>
      {open && children}
    </section>
  )
}

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
  if ((s.provider ?? '').toLowerCase().includes(lq)) return true
  return Object.values(s.agents).some(
    (a) =>
      (a.description?.toLowerCase().includes(lq) ?? false) ||
      (a.last_text?.toLowerCase().includes(lq) ?? false)
  )
}

export default function App() {
  const { sessions, status } = useStore()
  const [query, setQuery] = useState('')
  const [selectedProviders, setSelectedProviders] = useState<string[]>(ALL_PROVIDERS)

  const sorted = Object.values(sessions)
    .filter((s) => s.cwd && s.last_activity_ts)
    .filter((s) => selectedProviders.includes(s.provider ?? 'claude-code'))
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
        <span className="font-mono font-bold text-zinc-100 text-sm">agentperiscope</span>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="search sessions…"
          className="ml-4 flex-1 max-w-xs bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs font-mono text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
        />
        <ProviderFilter selected={selectedProviders} onChange={setSelectedProviders} />
        <span className={`font-mono text-xs ml-auto ${STATUS_CLS[status]}`}>
          {STATUS_LABEL[status]}
        </span>
        <span className="text-xs text-zinc-500">
          {sorted.length} session{sorted.length !== 1 ? 's' : ''}
        </span>
      </header>

      <main className="p-4 space-y-2">
        <Section title="Active" count={running.length} defaultOpen={true}>
          {running.length === 0 ? (
            <div className="py-6 text-center text-zinc-600 font-mono text-xs">
              {query ? 'No active sessions match.' : 'No active sessions.'}
            </div>
          ) : (
            <div className="space-y-3 pt-2">
              {running.map((s) => <SessionView key={s.id} session={s} />)}
            </div>
          )}
        </Section>

        {done.length > 0 && (
          <Section title="History" count={done.length} defaultOpen={false}>
            <div className="space-y-3 pt-2">
              {done.map((s) => <SessionView key={s.id} session={s} />)}
            </div>
          </Section>
        )}
      </main>
    </div>
  )
}
