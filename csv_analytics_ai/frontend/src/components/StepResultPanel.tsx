import { useState, useEffect } from 'react';
import { CheckCircle2, XCircle, Loader2, ChevronDown } from 'lucide-react';
import UIBlock, { Block } from './UIBlock';

interface StepResult {
  stepNumber: number;
  description: string;
  summary: string;
  status: 'completed' | 'error';
  generatedFiles: string[];
  artifacts: string[];
}

interface UIPayload {
  step_number: number;
  title: string;
  blocks: Block[];
}

interface Props {
  stepResult: StepResult;
  taskId: string;
}

export default function StepResultPanel({ stepResult }: Props) {
  const [uiPayload, setUiPayload] = useState<UIPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isExpanded, setIsExpanded] = useState(true);

  useEffect(() => {
    const uiFilePath = stepResult.generatedFiles.find((f) => f.includes('_ui.json'));

    if (uiFilePath) {
      setLoading(true);
      setError(null);

      fetch(`/api/workspace/files/${encodeURIComponent(uiFilePath)}`)
        .then((r) => {
          if (!r.ok) {
            throw new Error(`Failed to load: ${r.statusText}`);
          }
          return r.json();
        })
        .then((data) => setUiPayload(data))
        .catch((err) => {
          console.error('Failed to load UI payload:', err);
          setError('Failed to load visualization data');
        })
        .finally(() => setLoading(false));
    }
  }, [stepResult.generatedFiles]);

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ border: '0.5px solid var(--border)' }}
    >
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between px-4 py-3 transition-colors"
        style={{ background: 'var(--bg-sidebar)' }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLElement).style.background = 'var(--bg-surface)';
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLElement).style.background = 'var(--bg-sidebar)';
        }}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          {stepResult.status === 'completed' ? (
            <CheckCircle2 className="w-4 h-4 flex-shrink-0" style={{ color: '#4ade80' }} />
          ) : (
            <XCircle className="w-4 h-4 flex-shrink-0" style={{ color: '#f87171' }} />
          )}
          <span className="text-[14px] font-medium truncate" style={{ color: 'var(--text-main)' }}>
            Step {stepResult.stepNumber} — {stepResult.description}
          </span>
        </div>
        <ChevronDown
          className="w-4 h-4 flex-shrink-0 ml-3 transition-transform duration-200"
          style={{
            color: 'var(--text-secondary)',
            transform: isExpanded ? 'rotate(0deg)' : 'rotate(-90deg)',
          }}
        />
      </button>

      {/* Body */}
      {isExpanded && (
        <div
          className="p-4"
          style={{
            background: 'var(--bg-page)',
            borderTop: '0.5px solid var(--border)',
          }}
        >
          {/* Summary */}
          {stepResult.summary && (
            <p
              className="text-[13px] leading-relaxed mb-4"
              style={{ color: 'var(--text-secondary)' }}
            >
              {stepResult.summary}
            </p>
          )}

          {/* Loading */}
          {loading && (
            <div
              className="flex items-center gap-2 py-6 justify-center"
              style={{ color: 'var(--text-muted)' }}
            >
              <Loader2 className="w-4 h-4 animate-spin" />
              <span className="text-[13px]">Loading results...</span>
            </div>
          )}

          {/* Error */}
          {error && (
            <div
              className="text-[12px] px-3 py-2 rounded-lg"
              style={{
                color: '#f87171',
                border: '0.5px solid #7f1d1d',
                background: 'rgba(127,29,29,0.15)',
              }}
            >
              {error}
            </div>
          )}

          {/* UI Blocks */}
          {uiPayload?.blocks && (
            <div className="space-y-5">
              {uiPayload.title && (
                <p
                  className="text-[11px] uppercase tracking-wider"
                  style={{ color: 'var(--text-muted)' }}
                >
                  {uiPayload.title}
                </p>
              )}
              {uiPayload.blocks.map((block, i) => (
                <UIBlock key={i} block={block} />
              ))}
            </div>
          )}

          {/* Fallback file list */}
          {!loading && !uiPayload && !error && stepResult.generatedFiles.length > 0 && (
            <div>
              <p
                className="text-[11px] uppercase tracking-wider mb-2"
                style={{ color: 'var(--text-muted)' }}
              >
                Generated files
              </p>
              <div className="flex flex-wrap gap-1.5">
                {stepResult.generatedFiles.map((file, i) => (
                  <span
                    key={i}
                    className="text-[11px] px-2 py-1 rounded-md"
                    style={{
                      color: 'var(--text-secondary)',
                      background: 'var(--bg-surface)',
                      border: '0.5px solid var(--border)',
                    }}
                  >
                    {file.split('/').pop()}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
