import { useState, useEffect } from 'react';
import { Play, Loader2, CheckCircle2, ChevronRight } from 'lucide-react';
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

  // Check if execution already started
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

        // Reconstruct step results from execution state if available
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

      // Update step results
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

      // Update task status if completed
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
    <div className="space-y-6 relative">
      {/* Loading Overlay */}
      {executing && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center">
          <div className="bg-slate-800 rounded-xl border border-slate-700 p-8 shadow-2xl max-w-md w-full mx-4">
            <div className="flex flex-col items-center gap-4">
              <Loader2 className="w-12 h-12 text-blue-400 animate-spin" />
              <div className="text-center">
                <h3 className="text-lg font-semibold text-slate-100 mb-2">
                  Executando Passo {currentStep + 1}
                </h3>
                <p className="text-sm text-slate-300">
                  {loadingMessage}
                </p>
              </div>
              <div className="w-full bg-slate-700 rounded-full h-1.5 overflow-hidden">
                <div className="bg-blue-500 h-full rounded-full animate-pulse w-3/4"></div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Start Execution */}
      {!executionStarted && taskStatus === 'proceeded' && (
        <div className="bg-gradient-to-br from-blue-900/30 to-indigo-900/30 rounded-xl border border-blue-800 p-6">
          <h3 className="text-lg font-semibold text-slate-100 mb-3">
            Ready to Execute
          </h3>
          <p className="text-sm text-slate-300 mb-4">
            The plan has been approved. Click below to start step-by-step execution.
          </p>
          <button
            onClick={handleStartExecution}
            disabled={loading}
            className="flex items-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition disabled:opacity-50 disabled:cursor-not-allowed font-medium"
          >
            {loading ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                Starting...
              </>
            ) : (
              <>
                <Play className="w-5 h-5" />
                Start Execution
              </>
            )}
          </button>
        </div>
      )}

      {/* Execution Progress */}
      {executionStarted && (
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-slate-100">
              Execution Progress
            </h3>
            <div className="text-sm text-slate-400">
              {completedSteps.length} / {totalSteps} steps completed
            </div>
          </div>

          {/* Progress Bar */}
          <div className="w-full bg-slate-700 rounded-full h-2 mb-4">
            <div
              className="bg-blue-500 h-2 rounded-full transition-all duration-500"
              style={{
                width: `${(completedSteps.length / totalSteps) * 100}%`,
              }}
            />
          </div>

          {/* Next Step Button */}
          {canExecuteNext && taskStatus !== 'completed' && (
            <button
              onClick={() => handleExecuteStep(nextStepNumber)}
              disabled={executing}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-green-600 hover:bg-green-700 text-white rounded-lg transition disabled:opacity-50 disabled:cursor-not-allowed font-medium"
            >
              {executing ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  Executing Step {nextStepNumber}...
                </>
              ) : (
                <>
                  <ChevronRight className="w-5 h-5" />
                  Execute Step {nextStepNumber}
                </>
              )}
            </button>
          )}

          {/* Completed Status */}
          {taskStatus === 'completed' && (
            <div className="flex items-center justify-center gap-2 text-green-400 bg-green-900/30 px-4 py-3 rounded-lg border border-green-800">
              <CheckCircle2 className="w-5 h-5" />
              All steps completed successfully!
            </div>
          )}
        </div>
      )}

      {/* Error Message */}
      {error && (
        <div className="bg-red-900/30 text-red-400 px-4 py-3 rounded-lg text-sm border border-red-800">
          {error}
        </div>
      )}

    </div>
  );
}
