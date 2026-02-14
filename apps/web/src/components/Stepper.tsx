'use client'

interface StepperProps {
  currentStep: string | null
  status: string
}

const STEPS = [
  { key: 'uploading', label: 'Uploading' },
  { key: 'transcribing', label: 'Transcribing' },
  { key: 'planning', label: 'Planning' },
  { key: 'fetching_broll', label: 'Fetching b-roll' },
  { key: 'rendering', label: 'Rendering' },
  { key: 'done', label: 'Done' },
]

export function Stepper({ currentStep, status }: StepperProps) {
  if (!currentStep && status === 'queued') {
    return (
      <div className="flex items-center justify-center gap-2 py-3">
        <div className="w-4 h-4 border-2 border-accent/40 border-t-accent rounded-full animate-spin" />
        <span className="text-sm text-white/50">Queued...</span>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="flex items-center justify-center gap-2 py-3">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-red-400">
          <circle cx="12" cy="12" r="10" />
          <line x1="15" y1="9" x2="9" y2="15" />
          <line x1="9" y1="9" x2="15" y2="15" />
        </svg>
        <span className="text-sm text-red-400">Processing failed</span>
      </div>
    )
  }

  const currentIdx = STEPS.findIndex((s) => s.key === currentStep)

  return (
    <div className="flex items-center justify-center gap-1 py-3">
      {STEPS.map((step, i) => {
        const isActive = step.key === currentStep
        const isDone = i < currentIdx || status === 'done'
        const isFuture = i > currentIdx && status !== 'done'

        return (
          <div key={step.key} className="flex items-center gap-1">
            {i > 0 && (
              <div className={`w-4 h-px ${isDone ? 'bg-accent/50' : 'bg-white/10'}`} />
            )}
            <span
              className={`text-xs whitespace-nowrap transition-colors ${
                isActive
                  ? 'text-accent-light font-medium'
                  : isDone
                  ? 'text-white/50'
                  : 'text-white/20'
              }`}
            >
              {step.label}
            </span>
            {isActive && status !== 'done' && (
              <div className="w-3 h-3 border-2 border-accent/40 border-t-accent rounded-full animate-spin ml-0.5" />
            )}
          </div>
        )
      })}
    </div>
  )
}
