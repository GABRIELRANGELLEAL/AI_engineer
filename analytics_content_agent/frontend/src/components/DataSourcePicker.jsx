import { useState, useRef } from 'react'

const MODEL_OPTIONS = [
  { value: 'claude-sonnet-4-5-20250929', label: 'Claude Sonnet 4.5' },
  { value: 'claude-haiku-4-5-20251001',  label: 'Claude Haiku 4.5 (mais rápido)' },
]

export default function DataSourcePicker({ onSessionCreated }) {
  const [file, setFile]         = useState(null)
  const [model, setModel]       = useState(MODEL_OPTIONS[0].value)
  const [dragOver, setDragOver] = useState(false)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState(null)
  const inputRef = useRef(null)

  const handleDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    const dropped = e.dataTransfer.files[0]
    if (dropped && dropped.name.endsWith('.csv')) setFile(dropped)
  }

  const handleFileChange = (e) => {
    const selected = e.target.files[0]
    if (selected) setFile(selected)
  }

  const handleSubmit = async () => {
    if (!file) return
    setError(null)
    setLoading(true)

    try {
      // 1. Upload CSV
      const form = new FormData()
      form.append('file', file)
      const upRes = await fetch('/upload-csv', { method: 'POST', body: form })
      if (!upRes.ok) throw new Error(`Upload falhou: ${upRes.statusText}`)
      const upData = await upRes.json()

      // 2. Create session
      const sessRes = await fetch('/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ csv_name: upData.filename, model }),
      })
      if (!sessRes.ok) throw new Error(`Sessão falhou: ${sessRes.statusText}`)
      const sessData = await sessRes.json()

      onSessionCreated(sessData.session_id, upData.filename)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="datasource-page">
      <div className="datasource-card">
        <div>
          <h1>Analytics Content Agent</h1>
          <p style={{ marginTop: '0.4rem' }}>
            Envie um arquivo CSV para começar. O agente irá analisá-lo e gerar insights.
          </p>
        </div>

        {/* Drop zone */}
        <label
          className={`drop-zone${dragOver ? ' drag-over' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".csv"
            onChange={handleFileChange}
          />
          {file
            ? <span>📄 {file.name}</span>
            : <span>Arraste um CSV aqui ou <u>clique para selecionar</u></span>
          }
        </label>

        {file && (
          <div className="file-selected">
            ✓ {file.name} ({(file.size / 1024).toFixed(1)} KB)
          </div>
        )}

        {/* Model selector */}
        <div>
          <label style={{ fontSize: '0.82rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.4rem' }}>
            Modelo
          </label>
          <select
            value={model}
            onChange={e => setModel(e.target.value)}
            style={{
              width: '100%',
              background: 'var(--surface2)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text)',
              padding: '0.55rem 0.8rem',
              fontSize: '0.875rem',
              outline: 'none',
            }}
          >
            {MODEL_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        {error && <div className="error-msg">⚠ {error}</div>}

        <button
          className="btn-primary"
          onClick={handleSubmit}
          disabled={!file || loading}
        >
          {loading ? 'Carregando…' : 'Iniciar análise →'}
        </button>
      </div>
    </div>
  )
}
