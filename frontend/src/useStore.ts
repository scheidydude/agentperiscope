import { useEffect, useRef, useState } from 'react'
import type { Sessions, WsMessage } from './types'

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected'

export function useStore() {
  const [sessions, setSessions] = useState<Sessions>({})
  const [status, setStatus] = useState<ConnectionStatus>('connecting')
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    function connect() {
      const ws = new WebSocket(`ws://${window.location.host}/ws`)
      wsRef.current = ws
      setStatus('connecting')

      ws.onopen = () => setStatus('connected')

      ws.onclose = () => {
        setStatus('disconnected')
        reconnectTimer.current = setTimeout(connect, 2000)
      }

      ws.onmessage = (e) => {
        const msg: WsMessage = JSON.parse(e.data)
        setSessions((prev) => applyMessage(prev, msg))
      }
    }

    connect()
    return () => {
      wsRef.current?.close()
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
    }
  }, [])

  return { sessions, status }
}

function applyMessage(sessions: Sessions, msg: WsMessage): Sessions {
  switch (msg.type) {
    case 'snapshot':
      return msg.data.sessions

    case 'session_start':
    case 'session_update':
      return { ...sessions, [msg.session.id]: msg.session }

    case 'agent_start':
    case 'agent_update': {
      const sess = sessions[msg.session_id]
      if (!sess) return sessions
      return {
        ...sessions,
        [msg.session_id]: {
          ...sess,
          agents: { ...sess.agents, [msg.agent.id]: msg.agent },
        },
      }
    }

    default:
      return sessions
  }
}
