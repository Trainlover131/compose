'use client'

import type { RevisionSummary } from '@/lib/api'

interface RevisionListProps {
  revisions: RevisionSummary[]
  selectedId: string | null
  originalOutputUrl: string | null
  onSelect: (revision: RevisionSummary | null) => void
}

export function RevisionList({
  revisions,
  selectedId,
  originalOutputUrl,
  onSelect,
}: RevisionListProps) {
  return (
    <div className="space-y-2">
      <h3 className="text-xs font-medium text-white/40 uppercase tracking-wider">Revisions</h3>
      <div className="space-y-1.5">
        {/* Original */}
        <button
          onClick={() => onSelect(null)}
          className={`
            w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-left transition-all
            ${!selectedId ? 'bg-accent/10 border border-accent/30' : 'bg-glass-bg border border-transparent hover:bg-glass-bg-hover'}
          `}
        >
          <div className="w-6 h-6 rounded-md bg-glass-bg border border-glass-border flex items-center justify-center text-xs text-white/60">
            v1
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-xs text-white/70 truncate">Original edit</p>
          </div>
          {originalOutputUrl && (
            <div className="w-2 h-2 rounded-full bg-green-400/60" title="Ready" />
          )}
        </button>

        {/* Revisions */}
        {revisions.map((rev) => (
          <button
            key={rev.revision_id}
            onClick={() => onSelect(rev)}
            className={`
              w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-left transition-all
              ${selectedId === rev.revision_id
                ? 'bg-accent/10 border border-accent/30'
                : 'bg-glass-bg border border-transparent hover:bg-glass-bg-hover'
              }
            `}
          >
            <div className="w-6 h-6 rounded-md bg-glass-bg border border-glass-border flex items-center justify-center text-xs text-white/60">
              v{rev.revision_number + 1}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs text-white/70 truncate">
                {rev.instruction || `Revision ${rev.revision_number}`}
              </p>
              <p className="text-[10px] text-white/30 capitalize">{rev.status}</p>
            </div>
            {rev.status === 'done' && (
              <div className="w-2 h-2 rounded-full bg-green-400/60" title="Ready" />
            )}
            {rev.status === 'queued' || rev.status === 'processing' ? (
              <div className="w-3 h-3 border border-accent/40 border-t-accent rounded-full animate-spin" />
            ) : null}
          </button>
        ))}
      </div>
    </div>
  )
}
