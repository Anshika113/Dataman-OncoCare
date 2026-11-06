import { useEffect, useRef, useState, useCallback } from 'react'
import { clearSession, getToken } from './api'

// Live connection to the backend WebSocket. The socket is authenticated with
// the stored JWT (sent as the first message). Pushes a full state snapshot on
// connect, re-fetches state on every change broadcast, and re-syncs on a
// light heartbeat. Reconnects with exponential backoff + jitter.
export function useRealtime() {
  const [state, setState] = useState<any>(null)
  const [connected, setConnected] = useState(false)
  const [events, setEvents] = useState<any[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const attemptRef = useRef(0)
  // Monotonic id for /api/state fetches. A mutation broadcasts twice (its own
  // event + state_refresh) and the heartbeat fires on top of that, so several
  // requests are often in flight; without this, a slow older response could
  // land last and briefly revert the UI to stale data.
  const seqRef = useRef(0)

  const pushEvent = useCallback((e: any) => {
    setEvents((prev) => [e, ...prev].slice(0, 60))
  }, [])

  // re-pull the full state from the API (authoritative)
  const refresh = useCallback(() => {
    const token = getToken()
    if (!token) return
    const seq = ++seqRef.current
    fetch('/api/state', { headers: { Authorization: 'Bearer ' + token } })
      .then((r) => {
        // an expired token never recovers on its own; without this the app
        // waits on "Connecting to department…" forever
        if (r.status === 401) { clearSession(); window.location.href = '/login' }
        return r.ok ? r.json() : Promise.reject(r.status)
      })
      .then((s) => { if (seq === seqRef.current) setState(s) })
      .catch(() => {})
  }, [])

  useEffect(() => {
    let closed = false
    let reconnect: any
    let ws: WebSocket | null = null

    const connect = () => {
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const url = `${proto}://${window.location.host}/ws`
      const socket = new WebSocket(url)
      ws = socket
      wsRef.current = socket
      socket.onopen = () => {
        attemptRef.current = 0
        setConnected(true)
        const token = getToken()
        // authenticate the socket; the server closes it (1008) if invalid
        socket.send(token || '')
      }
      socket.onmessage = (msg) => {
        let data: any
        try { data = JSON.parse(msg.data) } catch { return }
        if (data.type === 'snapshot') {
          if (data.state) setState(data.state)
          else refresh()
        } else if (data.type === 'state_refresh') {
          refresh()
        } else {
          pushEvent({ ...data, at: new Date().toLocaleTimeString() })
          if (data.type && data.type !== 'pong') refresh()
        }
      }
      socket.onclose = (e) => {
        setConnected(false)
        if (closed) return
        // 1008 = unauthorized: stop retrying (the app handles re-login)
        if (e.code === 1008) return
        const delay = Math.min(15000, 1000 * 2 ** attemptRef.current)
        attemptRef.current += 1
        reconnect = setTimeout(connect, delay + Math.random() * 500)
      }
      socket.onerror = () => socket.close()
    }

    // initial load + connect
    refresh()
    connect()

    // heartbeat re-sync (safety net so the dashboard is never stale)
    const beat = setInterval(() => { if (!closed) refresh() }, 8000)

    return () => {
      closed = true
      clearInterval(beat)
      if (reconnect) clearTimeout(reconnect)
      ws?.close()
    }
  }, [pushEvent, refresh])

  return { state, connected, events, refresh }
}
