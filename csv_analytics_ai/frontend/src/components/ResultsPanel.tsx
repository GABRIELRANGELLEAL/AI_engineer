import { useState } from 'react';
import { Play, Loader2, CheckCircle2, CheckSquare, Square, AlertCircle } from 'lucide-react';
import type { Message, PlanItem } from '../types';
import { proceedTask } from '../api';
import ExecutionPanel, { type StepResultState } from './ExecutionPanel';

interface Props {
  messages: Message[];
  plan: PlanItem[] | null;
  taskId: string | null;
  taskStatus: string;
  onStatusChange: (status: string) => void;
  selectedSteps: number[];
  onStepsChange: (steps: number[]) => void;
  onStepResultsChange?: (
    stepResults: Record<number, StepResultState>,
    completedSteps: number[]
  ) => void;
}

export default function ResultsPanel({
  plan,
  taskId,
  taskStatus,
  onStatusChange,
  selectedSteps,
  onStepsChange,
  onStepResultsChange,
}: Props) {
  const [building, setBuilding] = useState(false);
  const [buildError, setBuildError] = useState<string | null>(null);

  const canBuild = taskId && plan && plan.length > 0 && taskStatus === 'plan_ready';
  const isProceeded = taskStatus === 'proceeded' || taskStatus === 'executing' || taskStatus === 'completed';

  const handleToggleStep = (step: number) => {
    if (selectedSteps.includes(step)) {
      onStepsChange(selectedSteps.filter((s) => s !== step));
    } else {
      onStepsChange([...selectedSteps, step].sort((a, b) => a - b));
    }
  };

  const handleToggleAll = () => {
    if (plan && selectedSteps.length === plan.length) {
      onStepsChange([]);
    } else {
      onStepsChange(plan?.map((item) => item.step) || []);
    }
  };

  const handleBuild = async () => {
    if (!taskId || !canBuild) return;

    setBuilding(true);
    setBuildError(null);

    try {
      await proceedTask(taskId, selectedSteps);
      onStatusChange('proceeded');
    } catch (err: any) {
      setBuildError(err.response?.data?.detail || 'Failed to proceed with plan');
    } finally {
      setBuilding(false);
    }
  };

  return (
    <div
      className="h-full flex flex-col"
      style={{ background: 'var(--bg-sidebar)' }}
    >
      {/* Header */}
      <div
        className="flex-shrink-0 px-4 pt-4 pb-3"
        style={{ borderBottom: '0.5px solid var(--border)' }}
      >
        <p
          className="text-[11px] font-medium uppercase tracking-wider"
          style={{ color: 'var(--text-muted)' }}
        >
          Analysis Plan
        </p>
      </div>

      {/* Scrollable Content */}
      <div className="flex-1 overflow-y-auto">

        {/* Info Banner */}
        {taskStatus === 'proceeded' && (
          <div
            className="mx-4 mt-4 flex items-start gap-2 text-[12px] rounded-lg px-3 py-2.5"
            style={{
              color: 'var(--text-muted)',
              border: '0.5px solid var(--border)',
            }}
          >
            <AlertCircle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" style={{ color: 'var(--text-muted)' }} />
            <span>Plan approved. You can still refine it via chat before execution begins.</span>
          </div>
        )}

        {/* Plan Section */}
        {plan && plan.length > 0 && (
          <div className="px-4 pt-4">
            {/* Select All Toggle */}
            {!isProceeded && (
              <button
                onClick={handleToggleAll}
                className="flex items-center gap-2 text-[12px] mb-1 transition-colors"
                style={{ color: 'var(--text-muted)' }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLElement).style.color = 'var(--text-body)';
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLElement).style.color = 'var(--text-muted)';
                }}
              >
                {selectedSteps.length === plan.length ? (
                  <CheckSquare className="w-3.5 h-3.5" />
                ) : (
                  <Square className="w-3.5 h-3.5" />
                )}
                {selectedSteps.length === plan.length ? 'Deselect all' : 'Select all'}
              </button>
            )}

            {/* Step list */}
            <div>
              {plan.map((item) => {
                const isSelected = selectedSteps.includes(item.step);
                return (
                  <div
                    key={item.step}
                    className="flex items-start gap-3 py-3"
                    style={{ borderBottom: '0.5px solid var(--border)' }}
                  >
                    {!isProceeded && (
                      <button
                        onClick={() => handleToggleStep(item.step)}
                        className="flex-shrink-0 mt-0.5 w-4 h-4 rounded flex items-center justify-center transition-colors"
                        style={{
                          backgroundColor: isSelected ? '#2563eb' : 'transparent',
                          border: `0.5px solid ${isSelected ? '#2563eb' : 'var(--border-hi)'}`,
                        }}
                      >
                        {isSelected && (
                          <svg className="w-2.5 h-2.5 text-white" viewBox="0 0 10 8" fill="none">
                            <path
                              d="M1 4l3 3 5-6"
                              stroke="currentColor"
                              strokeWidth="1.5"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            />
                          </svg>
                        )}
                      </button>
                    )}
                    {isProceeded && (
                      <CheckCircle2 className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color: '#4ade80' }} />
                    )}
                    <div className="flex-1 min-w-0">
                      <div
                        className="text-[14px] leading-snug"
                        style={{ color: isSelected ? 'var(--text-main)' : 'var(--text-muted)' }}
                      >
                        <span className="font-medium mr-1.5">Step {item.step}.</span>
                        {item.description}
                      </div>
                      {item.agent && (
                        <div className="text-[11px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
                          {item.agent}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Approve Button */}
            {canBuild && (
              <div className="pt-4 pb-4">
                <button
                  onClick={handleBuild}
                  disabled={building || selectedSteps.length === 0}
                  className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-[14px] font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  style={{
                    background: '#2563eb',
                    color: '#ffffff',
                  }}
                  onMouseEnter={(e) => {
                    if (!(e.currentTarget as HTMLButtonElement).disabled)
                      (e.currentTarget as HTMLElement).style.background = '#1d4ed8';
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLElement).style.background = '#2563eb';
                  }}
                >
                  {building ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Approving...
                    </>
                  ) : (
                    <>
                      <Play className="w-4 h-4" />
                      Approve Plan
                    </>
                  )}
                </button>
                {buildError && (
                  <div
                    className="mt-2 text-[12px] px-3 py-2 rounded-lg"
                    style={{
                      color: '#f87171',
                      border: '0.5px solid #7f1d1d',
                      background: 'rgba(127,29,29,0.15)',
                    }}
                  >
                    {buildError}
                  </div>
                )}
                {selectedSteps.length === 0 && (
                  <p className="text-[11px] mt-1.5 text-center" style={{ color: 'var(--text-muted)' }}>
                    Select at least one step to execute
                  </p>
                )}
              </div>
            )}
          </div>
        )}

        {/* Execution Section */}
        {taskId && isProceeded && (
          <div className="px-4 pb-4">
            <ExecutionPanel
              taskId={taskId}
              taskStatus={taskStatus}
              onStatusChange={onStatusChange}
              onStepResultsChange={onStepResultsChange}
            />
          </div>
        )}

        {/* Empty state */}
        {!taskId && (
          <div className="px-4 py-12 text-center">
            <p className="text-[13px]" style={{ color: 'var(--text-muted)' }}>
              Start a conversation to generate a plan
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
