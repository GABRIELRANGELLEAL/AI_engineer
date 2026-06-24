import { useState } from 'react'

export default function SetupPage({ onComplete }) {
  const [key, setKey] = useState('')
  const [status, setStatus] = useState(null) // null | 'loading' | 'valid' | 'error'
  const [errorMsg, setErrorMsg] = useState('')

  async function handleTest() {
    if (!key.trim()) return
    setStatus('loading')
    setErrorMsg('')

    try {
      const res = await fetch('/validate-keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ openai_key: key }),
      })
      const data = await res.json()
      const result = data.openai

      if (result?.valid) {
        setStatus('valid')
      } else {
        setStatus('error')
        setErrorMsg(result?.message || 'Validation failed')
      }
    } catch {
      setStatus('error')
      setErrorMsg('Could not connect to server')
    }
  }

  function handleContinue() {
    onComplete({ openaiKey: key, anthropicKey: null })
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-lg shadow-lg p-8 w-full max-w-md">
        <h1 className="text-2xl font-bold text-gray-900 mb-2">RAG PDF Q&A</h1>
        <p className="text-gray-500 text-sm mb-8">Upload PDFs and ask questions about their content</p>

        <label className="block text-sm font-medium text-gray-700 mb-2">
          OpenAI API Key
        </label>
        <p className="text-xs text-gray-400 mb-3">Used for embeddings (text-embedding-3-small) and answers (gpt-4o-mini)</p>
        <div className="flex gap-2">
          <input
            type="password"
            value={key}
            onChange={(e) => { setKey(e.target.value); setStatus(null) }}
            placeholder="sk-..."
            className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
          />
          <button
            onClick={handleTest}
            disabled={!key.trim() || status === 'loading'}
            className="px-4 py-2 bg-gray-900 text-white text-sm rounded-lg hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {status === 'loading' ? '...' : 'Test'}
          </button>
        </div>

        {status === 'valid' && (
          <p className="text-green-600 text-sm mt-2">Valid key</p>
        )}
        {status === 'error' && (
          <p className="text-red-600 text-sm mt-2">{errorMsg}</p>
        )}

        <button
          onClick={handleContinue}
          disabled={status !== 'valid'}
          className="w-full mt-6 py-3 bg-green-600 text-white font-medium rounded-lg hover:bg-green-700 disabled:opacity-40 disabled:cursor-not-allowed transition"
        >
          Get Started
        </button>
      </div>
    </div>
  )
}
