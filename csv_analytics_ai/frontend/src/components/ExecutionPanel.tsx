import { useState, useEffect } from 'react';
import { Play, Loader2, CheckCircle2, Circle, XCircle } from 'lucide-react';
import { startExecution, executeStep, getExecutionStatus } from '../api';
import type { StepExecutionResult } from '../types';

export interface StepResultState {
  stepNumber: number;
  description: string;
  summary: string;
  status: 'completed' | 'error';
  generatedFiles: string[];
  artifacts: string[];
}

interface Props {
  taskId: string;
  taskStatus: string;
  onStatusChange: (status: string) => void;
  onStepResultsChange?: (
    stepResults: Record<number, StepResultState>,
    completedSteps: number[]
  ) => void;
}

export default function ExecutionPanel({
  taskId,
  taskStatus,
  onStatusChange,
  onStepResultsChange,
}: Props) {
  const [executionStarted, setExecutionStarted] = useState(false);
  const [totalSteps, setTotalSteps] = useState(0);
  const [currentStep, setCurrentStep] = useState(0);
  const [completedSteps, setCompletedSteps] = useState<number[]>([]);
  const [stepResults, setStepResults] = useState<Record<number, StepResultState>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [executing, setExecuting] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState<string>('');

  useEffect(() => {
    if (taskStatus === 'executing' || taskStatus === 'completed') {
      loadExecutionStatus();
    }
  }, [taskId, taskStatus]);

  useEffect(() => {
    onStepResultsChange?.(stepResults, completedSteps);
  }, [stepResults, completedSteps, onStepResultsChange]);

  const loadExecutionStatus = async () => {
    try {
      const status = await getExecutionStatus(taskId);
      if (status.execution_state) {
        setExecutionStarted(true);
        setTotalSteps(status.total_steps);
        setCurrentStep(status.current_step);
        setCompletedSteps(status.completed_steps);

        if (status.execution_state.last_execution) {
          const lastExec = status.execution_state.last_execution;
          setStepResults((prev) => ({
            ...prev,
            [lastExec.step_number]: {
              stepNumber: lastExec.step_number,
              description: lastExec.step_description,
              summary: lastExec.summary,
              status: lastExec.status,
              generatedFiles: lastExec.generated_files,
              artifacts: lastExec.all_artifacts[lastExec.step_number] || [],
            },
          }));
        }
      }
    } catch (err: any) {
      console.error('Failed to load execution status:', err);
    }
  };

  const handleStartExecution = async () => {
    setLoading(true);
    setError(null);

    try {
      const result = await startExecution(taskId, 'analysis_results');
      setExecutionStarted(true);
      setTotalSteps(result.total_steps);
      setCurrentStep(0);
      setCompletedSteps([]);
      onStatusChange('executing');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to start execution');
    } finally {
      setLoading(false);
    }
  };

  const handleExecuteStep = async (stepNumber: number) => {
    setExecuting(true);
    setError(null);

    try {
      setLoadingMessage('Enviando requisição para o LLM...');

      const result = await executeStep(taskId, stepNumber);

      setLoadingMessage('Gerando arquivos de análise...');

      const execResult: StepExecutionResult = result.execution_result;

      setLoadingMessage('Renderizando resultados...');

      setStepResults((prev) => ({
        ...prev,
        [execResult.step_number]: {
          stepNumber: execResult.step_number,
          description: execResult.step_description,
          summary: execResult.summary,
          status: execResult.status,
          generatedFiles: execResult.generated_files,
          artifacts: execResult.all_artifacts[execResult.step_number] || [],
        },
      }));

      setCurrentStep(execResult.step_number);
      setCompletedSteps((prev) => [...new Set([...prev, execResult.step_number])]);

      if (result.task_status === 'completed') {
        onStatusChange('completed');
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || `Failed to execute step ${stepNumber}`);
    } finally {
      setExecuting(false);
      setLoadingMessage('');
    }
  };

  const nextStepNumber = currentStep < totalSteps ? currentStep + 1 : null;
  const canExecuteNext = executionStarted && nextStepNumber && !executing;

  return (
    <div className="space-y-4 relative">
      {/* Execution overlay */}
      {executing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.6)' }}>
          <div
            className="rounded-xl px-8 py-6 max-w-sm w-full mx-4"
            style={{
              background: 'var(--bg-sidebar)',
              border: '0.5px solid var(--border)',
            }}
          >
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="w-6 h-6 animate-spin" style={{ color: '#2563eb' }} />
              <div className="text-center">
                <p className="text-[14px] font-medium" style={{ color: 'var(--text-main)' }}>
                  Executing Step {currentStep + 1}
                </p>
                {loadingMessage && (
                  <p className="text-[12px] mt-1" style={{ color: 'var(--text-muted)' }}>
                    {loadingMessage}
                  </p>
                )}
              </div>
              <div
                className="w-full rounded-full overflow-hidden"
                style={{ height: '2px', background: 'var(--bg-surface2)' }}
              >
                <div
                  className="h-full animate-pulse rounded-full"
                  style={{ width: '75%', background: '#2563eb' }}
                />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Start Execution */}
      {!executionStarted && taskStatus === 'proceeded' && (
        <div className="pt-4">
          <p
            className="text-[11px] uppercase tracking-wider mb-3"
            style={{ color: 'var(--text-muted)' }}
          >
            Execution
          </p>
          <p className="text-[13px] mb-3" style={{ color: 'var(--text-secondary)' }}>
            Plan approved. Start step-by-step execution when ready.
          </p>
          <button
            onClick={handleStartExecution}
            disabled={loading}
            className="flex items-center gap-2 h-7 px-3 text-[12px] rounded-md transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            style={{
              color: 'var(--text-body)',
              border: '0.5px solid var(--border)',
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLElement).style.background = 'var(--bg-surface)';
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLElement).style.background = 'transparent';
            }}
          >
            {loading ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Starting...
              </>
            ) : (
              <>
                <Play className="w-3.5 h-3.5" />
                Start Execution
              </>
            )}
          </button>
        </div>
      )}

      {/* Execution Progress */}
      {executionStarted && (
        <div className="pt-4">
          <div className="flex items-center justify-between mb-2">
            <p
              className="text-[11px] uppercase tracking-wider"
              style={{ color: 'var(--text-muted)' }}
            >
              Execution
            </p>
            <span className="text-[12px]" style={{ color: 'var(--text-muted)' }}>
              {completedSteps.length}/{totalSteps}
            </span>
          </div>

          {/* Progress bar */}
          <div
            className="w-full overflow-hidden mb-4 rounded-full"
            style={{ height: '2px', background: 'var(--bg-surface2)' }}
          >
            <div
              className="h-full transition-all duration-500 rounded-full"
              style={{
                width: `${totalSteps > 0 ? (completedSteps.length / totalSteps) * 100 : 0}%`,
                background: '#2563eb',
              }}
            />
          </div>

          {/* Step status list */}
          {totalSteps > 0 && (
            <div className="space-y-0 mb-4">
              {Array.from({ length: totalSteps }, (_, i) => i + 1).map((stepNum) => {
                const isDone = completedSteps.includes(stepNum);
                const isRunning = executing && stepNum === currentStep + 1;
                const hasError = stepResults[stepNum]?.status === 'error';
                return (
                  <div
                    key={stepNum}
                    className="flex items-center gap-2.5 py-2"
                    style={{ borderBottom: '0.5px solid rgba(46,46,46,0.5)' }}
                  >
                    {hasError ? (
                      <XCircle className="w-4 h-4 flex-shrink-0" style={{ color: '#f87171' }} />
                    ) : isDone ? (
                      <CheckCircle2 className="w-4 h-4 flex-shrink-0" style={{ color: '#4ade80' }} />
                    ) : isRunning ? (
                      <Loader2 className="w-4 h-4 flex-shrink-0 animate-spin" style={{ color: '#2563eb' }} />
                    ) : (
                      <Circle className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--text-muted)' }} />
                    )}
                    <span className="text-[13px]" style={{ color: 'var(--text-secondary)' }}>
                      Step {stepNum}
                    </span>
                  </div>
                );
              })}
            </div>
          )}

          {/* Next Step Button */}
          {canExecuteNext && taskStatus !== 'completed' && (
            <button
              onClick={() => handleExecuteStep(nextStepNumber)}
              disabled={executing}
              className="flex items-center gap-1.5 h-7 px-3 text-[12px] rounded-md transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              style={{
                color: 'var(--text-body)',
                border: '0.5px solid var(--border)',
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLElement).style.background = 'var(--bg-surface)';
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLElement).style.background = 'transparent';
              }}
            >
              {executing ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  Executing...
                </>
              ) : (
                <>
                  <Play className="w-3.5 h-3.5" />
                  Execute Step {nextStepNumber}
                </>
              )}
            </button>
          )}

          {/* Completed status */}
          {taskStatus === 'completed' && (
            <div className="flex items-center gap-2 text-[13px]" style={{ color: '#4ade80' }}>
              <CheckCircle2 className="w-4 h-4" />
              All steps completed
            </div>
          )}
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
    </div>
  );
}
