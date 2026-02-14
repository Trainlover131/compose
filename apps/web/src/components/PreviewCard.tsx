'use client'

import { getFileUrl } from '@/lib/api'
import { useRef, useState } from 'react'

interface PreviewCardProps {
  file: File | null
  outputUrl: string | null
  duration: number | null
}

export function PreviewCard({ file, outputUrl, duration }: PreviewCardProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [isPlaying, setIsPlaying] = useState(false)

  const videoSrc = outputUrl
    ? getFileUrl(outputUrl)
    : file
    ? URL.createObjectURL(file)
    : null

  const togglePlay = () => {
    if (!videoRef.current) return
    if (isPlaying) {
      videoRef.current.pause()
    } else {
      videoRef.current.play()
    }
    setIsPlaying(!isPlaying)
  }

  return (
    <div className="relative w-full aspect-[9/16] max-h-[400px] rounded-glass-lg overflow-hidden bg-surface-raised border border-glass-border mx-auto">
      {videoSrc ? (
        <>
          <video
            ref={videoRef}
            src={videoSrc}
            className="w-full h-full object-cover"
            playsInline
            onEnded={() => setIsPlaying(false)}
          />
          <button
            onClick={togglePlay}
            className="absolute inset-0 flex items-center justify-center bg-black/20 hover:bg-black/30 transition-colors"
          >
            {!isPlaying && (
              <div className="w-12 h-12 rounded-full bg-white/20 backdrop-blur-sm flex items-center justify-center">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" className="text-white ml-1">
                  <polygon points="5 3 19 12 5 21 5 3" />
                </svg>
              </div>
            )}
          </button>
          {duration && (
            <div className="absolute top-3 right-3 px-2 py-1 rounded-full bg-black/60 backdrop-blur-sm text-xs text-white/80">
              {Math.round(duration)}s
            </div>
          )}
        </>
      ) : (
        <div className="w-full h-full flex flex-col items-center justify-center gap-3">
          <div className="w-16 h-16 rounded-2xl bg-glass-bg border border-glass-border flex items-center justify-center">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-white/20">
              <path d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
          </div>
          <p className="text-sm text-white/20">Drop a clip to preview</p>
        </div>
      )}
    </div>
  )
}
