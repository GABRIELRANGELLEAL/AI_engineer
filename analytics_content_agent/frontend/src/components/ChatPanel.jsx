import { useEffect, useRef, useState } from 'react'

export default function ChatPanel({ messages, streaming, disabled, onSend }) {
  const [input, setInput] = useState('')
  const bottomRef = useRef(null)

  // Auto-scroll to bottom when messages update
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSubmit = (e) => {
    e.preventDefault()
    const text = input.trim()
    if (!text || disabled) return
    setInput('')
    onSend(text)
  }

  return (
    <>
      <div className="panel-header">Chat</div>

      <div className="chat-messages">
        {messages.length === 0 && (
          <p className="empty-state">
            Nenhuma mensagem ainda.<br />
            Digite abaixo para começar.
          </p>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`chat-bubble ${msg.role}`}>
            {msg.text}
          </div>
        ))}

        <div ref={bottomRef} />
      </div>

      {streaming && (
        <div className="typing-indicator">● Agente processando…</div>
      )}

      <form className="chat-input-row" onSubmit={handleSubmit}>
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder={disabled ? 'Aguardando aprovação da tool…' : 'Digite uma mensagem…'}
          disabled={disabled}
        />
        <button type="submit" className="btn-send" disabled={disabled || !input.trim()}>
          Enviar
        </button>
      </form>
    </>
  )
}
