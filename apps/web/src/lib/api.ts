const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export interface JobResponse {
  job_id: string
  status: 'queued' | 'processing' | 'done' | 'error'
  progress_step: string | null
  error: string | null
  output_url: string | null
  edit_plan: Record<string, unknown> | null
  revisions: RevisionSummary[]
  created_at: string | null
}

export interface RevisionSummary {
  revision_id: string
  revision_number: number
  status: string
  output_url: string | null
  instruction: string | null
}

export interface Preset {
  id: string
  name: string
  description: string
  config: Record<string, unknown>
}

export async function createJob(
  file: File,
  prompt: string,
  presetId: string
): Promise<{ job_id: string }> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('prompt', prompt)
  formData.append('preset_id', presetId)

  const res = await fetch(`${API_URL}/api/jobs`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Upload failed' }))
    throw new Error(err.detail || 'Upload failed')
  }

  return res.json()
}

export async function getJob(jobId: string): Promise<JobResponse> {
  const res = await fetch(`${API_URL}/api/jobs/${jobId}`)
  if (!res.ok) throw new Error('Failed to fetch job')
  return res.json()
}

export async function createEdit(
  jobId: string,
  instruction: string
): Promise<{ revision_id: string; status: string }> {
  const res = await fetch(`${API_URL}/api/jobs/${jobId}/edits`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ instruction }),
  })
  if (!res.ok) throw new Error('Failed to create edit')
  return res.json()
}

export async function getRevision(
  jobId: string,
  revisionId: string
): Promise<{
  revision_id: string
  revision_number: number
  status: string
  output_url: string | null
}> {
  const res = await fetch(`${API_URL}/api/jobs/${jobId}/edits/${revisionId}`)
  if (!res.ok) throw new Error('Failed to fetch revision')
  return res.json()
}

export async function getPresets(): Promise<Preset[]> {
  const res = await fetch(`${API_URL}/api/presets`)
  if (!res.ok) throw new Error('Failed to fetch presets')
  return res.json()
}

export function getFileUrl(path: string): string {
  if (path.startsWith('http')) return path
  return `${API_URL}${path}`
}
