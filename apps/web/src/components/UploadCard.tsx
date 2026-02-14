'use client'

import { useCallback, useRef, useState } from 'react'

interface UploadCardProps {
  file: File | null
  onFileSelect: (file: File) => void
  duration: number | null
}

export function UploadCard({ file, onFileSelect, duration }: UploadCardProps) {
  const [isDragging, setIsDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setIsDragging(false)
      const f = e.dataTransfer.files[0]
      if (f && (f.type.startsWith('video/') || f.name.match(/\.(mp4|mov|webm|mkv)$/i))) {
        onFileSelect(f)
      }
    },
    [onFileSelect]
  )

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const f = e.target.files?.[0]
      if (f) onFileSelect(f)
    },
    [onFileSelect]
  )

  return (
    <div
      className={`
        relative border-2 border-dashed rounded-glass-lg p-6
        flex flex-col items-center justify-center gap-3
        transition-all duration-200 cursor-pointer min-h-[120px]
        ${isDragging
          ? 'border-accent/60 bg-accent/10'
          : file
          ? 'border-glass-border-light bg-glass-bg'
          : 'border-glass-border hover:border-white/20 bg-glass-bg hover:bg-glass-bg-hover'
        }
      `}
      onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
    >
      <input
        ref={inputRef}
        type="file"
        accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm,.mkv"
        className="hidden"
        onChange={handleChange}
      />

      {file ? (
        <div className="flex items-center gap-3 w-full">
          <div className="w-10 h-10 rounded-lg bg-accent/20 flex items-center justify-center flex-shrink-0">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-accent-light">
              <path d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm text-white/90 truncate">{file.name}</p>
            <p className="text-xs text-white/40">
              {(file.size / (1024 * 1024)).toFixed(1)} MB
              {duration ? ` \u00B7 ${Math.round(duration)}s` : ''}
            </p>
          </div>
          <button
            className="text-xs text-white/40 hover:text-white/70 transition-colors"
            onClick={(e) => { e.stopPropagation(); inputRef.current?.click() }}
          >
            Replace
          </button>
        </div>
      ) : (
        <>
          <div className="w-12 h-12 rounded-xl bg-glass-bg border border-glass-border flex items-center justify-center">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-white/40">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
          </div>
          <div className="text-center">
            <p className="text-sm font-medium text-white/70">Upload Video</p>
            <p className="text-xs text-white/30 mt-1">60-120s clips &middot; MP4/MOV</p>
          </div>
        </>
      )}
    </div>
  )
}
