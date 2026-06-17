import { useState } from 'react'
import { createPortal } from 'react-dom'
import type { AgentState, EventState } from './types'

const STATUS_COLOR: Record<string, string> = {
  running: 'border-blue-400 bg-blue-950/30',
  done: 'border-emerald-500 bg-emerald-950/20',
  error: 'border-red-500 bg-red-950/20',
}

const STATUS_DOT: Record<string, string> = {
  running: 'bg-blue-400 animate-pulse',
  done: 'bg-emerald-500',
  error: 'bg-red-500',
}

const KIND_COLOR: Record<string, string> = {
  text: 'text-zinc-300',
  tool_use: 'text-blue-300',
  tool_result: 'text-zinc-400',
  thinking: 'text-purple-300',
}

interface Props {
  agent: AgentState
  isRoot?: boolean
  sessionId: string
}

function fmtTs(ts: string): string {
  if (!ts) return ''
  try {
    return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ''
  }
}

function EventRow({ ev, wrap }: { ev: EventState; wrap?: boolean }) {
  const cls = KIND_COLOR[ev.kind] ?? 'text-zinc-400'
  const label = ev.kind === 'tool_use' ? `▶ ${ev.tool_name ?? ev.kind}` : ev.kind
  return (
    <div className={`flex gap-2 py-1 text-xs font-mono border-b border-zinc-800/60 last:border-0 ${wrap ? 'flex-wrap' : ''}`}>
      <span className="text-zinc-600 flex-shrink-0 w-20">{fmtTs(ev.ts)}</span>
      <span className={`flex-shrink-0 w-24 ${cls}`}>{label}</span>
      <span className={`text-zinc-400 ${wrap ? 'break-all' : 'truncate'} flex-1 min-w-0`}>{ev.summary ?? ''}</span>
    </div>
  )
}

function AgentModal({
  agent,
  isRoot,
  events,
  onClose,
}: {
  agent: AgentState
  isRoot?: boolean
  events: EventState[]
  onClose: () => void
}) {
  const dotCls = STATUS_DOT[agent.status] ?? 'bg-zinc-400'
  const tok = agent.tokens

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-3xl max-h-[85vh] flex flex-col rounded-xl border border-zinc-700 bg-zinc-900 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal header */}
        <div className="flex items-start gap-3 px-5 py-4 border-b border-zinc-800 flex-shrink-0">
          <span className={`mt-1 h-2.5 w-2.5 rounded-full flex-shrink-0 ${dotCls}`} />
          <div className="flex-1 min-w-0">
            <div className="font-mono font-semibold text-zinc-100 text-sm">
              {agent.agent_type ?? (isRoot ? 'root' : 'agent')}
            </div>
            {agent.description && (
              <div className="mt-0.5 text-xs text-zinc-400 font-mono">{agent.description}</div>
            )}
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs font-mono text-zinc-500">
              <span className="capitalize">{agent.status}</span>
              {agent.started_at && <span>started {fmtTs(agent.started_at)}</span>}
              {agent.ended_at && <span>ended {fmtTs(agent.ended_at)}</span>}
              {tok.input > 0 && <span>in {tok.input.toLocaleString()}</span>}
              {tok.output > 0 && <span>out {tok.output.toLocaleString()}</span>}
              {tok.cache_read > 0 && <span>cache↑ {tok.cache_read.toLocaleString()}</span>}
              {tok.cache_creation > 0 && <span>cache+ {tok.cache_creation.toLocaleString()}</span>}
            </div>
          </div>
          <button
            onClick={onClose}
            className="flex-shrink-0 text-zinc-500 hover:text-zinc-200 transition-colors text-lg leading-none mt-0.5 focus:outline-none"
          >
            ✕
          </button>
        </div>

        {/* Events list — scrollable */}
        <div className="flex-1 overflow-y-auto px-5 py-3">
          {events.length === 0 ? (
            <p className="text-xs text-zinc-600 font-mono py-4 text-center">no events recorded</p>
          ) : (
            <div>
              {events.map((ev) => <EventRow key={ev.id} ev={ev} wrap />)}
            </div>
          )}
        </div>

        <div className="px-5 py-2 border-t border-zinc-800 flex-shrink-0 text-xs text-zinc-600 font-mono">
          {events.length} event{events.length !== 1 ? 's' : ''}
        </div>
      </div>
    </div>,
    document.body,
  )
}

