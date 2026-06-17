import type { AgentState } from './types'

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

interface Props {
  agent: AgentState
  isRoot?: boolean
}

export function AgentCard({ agent, isRoot }: Props) {
  const borderCls = STATUS_COLOR[agent.status] ?? 'border-zinc-600 bg-zinc-900/20'
  const dotCls = STATUS_DOT[agent.status] ?? 'bg-zinc-400'

  return (
    <div className={`rounded-lg border ${borderCls} p-3 text-sm font-mono`}>
      {/* Header */}
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full flex-shrink-0 ${dotCls}`} />
        <span className="font-semibold text-zinc-100 truncate">
          {agent.agent_type ?? (isRoot ? 'root' : 'agent')}
        </span>
        {agent.current_tool && (
          <span className="ml-auto flex-shrink-0 rounded bg-blue-900/60 px-1.5 py-0.5 text-xs text-blue-300">
            {agent.current_tool}
          </span>
        )}
      </div>

      {/* Description */}
      {agent.description && (
        <p className="mt-1 text-xs text-zinc-400 truncate">{agent.description}</p>
      )}

      {/* Last text */}
      {agent.last_text && (
        <p className="mt-2 text-xs text-zinc-300 line-clamp-2 leading-relaxed">
          {agent.last_text}
        </p>
      )}

      {/* Footer: tokens + status */}
      <div className="mt-2 flex items-center gap-3 text-xs text-zinc-500">
        {agent.tokens.total > 0 && (
          <span>{agent.tokens.total.toLocaleString()} tok</span>
        )}
        <span className="capitalize ml-auto">{agent.status}</span>
      </div>
    </div>
  )
}
