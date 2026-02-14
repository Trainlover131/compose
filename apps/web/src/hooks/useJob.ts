'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { getJob, getRevision, type JobResponse, type RevisionSummary } from '@/lib/api'

export function useJobPoller(jobId: string | null) {
  const [job, setJob] = useState<JobResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const intervalRef = useRef<NodeJS.Timeout | null>(null)

  const poll = useCallback(async () => {
    if (!jobId) return
    try {
      const data = await getJob(jobId)
      setJob(data)
      if (data.status === 'done' || data.status === 'error') {
        if (intervalRef.current) {
          clearInterval(intervalRef.current)
          intervalRef.current = null
        }
      }
    } catch (e) {
      console.error('Poll error:', e)
    }
  }, [jobId])

  useEffect(() => {
    if (!jobId) return

    setLoading(true)
    poll().finally(() => setLoading(false))

    intervalRef.current = setInterval(poll, 2000)

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
    }
  }, [jobId, poll])

  return { job, loading }
}

export function useRevisionPoller(
  jobId: string | null,
  revisionId: string | null,
  onComplete?: () => void
) {
  const [revision, setRevision] = useState<{
    revision_id: string
    revision_number: number
    status: string
    output_url: string | null
  } | null>(null)
  const intervalRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    if (!jobId || !revisionId) return

    const poll = async () => {
      try {
        const data = await getRevision(jobId, revisionId)
        setRevision(data)
        if (data.status === 'done' || data.status === 'error') {
          if (intervalRef.current) {
            clearInterval(intervalRef.current)
            intervalRef.current = null
          }
          onComplete?.()
        }
      } catch (e) {
        console.error('Revision poll error:', e)
      }
    }

    poll()
    intervalRef.current = setInterval(poll, 2000)

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
    }
  }, [jobId, revisionId, onComplete])

  return { revision }
}
