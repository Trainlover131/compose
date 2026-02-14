'use client'

import { useState } from 'react'

interface PromptInputProps {
  value: string
  onChange: (value: string) => void
}

const SUGGESTION_CHIPS = [
  'Punchy',
  'Cinematic',
  'Remove filler words',
  'Add captions',
  'Less b-roll',
  'Luxury vibe',
]

export function PromptInput({ value, onChange }: PromptInputProps) {
  const [activeChips, setActiveChips] = useState<Set<string>>(new Set())

  const toggleChip = (chip: string) => {
    const next = new Set(activeChips)
    if (next.has(chip)) {
      next.delete(chip)
    } else {
      next.add(chip)
    }
    setActiveChips(next)

    // Append chip text to prompt
    const chipTexts = Array.from(next)
    const basePrompt = value.split(' | ')[0] || ''
    const newValue = chipTexts.length
      ? `${basePrompt} | ${chipTexts.join(', ')}`
      : basePrompt
    onChange(newValue.trim())
  }

  return (
    <div className="space-y-3">
      <div className="relative">
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Describe how you want this edited\u2026"
          className="glass-input w-full h-14 text-sm pr-16"
          maxLength={500}
        />
        <span className="absolute right-4 top-1/2 -translate-y-1/2 text-xs text-white/20">
          {value.length}/500
        </span>
      </div>

      <div className="flex flex-wrap gap-2">
        {SUGGESTION_CHIPS.map((chip) => (
          <button
            key={chip}
            onClick={() => toggleChip(chip)}
            className={`pill text-xs ${activeChips.has(chip) ? 'pill-selected' : 'text-white/50'}`}
          >
            {chip}
          </button>
        ))}
      </div>
    </div>
  )
}
