const PROVIDER_LABELS: Record<string, string> = {
  'claude-code': 'Claude Code',
  'codex-cli': 'Codex',
  'opencode': 'OpenCode',
}

const PROVIDER_CLS: Record<string, string> = {
  'claude-code': 'bg-orange-900/50 text-orange-300 border-orange-700/50',
  'codex-cli': 'bg-green-900/50 text-green-300 border-green-700/50',
  'opencode': 'bg-sky-900/50 text-sky-300 border-sky-700/50',
}

interface Props {
  provider: string
}

export function ProviderBadge({ provider }: Props) {
  const label = PROVIDER_LABELS[provider] ?? provider
  const cls = PROVIDER_CLS[provider] ?? 'bg-zinc-800 text-zinc-400 border-zinc-700'
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-mono border ${cls}`}>
      {label}
    </span>
  )
}
