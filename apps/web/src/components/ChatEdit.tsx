'use client'

import { useState } from 'react'

interface ChatEditProps {
  onSubmit: (instruction: string) => void
  disabled?: boolean
}

const EXAMPLE_CHIPS = [
  'Bigger captions',
  'Less b-roll',
  'Shorter',
  'Calmer music',
  'Remove zoom effects',
]

export function ChatEdit({ onSubmit, disabled }: ChatEditProps) {
  const [instruction, setInstruction] = useState('')

  const handleSubmit = () => {
    if (!instruction.trim() || disabled) return
    onSubmit(instruction.trim())
    setInstruction('')
  }

  return (
    <div className="space-y-3">
      <h3 className="text-xs font-medium text-white/40 uppercase tracking-wider">Make changes</h3>

      <div className="flex flex-wrap gap-1.5">
        {EXAMPLE_CHIPS.map((chip) => (
          <button
            key={chip}
            onClick={() => setInstruction(chip)}
            className="pill text-[11px] text-white/40 hover:text-white/60"
            disabled={disabled}
          >
            {chip}
          </button>
        ))}
      </div>

      <div className="flex gap-2">
        <input
          type="text"
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
          placeholder="Describe changes..."
          className="glass-input flex-1 text-sm h-10"
          disabled={disabled}
        />
        <button
          onClick={handleSubmit}
          disabled={disabled || !instruction.trim()}
          className="accent-button h-10 px-4 text-sm"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
      </div>
    </div>
  )
}
