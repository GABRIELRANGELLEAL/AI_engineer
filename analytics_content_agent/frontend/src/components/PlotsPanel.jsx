const IMAGE_EXTS = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'])

function isImage(filename) {
  const ext = filename.slice(filename.lastIndexOf('.')).toLowerCase()
  return IMAGE_EXTS.has(ext)
}

export default function PlotsPanel({ plots, onRefresh }) {
  const images = plots.filter(p => isImage(p.filename))
  const others = plots.filter(p => !isImage(p.filename))

  return (
    <div className="plots-col">
      <div className="panel-header">
        <div className="plots-header-row">
          <span>Resultados / Plots</span>
          <button className="btn-refresh" onClick={onRefresh} title="Atualizar">
            ↺ Atualizar
          </button>
        </div>
      </div>

      <div className="panel-body">
        {plots.length === 0 && (
          <p className="empty-state">
            Nenhum resultado ainda.<br />
            Gráficos e arquivos gerados pelo agente aparecerão aqui.
          </p>
        )}

        {images.length > 0 && (
          <div className="plots-grid">
            {images.map(p => (
              <div key={p.filename} className="plot-item">
                <img src={p.url} alt={p.filename} loading="lazy" />
                <div className="plot-caption">
                  <span>{p.filename}</span>
                  <a href={p.url} download={p.filename}>⬇ baixar</a>
                </div>
              </div>
            ))}
          </div>
        )}

        {others.length > 0 && (
          <div style={{ marginTop: images.length ? '1rem' : 0 }}>
            <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: '0.5rem' }}>
              Outros arquivos
            </p>
            <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
              {others.map(p => (
                <li key={p.filename}>
                  <a
                    href={p.url}
                    download={p.filename}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.4rem',
                      fontSize: '0.85rem',
                      color: 'var(--accent)',
                      textDecoration: 'none',
                      padding: '0.4rem 0.6rem',
                      background: 'var(--surface2)',
                      borderRadius: 'var(--radius-sm)',
                      border: '1px solid var(--border)',
                    }}
                  >
                    📄 {p.filename}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}
