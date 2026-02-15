const API_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/+$/, '')

export interface JobResponse {
  job_id: string
  status: 'queued' | 'processing' | 'done' | 'error'
  progress_step: string | null
  error: string | null
  output_url: string | null
  edit_plan: Record<string, unknown> | null
  revisions: RevisionSummary[]
  created_at: string | null
  updated_at: string | null
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

async function handleResponse<T>(res: Response, operation: string): Promise<T> {
  if (!res.ok) {
    let detail = `${operation} failed (HTTP ${res.status})`
    try {
      const body = await res.json()
      if (body.detail) detail = body.detail
      else if (body.error) detail = body.error
    } catch {
      try {
        const text = await res.text()
        if (text) detail = `${operation} failed (HTTP ${res.status}): ${text.slice(0, 200)}`
      } catch {
        // use default
      }
    }
    throw new Error(detail)
  }
  return res.json()
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

  return handleResponse(res, 'Upload')
}

export async function getJob(jobId: string): Promise<JobResponse> {
  const res = await fetch(`${API_URL}/api/jobs/${jobId}`)
  return handleResponse(res, 'Fetch job')
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
  return handleResponse(res, 'Create edit')
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
  return handleResponse(res, 'Fetch revision')
}

export async function getPresets(): Promise<Preset[]> {
  const res = await fetch(`${API_URL}/api/presets`)
  return handleResponse(res, 'Fetch presets')
}

export function getFileUrl(path: string): string {
  if (path.startsWith('http')) return path
  // Avoid double-prefixing: if path already starts with /api/, just prepend base URL
  if (path.startsWith('/api/')) return `${API_URL}${path}`
  if (path.startsWith('/')) return `${API_URL}${path}`
  return `${API_URL}/${path}`
}
