const PROVIDERS = [
  { id: 'claude-code', label: 'Claude Code' },
  { id: 'codex-cli', label: 'Codex' },
  { id: 'opencode', label: 'OpenCode' },
]

interface Props {
  selected: string[]
  onChange: (selected: string[]) => void
}

export function ProviderFilter({ selected, onChange }: Props) {
  function toggle(id: string) {
    if (selected.includes(id)) {
      const next = selected.filter((s) => s !== id)
      onChange(next.length === 0 ? PROVIDERS.map((p) => p.id) : next)
    } else {
      onChange([...selected, id])
    }
  }

  return (
    <div className="flex items-center gap-2">
      {PROVIDERS.map(({ id, label }) => {
        const active = selected.includes(id)
        return (
          <button
            key={id}
            onClick={() => toggle(id)}
            className={`px-2 py-0.5 rounded text-xs font-mono border transition-colors ${
              active
                ? 'border-zinc-500 text-zinc-200 bg-zinc-700/50'
                : 'border-zinc-700 text-zinc-600 bg-transparent hover:border-zinc-600 hover:text-zinc-400'
            }`}
          >
            {label}
          </button>
        )
      })}
    </div>
  )
}