export function AgentCard({ agent, isRoot, sessionId }: Props) {
  const [expanded, setExpanded] = useState(false)
  const [events, setEvents] = useState<EventState[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)

  const borderCls = STATUS_COLOR[agent.status] ?? 'border-zinc-600 bg-zinc-900/20'
  const dotCls = STATUS_DOT[agent.status] ?? 'bg-zinc-400'

  async function fetchEvents() {
    if (events !== null) return
    setLoading(true)
    try {
      const res = await fetch(`/api/sessions/${sessionId}`)
      if (res.ok) {
        const data = await res.json()
        setEvents(data.agents?.[agent.id]?.events ?? [])
      }
    } finally {
      setLoading(false)
    }
  }

  async function toggleExpand() {
    if (!expanded) await fetchEvents()
    setExpanded((v) => !v)
  }

  async function openModal() {
    await fetchEvents()
    setModalOpen(true)
  }

  const tok = agent.tokens
  const hasTokenBreakdown = tok.input > 0 || tok.output > 0 || tok.cache_read > 0 || tok.cache_creation > 0

  return (
    <>
      <div className={`rounded-lg border ${borderCls} p-3 text-sm font-mono`}>
        {/* Header — click to expand */}
        <button
          onClick={toggleExpand}
          className="w-full text-left flex items-center gap-2 focus:outline-none"
        >
          <span className={`h-2 w-2 rounded-full flex-shrink-0 ${dotCls}`} />
          <span className="font-semibold text-zinc-100 truncate">
            {agent.agent_type ?? (isRoot ? 'root' : 'agent')}
          </span>
          {agent.current_tool && (
            <span className="ml-auto flex-shrink-0 rounded bg-blue-900/60 px-1.5 py-0.5 text-xs text-blue-300">
              {agent.current_tool}
            </span>
          )}
          <span className="ml-auto flex-shrink-0 text-zinc-600 text-xs">{expanded ? '▲' : '▼'}</span>
        </button>

        {/* Description */}
        {agent.description && (
          <p className="mt-1 text-xs text-zinc-400 truncate">{agent.description}</p>
        )}

        {/* Last text (collapsed only) */}
        {!expanded && agent.last_text && (
          <p className="mt-2 text-xs text-zinc-300 line-clamp-2 leading-relaxed">
            {agent.last_text}
          </p>
        )}

        {/* Token breakdown */}
        {hasTokenBreakdown ? (
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-zinc-500">
            {tok.input > 0 && <span>in {tok.input.toLocaleString()}</span>}
            {tok.output > 0 && <span>out {tok.output.toLocaleString()}</span>}
            {tok.cache_read > 0 && <span>cache↑ {tok.cache_read.toLocaleString()}</span>}
            {tok.cache_creation > 0 && <span>cache+ {tok.cache_creation.toLocaleString()}</span>}
            <span className="ml-auto capitalize">{agent.status}</span>
          </div>
        ) : (
          <div className="mt-2 flex items-center text-xs text-zinc-500">
            <span className="capitalize ml-auto">{agent.status}</span>
          </div>
        )}

        {/* Expanded events list */}
        {expanded && (
          <div className="mt-3 border-t border-zinc-700 pt-2">
            {loading && <p className="text-xs text-zinc-500">loading…</p>}
            {!loading && events && events.length === 0 && (
              <p className="text-xs text-zinc-600">no events recorded</p>
            )}
            {!loading && events && events.length > 0 && (
              <>
                <div className="max-h-48 overflow-y-auto">
                  {events.map((ev) => <EventRow key={ev.id} ev={ev} />)}
                </div>
                <button
                  onClick={openModal}
                  className="mt-2 w-full text-center text-xs text-zinc-500 hover:text-zinc-200 transition-colors font-mono py-1 border border-zinc-700 hover:border-zinc-500 rounded"
                >
                  ⤢ pop out
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {modalOpen && events && (
        <AgentModal
          agent={agent}
          isRoot={isRoot}
          events={events}
          onClose={() => setModalOpen(false)}
        />
      )}
    </>
  )
}
