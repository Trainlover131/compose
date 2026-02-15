'use client'

import { useCallback, useEffect, useState } from 'react'
import { TopBar } from '@/components/TopBar'
import { GlassPanel } from '@/components/GlassPanel'
import { UploadCard } from '@/components/UploadCard'
import { PreviewCard } from '@/components/PreviewCard'
import { PromptInput } from '@/components/PromptInput'
import { PresetSelector } from '@/components/PresetSelector'
import { Stepper } from '@/components/Stepper'
import { RevisionList } from '@/components/RevisionList'
import { ChatEdit } from '@/components/ChatEdit'
import { useJobPoller } from '@/hooks/useJob'
import {
  createJob,
  createEdit,
  getFileUrl,
  getPresets,
  type Preset,
  type RevisionSummary,
} from '@/lib/api'

const DEFAULT_PRESETS: Preset[] = [
  { id: 'snappy-creator', name: 'Snappy Creator', description: 'Fast cuts, energetic', config: {} },
  { id: 'cinematic-doc', name: 'Cinematic Doc', description: 'Slower, subtle', config: {} },
  { id: 'podcast-clipper', name: 'Podcast Clipper', description: 'Clean, focused', config: {} },
  { id: 'luxury-real-estate', name: 'Luxury Real Estate', description: 'Elegant, smooth', config: {} },
  { id: 'study-explainer', name: 'Study / Explainer', description: 'Structured, readable', config: {} },
]

