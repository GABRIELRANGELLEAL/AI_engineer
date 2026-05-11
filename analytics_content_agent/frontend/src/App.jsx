import { useState, useCallback, useRef } from 'react'
import DataSourcePicker from './components/DataSourcePicker'
import ChatPanel from './components/ChatPanel'
import ActivityPanel from './components/ActivityPanel'
import PlotsPanel from './components/PlotsPanel'
import './App.css'

export default function App() {
  const [sessionId, setSessionId] = useState(null)
  const [messages, setMessages]       = useState([])   // { role, text }[]
  const [activityLog, setActivityLog] = useState([])   // { id, name, input, status }[]
  const [pendingTool, setPendingTool] = useState(null) // { id, name, input } | null
  const [plots, setPlots]             = useState([])   // { filename, url }[]
  const [streaming, setStreaming]     = useState(false)

  // Keep a ref so SSE onmessage closure always sees current pendingTool id
  const pendingIdRef = useRef(null)

  const fetchPlots = useCallback(async () => {
    try {
      const res = await fetch('/outputs')
      const data = await res.json()
      setPlots(data.files || [])
    } catch (_) {}
  }, [])

  const handleSessionCreated = useCallback((sid) => {
    setSessionId(sid)
  }, [])

  const handleSendMessage = useCallback((text) => {
    if (!sessionId || streaming) return

    setMessages(prev => [...prev, { role: 'user', text }])
    setStreaming(true)

    const url = `/session/${sessionId}/stream?message=${encodeURIComponent(text)}`
    const es = new EventSource(url)

    es.onmessage = (e) => {
      let event
      try { event = JSON.parse(e.data) } catch { return }

      switch (event.type) {
        case 'text':
          setMessages(prev => [...prev, { role: 'assistant', text: event.content }])
          break

        case 'tool_call':
          pendingIdRef.current = event.id
          setPendingTool({ id: event.id, name: event.name, input: event.input })
          setActivityLog(prev => [
            ...prev,
            { id: event.id, name: event.name, input: event.input, status: 'waiting' },
          ])
          break

        case 'tool_result':
          setActivityLog(prev =>
            prev.map(t => t.id === event.id ? { ...t, status: 'aprovado' } : t)
          )
          setPendingTool(null)
          pendingIdRef.current = null
          break

        case 'tool_denied':
          setActivityLog(prev =>
            prev.map(t => t.id === event.id ? { ...t, status: 'negado' } : t)
          )
          setPendingTool(null)
          pendingIdRef.current = null
          break

        case 'done':
          setStreaming(false)
          fetchPlots()
          es.close()
          break

        case 'error':
          setMessages(prev => [
            ...prev,
            { role: 'assistant', text: `⚠️ Erro: ${event.message}` },
          ])
          setStreaming(false)
          setPendingTool(null)
          es.close()
          break
      }
    }

    es.onerror = () => {
      setStreaming(false)
      setPendingTool(null)
      es.close()
    }
  }, [sessionId, streaming, fetchPlots])

  const handleAuthorize = useCallback(async (approved) => {
    if (!sessionId || !pendingTool) return
    await fetch(`/session/${sessionId}/authorize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approved }),
    })
  }, [sessionId, pendingTool])

  if (!sessionId) {
    return <DataSourcePicker onSessionCreated={handleSessionCreated} />
  }

  return (
    <div className="layout">
      <header className="topbar">
        <span className="topbar-title">Analytics Content Agent</span>
        <span className="topbar-badge">{streaming ? '● streaming…' : '○ idle'}</span>
      </header>

      <div className="main-grid">
        <section className="col-chat">
          <ChatPanel
            messages={messages}
            streaming={streaming}
            disabled={!!pendingTool || streaming}
            onSend={handleSendMessage}
          />
        </section>

        <section className="col-right">
          <div className="right-top">
            <ActivityPanel
              activityLog={activityLog}
              pendingTool={pendingTool}
              onAuthorize={handleAuthorize}
            />
          </div>
          <div className="right-bottom">
            <PlotsPanel plots={plots} onRefresh={fetchPlots} />
          </div>
        </section>
      </div>
    </div>
  )
}
