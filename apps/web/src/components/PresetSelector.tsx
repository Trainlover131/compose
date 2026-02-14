'use client'

interface Preset {
  id: string
  name: string
  description: string
}

interface PresetSelectorProps {
  presets: Preset[]
  selected: string
  onSelect: (id: string) => void
}

export function PresetSelector({ presets, selected, onSelect }: PresetSelectorProps) {
  return (
    <div className="space-y-2">
      <label className="text-xs font-medium text-white/40 uppercase tracking-wider">Style Preset</label>
      <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-hide">
        {presets.map((preset) => (
          <button
            key={preset.id}
            onClick={() => onSelect(preset.id)}
            className={`
              pill whitespace-nowrap text-xs
              ${selected === preset.id ? 'pill-selected' : 'text-white/50'}
            `}
            title={preset.description}
          >
            {preset.name}
          </button>
        ))}
      </div>
    </div>
  )
}
