import StepResultPanel from './StepResultPanel';

interface StepResultState {
  stepNumber: number;
  description: string;
  summary: string;
  status: 'completed' | 'error';
  generatedFiles: string[];
  artifacts: string[];
}

interface Props {
  stepResults: Record<number, StepResultState>;
  completedSteps: number[];
  taskId: string;
}

export default function StepResultsSection({ stepResults, completedSteps, taskId }: Props) {
  if (Object.keys(stepResults).length === 0) return null;

  return (
    <div className="w-full px-6 py-4 space-y-4">
      <h3
        className="text-lg font-semibold flex items-center gap-2 pb-2"
        style={{
          color: 'var(--text-main)',
          borderBottom: '0.5px solid var(--border)',
        }}
      >
        Resultados da Análise
      </h3>
      <div className="space-y-3">
        {completedSteps
          .sort((a, b) => a - b)
          .map((stepNum) => {
            const result = stepResults[stepNum];
            if (!result) return null;
            return (
              <StepResultPanel
                key={stepNum}
                stepResult={result}
                taskId={taskId}
              />
            );
          })}
      </div>
    </div>
  );
}
