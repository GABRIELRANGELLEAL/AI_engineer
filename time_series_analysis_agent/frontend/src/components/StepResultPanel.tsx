import { useState, useEffect } from 'react';
import { CheckCircle2, AlertCircle, Loader2, ChevronDown, ChevronRight } from 'lucide-react';
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
    // Find ui.json file in generated files
    const uiFilePath = stepResult.generatedFiles.find((f) =>
      f.includes('_ui.json')
    );

    if (uiFilePath) {
      setLoading(true);
      setError(null);

      // Fetch UI payload from workspace
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
    <div className="bg-slate-800 rounded-xl border border-slate-700 shadow-lg overflow-hidden">
      {/* Header - Clickable */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-start justify-between p-5 hover:bg-slate-700/30 transition"
      >
        <div className="flex-1 text-left">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-lg font-semibold text-slate-100">
              Step {stepResult.stepNumber}
            </h3>
            {stepResult.status === 'completed' ? (
              <CheckCircle2 className="w-5 h-5 text-green-400" />
            ) : (
              <AlertCircle className="w-5 h-5 text-red-400" />
            )}
          </div>
          <p className="text-sm text-slate-400">{stepResult.description}</p>
        </div>
        <div className="flex-shrink-0 ml-4">
          {isExpanded ? (
            <ChevronDown className="w-5 h-5 text-slate-400" />
          ) : (
            <ChevronRight className="w-5 h-5 text-slate-400" />
          )}
        </div>
      </button>

      {/* Collapsible Content */}
      {isExpanded && (
        <div className="px-5 pb-5">
          {/* Quick Summary */}
          <div className="bg-slate-900/50 rounded-lg p-3 mb-4 border border-slate-700">
            <p className="text-xs text-slate-300 leading-relaxed">
              {stepResult.summary}
            </p>
          </div>

          {/* Loading State */}
          {loading && (
            <div className="flex items-center justify-center py-8 text-slate-400">
              <Loader2 className="w-6 h-6 animate-spin mr-2" />
              Loading analysis results...
            </div>
          )}

          {/* Error State */}
          {error && (
            <div className="bg-red-900/30 text-red-400 px-4 py-3 rounded-lg text-sm border border-red-800">
              {error}
            </div>
          )}

          {/* UI Blocks */}
          {uiPayload?.blocks && (
            <div className="space-y-4 mt-4">
              {uiPayload.title && (
                <h4 className="text-base font-semibold text-slate-100 border-b border-slate-700 pb-2">
                  {uiPayload.title}
                </h4>
              )}
              {uiPayload.blocks.map((block, i) => (
                <UIBlock key={i} block={block} />
              ))}
            </div>
          )}

          {/* Fallback - show file list if no UI */}
          {!loading &&
            !uiPayload &&
            !error &&
            stepResult.generatedFiles.length > 0 && (
              <div className="mt-3 pt-3 border-t border-slate-700">
                <p className="text-xs text-slate-500 mb-2">Generated files:</p>
                <div className="flex flex-wrap gap-2">
                  {stepResult.generatedFiles.map((file, i) => (
                    <span
                      key={i}
                      className="text-xs bg-slate-700 text-slate-300 px-2 py-1 rounded"
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
