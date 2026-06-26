import { useState } from 'react'

export default function SetupPage({ onComplete }) {
  const [key, setKey] = useState('')
  const [anthropicKey, setAnthropicKey] = useState('')
  const [loading, setLoading] = useState(false)
  const [errors, setErrors] = useState({})

  async function handleGetStarted() {
    if (!key.trim()) return
    setLoading(true)
    setErrors({})

    const body = { openai_key: key }
    if (anthropicKey.trim()) body.anthropic_key = anthropicKey

    try {
      const res = await fetch('/validate-keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json()
      const newErrors = {}

      if (!data.openai?.valid) {
        newErrors.openai = data.openai?.message || 'Invalid OpenAI key'
      }
      if (anthropicKey.trim() && !data.anthropic?.valid) {
        newErrors.anthropic = data.anthropic?.message || 'Invalid Anthropic key'
      }

      if (Object.keys(newErrors).length > 0) {
        setErrors(newErrors)
        setLoading(false)
        return
      }

      onComplete({ openaiKey: key, anthropicKey: anthropicKey || null })
    } catch {
      setErrors({ openai: 'Could not connect to server' })
      setLoading(false)
    }
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
        <input
          type="password"
          value={key}
          onChange={(e) => { setKey(e.target.value); setErrors((prev) => ({ ...prev, openai: undefined })) }}
          placeholder="sk-..."
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
        />
        {errors.openai && (
          <p className="text-red-600 text-sm mt-2">{errors.openai}</p>
        )}

        <div className="border-t border-gray-200 mt-6 pt-6">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Anthropic API Key <span className="text-gray-400 font-normal">(opcional)</span>
          </label>
          <p className="text-xs text-gray-400 mb-3">Usado como fallback caso a OpenAI falhe</p>
          <input
            type="password"
            value={anthropicKey}
            onChange={(e) => { setAnthropicKey(e.target.value); setErrors((prev) => ({ ...prev, anthropic: undefined })) }}
            placeholder="sk-ant-..."
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
          />
          {errors.anthropic && (
            <p className="text-red-600 text-sm mt-2">{errors.anthropic}</p>
          )}
        </div>

        <button
          onClick={handleGetStarted}
          disabled={!key.trim() || loading}
          className="w-full mt-6 py-3 bg-green-600 text-white font-medium rounded-lg hover:bg-green-700 disabled:opacity-40 disabled:cursor-not-allowed transition"
        >
          {loading ? 'Validating...' : 'Get Started'}
        </button>
      </div>
    </div>
  )
}
