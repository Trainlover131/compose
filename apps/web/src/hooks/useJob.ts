'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { getJob, getRevision, type JobResponse, type RevisionSummary } from '@/lib/api'

// Stop polling after 20 minutes to prevent infinite loops
const POLL_TIMEOUT_MS = 20 * 60 * 1000
const POLL_INTERVAL_MS = 2000

export function useJobPoller(jobId: string | null) {
  const [job, setJob] = useState<JobResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [pollError, setPollError] = useState<string | null>(null)
  const [timedOut, setTimedOut] = useState(false)
  const intervalRef = useRef<NodeJS.Timeout | null>(null)
  const timeoutRef = useRef<NodeJS.Timeout | null>(null)
  const startTimeRef = useRef<number | null>(null)

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }
  }, [])

  const poll = useCallback(async () => {
    if (!jobId) return
    try {
      const data = await getJob(jobId)
      setJob(data)
      setPollError(null)
      if (data.status === 'done' || data.status === 'error') {
        stopPolling()
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Failed to fetch job status'
      setPollError(msg)
      console.error('Poll error:', msg)
    }
  }, [jobId, stopPolling])

  useEffect(() => {
    if (!jobId) return

    // Reset state for new job
    setJob(null)
    setPollError(null)
    setTimedOut(false)
    startTimeRef.current = Date.now()

    setLoading(true)
    poll().finally(() => setLoading(false))

    intervalRef.current = setInterval(poll, POLL_INTERVAL_MS)

    // Client-side timeout: stop polling after 10 minutes
    timeoutRef.current = setTimeout(() => {
      stopPolling()
      setTimedOut(true)
    }, POLL_TIMEOUT_MS)

    return () => {
      stopPolling()
    }
  }, [jobId, poll, stopPolling])

  return { job, loading, pollError, timedOut }
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
  const timeoutRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    if (!jobId || !revisionId) return

    const stopPolling = () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
        timeoutRef.current = null
      }
    }

    const poll = async () => {
      try {
        const data = await getRevision(jobId, revisionId)
        setRevision(data)
        if (data.status === 'done' || data.status === 'error') {
          stopPolling()
          onComplete?.()
        }
      } catch (e) {
        console.error('Revision poll error:', e)
      }
    }

    poll()
    intervalRef.current = setInterval(poll, POLL_INTERVAL_MS)

    // Client-side timeout for revisions too
    timeoutRef.current = setTimeout(() => {
      stopPolling()
    }, POLL_TIMEOUT_MS)

    return () => {
      stopPolling()
    }
  }, [jobId, revisionId, onComplete])

  return { revision }
}
