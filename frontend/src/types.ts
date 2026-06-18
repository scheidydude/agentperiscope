export interface TokenCounts {
  input: number
  output: number
  cache_creation: number
  cache_read: number
  total: number
}

export interface EventState {
  id: string
  agent_id: string
  ts: string
  kind: 'text' | 'tool_use' | 'tool_result' | 'thinking' | 'usage' | 'system'
  tool_name: string | null
  summary: string | null
  tokens_in: number | null
  tokens_out: number | null
}

export interface AgentState {
  id: string
  session_id: string
  parent_agent_id: string | null
  agent_type: string | null
  description: string | null
  status: 'running' | 'done' | 'error'
  started_at: string
  ended_at: string | null
  current_tool: string | null
  last_text: string | null
  tokens: TokenCounts
  child_ids: string[]
  events?: EventState[]
  provider: string
}

export interface SessionState {
  id: string
  cwd: string
  project_slug: string
  model: string | null
  started_at: string
  status: string
  root_agent_id: string
  last_activity_ts: string
  agents: Record<string, AgentState>
  provider: string
}

export type Sessions = Record<string, SessionState>

// WebSocket message shapes
export type WsMessage =
  | { type: 'snapshot'; data: { sessions: Sessions } }
  | { type: 'session_start'; session: SessionState }
  | { type: 'session_update'; session: SessionState }
  | { type: 'agent_start'; session_id: string; agent: AgentState }
  | { type: 'agent_update'; session_id: string; agent: AgentState }
  | { type: 'event'; session_id: string; agent_id: string; event: unknown }
  | { type: 'hook'; payload: unknown }
