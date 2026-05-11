import { useState } from 'react'

function ActivityItem({ item }) {
  const [open, setOpen] = useState(false)

  const icon = { aprovado: '✅', negado: '❌', waiting: '⏳' }[item.status] ?? '•'

  return (
    <li className="activity-item">
      <div className="activity-item-header" onClick={() => setOpen(o => !o)}>
        <span>{icon}</span>
        <span className="activity-tool-name">{item.name}</span>
        <span className={`status-badge ${item.status}`}>{item.status}</span>
        <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
          {open ? '▲' : '▼'}
        </span>
      </div>
      {open && (
        <div className="activity-item-body">
          <pre>{JSON.stringify(item.input, null, 2)}</pre>
        </div>
      )}
    </li>
  )
}

export default function ActivityPanel({ activityLog, pendingTool, onAuthorize }) {
  const handleApprove = () => onAuthorize(true)
  const handleDeny    = () => onAuthorize(false)

  return (
    <div className="activity-col">
      <div className="panel-header">Atividade</div>

      <div className="panel-body">
        {activityLog.length === 0 && !pendingTool && (
          <p className="empty-state">Nenhuma atividade ainda.</p>
        )}

        {activityLog.length > 0 && (
          <ul className="activity-log">
            {activityLog.map((item, i) => (
              <ActivityItem key={item.id ?? i} item={item} />
            ))}
          </ul>
        )}

        {pendingTool && (
          <div className="pending-tool-card">
            <h4>⚠ Aguardando aprovação</h4>
            <div className="tool-name">{pendingTool.name}</div>
            <pre>{JSON.stringify(pendingTool.input, null, 2)}</pre>
            <div className="auth-buttons">
              <button className="btn-approve" onClick={handleApprove}>
                ✅ Aprovar
              </button>
              <button className="btn-deny" onClick={handleDeny}>
                ❌ Negar
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
