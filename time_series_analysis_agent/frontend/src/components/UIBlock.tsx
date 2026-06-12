import Plot from 'react-plotly.js';
import ReactMarkdown from 'react-markdown';

export interface TextBlock {
  type: 'text';
  content: string;
}

export interface TableBlock {
  type: 'table';
  title: string;
  columns: string[];
  rows: (string | number)[][];
}

export interface PlotBlock {
  type: 'plot';
  title: string;
  library: 'plotly';
  spec: {
    data: any[];
    layout: any;
  };
}

export type Block = TextBlock | TableBlock | PlotBlock;

interface Props {
  block: Block;
}

export default function UIBlock({ block }: Props) {
  if (block.type === 'text') {
    return (
      <div className="prose prose-sm max-w-none">
        <ReactMarkdown
          components={{
            p: ({ children }) => (
              <p style={{ color: 'var(--text-body)', lineHeight: '1.75', marginBottom: '0.5rem' }}>{children}</p>
            ),
            h1: ({ children }) => (
              <h1 style={{ color: 'var(--text-main)', marginBottom: '0.5rem' }}>{children}</h1>
            ),
            h2: ({ children }) => (
              <h2 style={{ color: 'var(--text-main)', marginBottom: '0.5rem' }}>{children}</h2>
            ),
            h3: ({ children }) => (
              <h3 style={{ color: 'var(--text-main)', marginBottom: '0.5rem' }}>{children}</h3>
            ),
            h4: ({ children }) => (
              <h4 style={{ color: 'var(--text-main)', marginBottom: '0.5rem' }}>{children}</h4>
            ),
            strong: ({ children }) => (
              <strong style={{ color: 'var(--text-main)', fontWeight: 600 }}>{children}</strong>
            ),
            li: ({ children }) => (
              <li style={{ color: 'var(--text-body)', marginBottom: '0.25rem' }}>{children}</li>
            ),
            code: ({ children, className }) => {
              const isBlock = className?.includes('language-');
              if (isBlock) {
                return (
                  <code
                    className={className}
                    style={{
                      display: 'block',
                      background: 'var(--bg-surface)',
                      color: '#4ade80',
                      padding: '0.75rem 1rem',
                      borderRadius: '6px',
                      border: '0.5px solid var(--border)',
                      fontSize: '13px',
                      lineHeight: '1.7',
                      fontFamily: 'var(--font-mono, "JetBrains Mono", monospace)',
                      overflowX: 'auto',
                    }}
                  >
                    {children}
                  </code>
                );
              }
              return (
                <code
                  style={{
                    background: 'var(--bg-surface)',
                    color: '#4ade80',
                    padding: '1px 5px',
                    borderRadius: '4px',
                    fontSize: '12px',
                    fontFamily: '"JetBrains Mono", monospace',
                  }}
                >
                  {children}
                </code>
              );
            },
            pre: ({ children }) => (
              <pre
                style={{
                  background: 'var(--bg-surface)',
                  border: '0.5px solid var(--border)',
                  borderRadius: '6px',
                  padding: '0.75rem 1rem',
                  overflowX: 'auto',
                  marginBottom: '0.75rem',
                }}
              >
                {children}
              </pre>
            ),
          }}
        >
          {block.content}
        </ReactMarkdown>
      </div>
    );
  }

  if (block.type === 'table') {
    return (
      <div>
        {block.title && (
          <h4
            className="text-[13px] font-medium mb-2"
            style={{ color: 'var(--text-body)' }}
          >
            {block.title}
          </h4>
        )}
        <div
          className="overflow-x-auto rounded-xl overflow-hidden"
          style={{ border: '0.5px solid var(--border)' }}
        >
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr style={{ background: 'var(--bg-sidebar)', borderBottom: '0.5px solid var(--border)' }}>
                {block.columns.map((col, i) => (
                  <th
                    key={i}
                    className="px-4 py-2.5 text-left text-[12px] font-medium uppercase tracking-wider"
                    style={{ color: 'var(--text-secondary)' }}
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, i) => (
                <tr
                  key={i}
                  style={{ borderBottom: '0.5px solid rgba(46,46,46,0.5)' }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLElement).style.background = 'var(--bg-hover)';
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLElement).style.background = 'transparent';
                  }}
                >
                  {row.map((cell, j) => (
                    <td
                      key={j}
                      className="px-4 py-2.5 text-[14px]"
                      style={{ color: 'var(--text-main)' }}
                    >
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  if (block.type === 'plot' && block.library === 'plotly') {
    return (
      <div className="w-full">
        {block.title && (
          <h4
            className="text-[13px] font-medium mb-2"
            style={{ color: 'var(--text-body)' }}
          >
            {block.title}
          </h4>
        )}
        <div className="w-full px-1">
          <Plot
            data={block.spec.data}
            layout={{
              ...block.spec.layout,
              autosize: true,
              paper_bgcolor: 'transparent',
              plot_bgcolor: '#1a1a1a',
              font: {
                color: '#888888',
                family: 'Inter, system-ui, sans-serif',
                size: 12,
              },
              xaxis: {
                ...block.spec.layout?.xaxis,
                gridcolor: '#2e2e2e',
                linecolor: '#333333',
                tickfont: { color: '#888888' },
              },
              yaxis: {
                ...block.spec.layout?.yaxis,
                gridcolor: '#2e2e2e',
                linecolor: '#333333',
                tickfont: { color: '#888888' },
              },
              margin: { l: 50, r: 20, t: 40, b: 50 },
            }}
            config={{
              responsive: true,
              displayModeBar: true,
              displaylogo: false,
              modeBarButtonsToRemove: ['lasso2d', 'select2d'],
            }}
            useResizeHandler
            style={{ width: '100%', height: '420px' }}
            className="w-full"
          />
        </div>
      </div>
    );
  }

  return null;
}