export default function Home() {
  // State
  const [file, setFile] = useState<File | null>(null)
  const [duration, setDuration] = useState<number | null>(null)
  const [prompt, setPrompt] = useState('')
  const [presetId, setPresetId] = useState('snappy-creator')
  const [presets, setPresets] = useState<Preset[]>(DEFAULT_PRESETS)
  const [jobId, setJobId] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedRevision, setSelectedRevision] = useState<RevisionSummary | null>(null)
  const [editLoading, setEditLoading] = useState(false)

  const { job, pollError, timedOut } = useJobPoller(jobId)

  // Load presets
  useEffect(() => {
    getPresets().then(setPresets).catch(() => {})
  }, [])

  // Get video duration when file selected
  const handleFileSelect = useCallback((f: File) => {
    setFile(f)
    setError(null)
    const video = document.createElement('video')
    video.preload = 'metadata'
    video.onloadedmetadata = () => {
      setDuration(video.duration)
      URL.revokeObjectURL(video.src)
    }
    video.src = URL.createObjectURL(f)
  }, [])

  // Submit job
  const handleGenerate = async () => {
    if (!file) return
    setIsSubmitting(true)
    setError(null)
    setSelectedRevision(null)

    try {
      const result = await createJob(
        file,
        prompt || 'Make this into an engaging short-form video',
        presetId
      )
      setJobId(result.job_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setIsSubmitting(false)
    }
  }

  // Submit edit
  const handleEdit = async (instruction: string) => {
    if (!jobId) return
    setEditLoading(true)
    try {
      await createEdit(jobId, instruction)
      // The poller will pick up the new revision
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Edit failed')
    } finally {
      setEditLoading(false)
    }
  }

  // Determine current output URL
  const currentOutputUrl = selectedRevision?.output_url || job?.output_url || null

  const isJobActive =
    job?.status === 'queued' || job?.status === 'processing'
  const isJobDone = job?.status === 'done'
  const isJobError = job?.status === 'error'

  // Compute the visible error message (prioritize: timeout > job error > poll error > local error)
  const displayError = timedOut
    ? 'Timed out waiting for server response. Check server logs or try again.'
    : job?.error || pollError || error || null

  return (
    <div className="min-h-screen flex flex-col">
      <TopBar />

      {/* Hero */}
      <div className="text-center pt-4 pb-8 px-5">
        <h1 className="text-3xl md:text-4xl font-semibold tracking-tight-heading text-white/90">
          Create short-form videos in seconds.
        </h1>
        <p className="text-sm text-white/40 mt-2">
          Upload a clip. Describe the vibe. Export.
        </p>
      </div>

      {/* Main content */}
      <main className="flex-1 max-w-[1200px] mx-auto w-full px-5 md:px-8 pb-12">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left: Create Panel */}
          <div className="lg:col-span-8">
            <GlassPanel className="space-y-6">
              {/* Upload */}
              <UploadCard
                file={file}
                onFileSelect={handleFileSelect}
                duration={duration}
              />

              {/* Preview */}
              <div className="flex justify-center">
                <div className="w-full max-w-[240px]">
                  <PreviewCard
                    file={file}
                    outputUrl={isJobDone ? currentOutputUrl : null}
                    duration={duration}
                  />
                </div>
              </div>

              {/* Prompt */}
              <PromptInput value={prompt} onChange={setPrompt} />

              {/* Presets */}
              <PresetSelector
                presets={presets}
                selected={presetId}
                onSelect={setPresetId}
              />

              {/* Generate button */}
              <div className="flex flex-col items-center gap-3">
                <button
                  onClick={handleGenerate}
                  disabled={!file || isSubmitting || isJobActive}
                  className="accent-button w-full max-w-xs h-12 text-sm font-medium flex items-center justify-center gap-2"
                >
                  {isSubmitting || isJobActive ? (
                    <>
                      <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      {isSubmitting ? 'Uploading...' : 'Processing...'}
                    </>
                  ) : (
                    'Generate'
                  )}
                </button>

                {/* Progress stepper */}
                {(isJobActive || isJobDone || isJobError) && job && (
                  <Stepper
                    currentStep={job.progress_step}
                    status={job.status}
                  />
                )}

                {/* Error display */}
                {displayError && (
                  <div className="w-full max-w-sm rounded-lg bg-red-500/10 border border-red-500/20 px-4 py-3">
                    <p className="text-xs text-red-400 text-center break-words">
                      {displayError}
                    </p>
                  </div>
                )}
              </div>

              {/* Disclaimer */}
              <p className="text-[10px] text-white/20 text-center">
                Stock assets used via Pexels; verify licensing for commercial use.
              </p>
            </GlassPanel>
          </div>

          {/* Right: Edit Result Panel */}
          <div className="lg:col-span-4">
            <GlassPanel className="space-y-6">
              <h2 className="text-sm font-medium text-white/60 tracking-tight-heading">
                Edit Result
              </h2>

              {/* Result preview */}
              {isJobDone && currentOutputUrl ? (
                <div className="space-y-3">
                  <div className="relative w-full aspect-[9/16] max-h-[280px] rounded-glass-lg overflow-hidden bg-surface-raised border border-glass-border">
                    <video
                      src={getFileUrl(currentOutputUrl)}
                      className="w-full h-full object-cover"
                      controls
                      playsInline
                    />
                  </div>
                  <a
                    href={getFileUrl(currentOutputUrl)}
                    download
                    className="accent-button w-full h-10 text-sm flex items-center justify-center gap-2"
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                      <polyline points="7 10 12 15 17 10" />
                      <line x1="12" y1="15" x2="12" y2="3" />
                    </svg>
                    Download MP4
                  </a>
                </div>
              ) : isJobActive ? (
                <div className="flex flex-col items-center justify-center py-12 gap-3">
                  <div className="w-10 h-10 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
                  <p className="text-xs text-white/40">Processing video...</p>
                </div>
              ) : isJobError ? (
                <div className="flex flex-col items-center justify-center py-12 gap-3">
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-red-400">
                    <circle cx="12" cy="12" r="10" />
                    <line x1="15" y1="9" x2="9" y2="15" />
                    <line x1="9" y1="9" x2="15" y2="15" />
                  </svg>
                  <p className="text-xs text-red-400 text-center px-4">
                    {job?.error || 'Processing failed'}
                  </p>
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-12 gap-3">
                  <div className="w-12 h-12 rounded-xl bg-glass-bg border border-glass-border flex items-center justify-center">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-white/15">
                      <rect x="2" y="2" width="20" height="20" rx="5" />
                      <polygon points="10 8 16 12 10 16 10 8" />
                    </svg>
                  </div>
                  <p className="text-xs text-white/20">Result will appear here</p>
                </div>
              )}

              {/* Divider */}
              {isJobDone && <div className="border-t border-glass-border" />}

              {/* Revisions */}
              {isJobDone && job && (
                <RevisionList
                  revisions={job.revisions}
                  selectedId={selectedRevision?.revision_id || null}
                  originalOutputUrl={job.output_url}
                  onSelect={setSelectedRevision}
                />
              )}

              {/* Divider */}
              {isJobDone && <div className="border-t border-glass-border" />}

              {/* Chat edits */}
              {isJobDone && (
                <ChatEdit
                  onSubmit={handleEdit}
                  disabled={editLoading}
                />
              )}
            </GlassPanel>
          </div>
        </div>
      </main>
    </div>
  )
}
