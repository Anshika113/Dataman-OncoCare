import { useEffect, useRef, useState, useCallback } from 'react'
import { BASE_URL } from './api'

// Live connection to the backend WebSocket. Pushes a full state snapshot on
// connect, re-fetches state on every change broadcast, AND re-syncs on a
// light heartbeat so the dashboard can never show stale data even if a
// broadcast is missed.
export function useRealtime() {
  const [state, setState] = useState<any>(null)
  const [connected, setConnected] = useState(false)
  const [events, setEvents] = useState<any[]>([])
  const wsRef = useRef<WebSocket | null>(null)

  const pushEvent = useCallback((e: any) => {
    setEvents((prev) => [e, ...prev].slice(0, 60))
  }, [])

  // re-pull the full state from the API (authoritative)
  const refresh = useCallback(() => {
    const token = localStorage.getItem('care_token')
    fetch(BASE_URL + '/api/state', { headers: { Authorization: 'Bearer ' + (token || '') } })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((s) => setState(s))
      .catch(() => {})
  }, [])

  useEffect(() => {
    let closed = false
    let reconnect: any

    const connect = () => {
      let wsBase = BASE_URL || `${window.location.protocol}//${window.location.host}`
      wsBase = wsBase.replace(/^http/, 'ws')
      const url = `${wsBase}/ws`
      const ws = new WebSocket(url)
      wsRef.current = ws
      ws.onopen = () => setConnected(true)
      ws.onmessage = (msg) => {
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
      ws.onclose = () => {
        setConnected(false)
        if (!closed) reconnect = setTimeout(connect, 2000)
      }
      ws.onerror = () => ws.close()
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
      wsRef.current?.close()
    }
  }, [pushEvent, refresh])

  return { state, connected, events, refresh }
}
