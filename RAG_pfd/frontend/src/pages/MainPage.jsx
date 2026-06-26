import { useState, useRef, useEffect } from 'react'

function getHeaders(apiConfig) {
  const headers = {}
  if (apiConfig.openaiKey) headers['X-OpenAI-Key'] = apiConfig.openaiKey
  if (apiConfig.anthropicKey) headers['X-Anthropic-Key'] = apiConfig.anthropicKey
  return headers
}

export default function MainPage({ apiConfig, onBack }) {
  const [documents, setDocuments] = useState([])
  const [uploading, setUploading] = useState(false)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [asking, setAsking] = useState(false)
  const chatEndRef = useRef(null)

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function handleUpload(e) {
    const files = e.target.files
    if (!files?.length) return

    setUploading(true)
    const formData = new FormData()
    for (const f of files) formData.append('files', f)

    try {
      const res = await fetch('/documents', {
        method: 'POST',
        headers: getHeaders(apiConfig),
        body: formData,
      })
      const data = await res.json()
      if (res.ok) {
        setDocuments((prev) => [...prev, ...data.details])
      } else {
        alert(data.detail || 'Upload failed')
      }
    } catch {
      alert('Could not connect to server')
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  async function handleAsk(e) {
    e.preventDefault()
    if (!input.trim() || asking) return

    const question = input.trim()
    setInput('')
    setMessages((prev) => [...prev, { role: 'user', text: question }])
    setAsking(true)

    try {
      const res = await fetch('/question', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getHeaders(apiConfig) },
        body: JSON.stringify({ question }),
      })
      const data = await res.json()
      if (res.ok) {
        setMessages((prev) => [...prev, { role: 'assistant', data }])
      } else {
        setMessages((prev) => [...prev, { role: 'error', text: data.detail || 'Error' }])
      }
    } catch {
      setMessages((prev) => [...prev, { role: 'error', text: 'Could not connect to server' }])
    } finally {
      setAsking(false)
    }
  }

  return (
    <div className="h-screen flex bg-gray-50">
      {/* Sidebar */}
      <div className="w-72 bg-white border-r border-gray-200 flex flex-col">
        <div className="p-4 border-b border-gray-200">
          <button onClick={onBack} className="text-xs text-gray-400 hover:text-gray-600 mb-3 block">
            &larr; Change API key
          </button>
          <h2 className="font-semibold text-gray-900 text-sm">Documents</h2>
        </div>

        <div className="p-4">
          <label className={`block w-full p-4 border-2 border-dashed border-gray-300 rounded-lg text-center cursor-pointer hover:border-blue-400 hover:bg-blue-50 transition ${uploading ? 'opacity-50 pointer-events-none' : ''}`}>
            <input type="file" accept=".pdf" multiple onChange={handleUpload} className="hidden" />
            <span className="text-sm text-gray-500">
              {uploading ? 'Processing...' : 'Click to upload PDFs'}
            </span>
          </label>
        </div>

        <div className="flex-1 overflow-y-auto px-4 space-y-2">
          {documents.map((doc, i) => (
            <div key={i} className="p-3 bg-gray-50 rounded-lg">
              <p className="text-sm font-medium text-gray-900 truncate">{doc.filename}</p>
              <p className="text-xs text-gray-500">{doc.pages} pages, {doc.chunks} chunks</p>
            </div>
          ))}
        </div>
      </div>

      {/* Chat */}
      <div className="flex-1 flex flex-col">
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {messages.length === 0 && documents.length === 0 && (
            <div className="h-full flex items-center justify-center">
              <p className="text-gray-400 text-sm">Upload a PDF to get started</p>
            </div>
          )}
          {messages.length === 0 && documents.length > 0 && (
            <div className="h-full flex items-center justify-center">
              <p className="text-gray-400 text-sm">Ask a question about your documents</p>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i}>
              {msg.role === 'user' && (
                <div className="flex justify-end">
                  <div className="bg-blue-600 text-white px-4 py-2 rounded-lg max-w-lg text-sm">
                    {msg.text}
                  </div>
                </div>
              )}
              {msg.role === 'assistant' && (
                <div className="bg-white border border-gray-200 rounded-lg p-4 max-w-2xl">
                  <p className="text-sm text-gray-900 whitespace-pre-wrap">{msg.data.answer}</p>

                  <div className="flex gap-3 mt-3 text-xs text-gray-400">
                    <span className={
                      msg.data.metadata.confidence === 'high' ? 'text-green-600' :
                      msg.data.metadata.confidence === 'medium' ? 'text-yellow-600' : 'text-red-500'
                    }>
                      {msg.data.metadata.confidence} confidence
                    </span>
                    <span>{msg.data.metadata.model}</span>
                    <span>{(msg.data.metadata.total_time_ms / 1000).toFixed(1)}s</span>
                  </div>

                  {msg.data.references.length > 0 && (
                    <details className="mt-3">
                      <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-600">
                        {msg.data.references.length} reference(s)
                      </summary>
                      <div className="mt-2 space-y-2">
                        {msg.data.references.map((ref, j) => (
                          <div key={j} className="bg-gray-50 rounded p-3 text-xs">
                            <p className="text-gray-600 line-clamp-3">{ref.text}</p>
                            <p className="text-gray-400 mt-1">
                              {ref.document}, p.{ref.page}
                              {ref.similarity_score != null && ` (${(ref.similarity_score * 100).toFixed(0)}%)`}
                            </p>
                          </div>
                        ))}
                      </div>
                    </details>
                  )}
                </div>
              )}
              {msg.role === 'error' && (
                <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-2 max-w-lg text-sm text-red-700">
                  {msg.text}
                </div>
              )}
            </div>
          ))}

          {asking && (
            <div className="bg-white border border-gray-200 rounded-lg p-4 max-w-2xl animate-pulse">
              <div className="h-4 bg-gray-200 rounded w-3/4"></div>
              <div className="h-4 bg-gray-200 rounded w-1/2 mt-2"></div>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>

        <form onSubmit={handleAsk} className="p-4 border-t border-gray-200 bg-white">
          <div className="flex gap-2 max-w-3xl mx-auto">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask a question about your documents..."
              disabled={asking}
              className="flex-1 border border-gray-300 rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={!input.trim() || asking}
              className="px-6 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Send
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
