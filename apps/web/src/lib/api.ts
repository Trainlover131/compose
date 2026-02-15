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

// ---------------------------------------------------------------------------
// Upload helpers
// ---------------------------------------------------------------------------

/** Upload a File to an R2 presigned PUT URL with progress reporting. */
function uploadToR2(
  url: string,
  file: File,
  contentType: string,
  onProgress?: (pct: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', url)
    xhr.setRequestHeader('Content-Type', contentType)

    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          onProgress(Math.round((e.loaded / e.total) * 100))
        }
      }
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve()
      else reject(new Error(`Upload to storage failed (HTTP ${xhr.status})`))
    }
    xhr.onerror = () => reject(new Error('Upload to storage failed: network error'))
    xhr.send(file)
  })
}

/** Request a presigned PUT URL from the API. Returns null if R2 not configured (501). */
async function requestPresign(
  filename: string,
  contentType: string,
): Promise<{ file_key: string; upload_url: string } | null> {
  const res = await fetch(`${API_URL}/api/uploads/presign`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename, content_type: contentType }),
  })

  if (res.status === 501) {
    // R2 not configured — caller should fall back to multipart
    return null
  }

  return handleResponse(res, 'Presign')
}

// ---------------------------------------------------------------------------
// Job creation (presigned-upload primary, multipart fallback)
// ---------------------------------------------------------------------------

export async function createJob(
  file: File,
  prompt: string,
  presetId: string,
  opts?: {
    durationSec?: number
    onProgress?: (pct: number) => void
  },
): Promise<{ job_id: string }> {
  const contentType = file.type || 'video/mp4'

  // Try presigned direct-to-R2 upload first
  let presign: { file_key: string; upload_url: string } | null = null
  try {
    presign = await requestPresign(file.name, contentType)
  } catch {
    // If presign request itself fails (network error), fall through to multipart
  }

  if (presign) {
    // Step 1 — upload file directly to R2 (browser ↔ R2, no Vercel proxy)
    await uploadToR2(presign.upload_url, file, contentType, opts?.onProgress)

    // Step 2 — create the job referencing the R2 key (tiny JSON POST)
    const res = await fetch(`${API_URL}/api/jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        file_key: presign.file_key,
        prompt,
        preset_id: presetId,
        duration_sec: opts?.durationSec ?? 0,
      }),
    })
    return handleResponse(res, 'Create job')
  }

  // Fallback — multipart upload through the API (local-storage / dev mode)
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

// ---------------------------------------------------------------------------
// Remaining API helpers (unchanged)
// ---------------------------------------------------------------------------

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
