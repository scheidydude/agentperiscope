import type { SessionState } from './types'
import { AgentCard } from './AgentCard'
import { ProviderBadge } from './ProviderBadge'

interface Props {
  session: SessionState
}

function shortId(id: string) {
  return id.slice(0, 8)
}

function shortCwd(cwd: string) {
  const parts = cwd.replace(/\\/g, '/').split('/')
  return parts.slice(-2).join('/')
}

function fmtSessionTs(ts: string): string {
  if (!ts) return ''
  try {
    const d = new Date(ts)
    if (isNaN(d.getTime())) return ''
    const now = new Date()
    const isToday = d.toDateString() === now.toDateString()
    const isThisYear = d.getFullYear() === now.getFullYear()
    const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    if (isToday) return time
    const date = d.toLocaleDateString([], { month: 'short', day: 'numeric', ...(!isThisYear && { year: 'numeric' }) })
    return `${date} · ${time}`
  } catch {
    return ''
  }
}

export function SessionView({ session }: Props) {
  const rootAgent = session.agents[session.root_agent_id]
  const subagents = Object.values(session.agents).filter(
    (a) => a.id !== session.root_agent_id
  )
  const hasRunning = Object.values(session.agents).some((a) => a.status === 'running')
  const ts = fmtSessionTs(session.last_activity_ts)

  return (
    <div className="rounded-xl border border-zinc-700 bg-zinc-900 p-4">
      {/* Session header */}
      <div className="flex items-center gap-2 mb-3">
        <span className={`h-2 w-2 rounded-full flex-shrink-0 ${hasRunning ? 'bg-blue-400 animate-pulse' : 'bg-zinc-600'}`} />
        <span className="font-mono text-sm font-semibold text-zinc-200 truncate">
          {shortCwd(session.cwd)}
        </span>
        <div className="ml-auto flex items-center gap-2 flex-shrink-0">
          <ProviderBadge provider={session.provider ?? 'claude-code'} />
          {ts && (
            <span className="font-mono text-xs text-zinc-400">{ts}</span>
          )}
          <span className="font-mono text-xs text-zinc-600" title={session.id}>
            {shortId(session.id)}
          </span>
          {session.model && (
            <span className="text-xs text-zinc-500">{session.model}</span>
          )}
        </div>
      </div>

      {/* Agent lane grid */}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-2">
        {rootAgent && <AgentCard agent={rootAgent} isRoot sessionId={session.id} />}
        {subagents.map((agent) => (
          <AgentCard key={agent.id} agent={agent} sessionId={session.id} />
        ))}
      </div>
    </div>
  )
}
