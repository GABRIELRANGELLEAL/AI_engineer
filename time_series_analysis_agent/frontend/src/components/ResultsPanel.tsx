import { useState } from 'react';
import { FileText, BarChart3, Play, Loader2, CheckCircle2, CheckSquare, Square } from 'lucide-react';
import type { Message, PlanItem } from '../types';
import { proceedTask } from '../api';

interface Props {
  messages: Message[];
  plan: PlanItem[] | null;
  taskId: string | null;
  taskStatus: string;
  onStatusChange: (status: string) => void;
  selectedSteps: number[];
  onStepsChange: (steps: number[]) => void;
}

export default function ResultsPanel({ 
  messages, 
  plan, 
  taskId, 
  taskStatus, 
  onStatusChange,
  selectedSteps,
  onStepsChange 
}: Props) {
  const [building, setBuilding] = useState(false);
  const [buildError, setBuildError] = useState<string | null>(null);

  const canBuild = taskId && plan && plan.length > 0 && taskStatus === 'plan_ready';
  const isProceeded = taskStatus === 'proceeded' || taskStatus === 'completed';

  const handleToggleStep = (step: number) => {
    if (selectedSteps.includes(step)) {
      onStepsChange(selectedSteps.filter(s => s !== step));
    } else {
      onStepsChange([...selectedSteps, step].sort((a, b) => a - b));
    }
  };

  const handleToggleAll = () => {
    if (plan && selectedSteps.length === plan.length) {
      // Deselect all
      onStepsChange([]);
    } else {
      // Select all
      onStepsChange(plan?.map(item => item.step) || []);
    }
  };

  const handleBuild = async () => {
    if (!taskId || !canBuild) return;
    
    setBuilding(true);
    setBuildError(null);
    
    try {
      // Store selected steps in localStorage to pass to execute
      if (selectedSteps.length > 0 && plan) {
        localStorage.setItem(`task_${taskId}_selected_steps`, JSON.stringify(selectedSteps));
      }
      await proceedTask(taskId);
      onStatusChange('proceeded');
    } catch (err: any) {
      setBuildError(err.response?.data?.detail || 'Failed to proceed with plan');
    } finally {
      setBuilding(false);
    }
  };

  return (
    <div className="h-full p-6 space-y-6 bg-slate-900">
      <div className="sticky top-0 bg-slate-900 pb-4 z-10">
        <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">
          <BarChart3 className="w-6 h-6 text-blue-400" />
          Results & Analysis
        </h2>
        <p className="text-sm text-slate-400 mt-1">
          View outputs, plans, and analysis results
        </p>
      </div>

      {/* Plan Section */}
      {plan && plan.length > 0 && (
        <div className="bg-slate-800 rounded-xl shadow-lg border border-slate-700 p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-slate-100 flex items-center gap-2">
              <FileText className="w-5 h-5 text-blue-400" />
              Analysis Plan
            </h3>
            {isProceeded && (
              <div className="flex items-center gap-2 text-green-400 text-sm">
                <CheckCircle2 className="w-4 h-4" />
                Approved
              </div>
            )}
          </div>

          {/* Select All Toggle */}
          {!isProceeded && (
            <button
              onClick={handleToggleAll}
              className="flex items-center gap-2 text-sm text-slate-300 hover:text-slate-100 mb-3 transition"
            >
              {selectedSteps.length === plan.length ? (
                <CheckSquare className="w-4 h-4" />
              ) : (
                <Square className="w-4 h-4" />
              )}
              {selectedSteps.length === plan.length ? 'Deselect All' : 'Select All'}
            </button>
          )}
          
          <div className="space-y-2 mb-4">
            {plan.map((item) => {
              const isSelected = selectedSteps.includes(item.step);
              return (
                <div 
                  key={item.step} 
                  className={`flex gap-3 p-3 rounded-lg border transition ${
                    isSelected 
                      ? 'bg-slate-700/50 border-blue-500/50' 
                      : 'bg-slate-800/50 border-slate-600 opacity-60'
                  }`}
                >
                  {!isProceeded && (
                    <button
                      onClick={() => handleToggleStep(item.step)}
                      className="flex-shrink-0 mt-0.5"
                    >
                      {isSelected ? (
                        <CheckSquare className="w-5 h-5 text-blue-400" />
                      ) : (
                        <Square className="w-5 h-5 text-slate-500 hover:text-slate-300" />
                      )}
                    </button>
                  )}
                  <div className="flex-1">
                    <div className="text-sm font-medium text-slate-200">
                      Step {item.step}
                    </div>
                    <div className="text-sm text-slate-300 mt-1">
                      {item.description}
                    </div>
                    {item.agent && (
                      <div className="text-xs text-slate-500 mt-1">
                        Agent: {item.agent}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Build Button */}
          {canBuild && (
            <div className="pt-3 border-t border-slate-700">
              <button
                onClick={handleBuild}
                disabled={building || selectedSteps.length === 0}
                className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition disabled:opacity-50 disabled:cursor-not-allowed font-medium"
              >
                {building ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" />
                    Building...
                  </>
                ) : (
                  <>
                    <Play className="w-5 h-5" />
                    Build {selectedSteps.length > 0 && selectedSteps.length < plan.length ? `${selectedSteps.length} Selected Step${selectedSteps.length !== 1 ? 's' : ''}` : 'Plan'}
                  </>
                )}
              </button>
              {buildError && (
                <div className="mt-2 text-sm text-red-400 bg-red-900/30 px-3 py-2 rounded border border-red-800">
                  {buildError}
                </div>
              )}
              <p className="text-xs text-slate-400 mt-2 text-center">
                {selectedSteps.length === 0 
                  ? 'Select at least one step to execute'
                  : `Will execute ${selectedSteps.length === plan.length ? 'all' : selectedSteps.length} step${selectedSteps.length !== 1 ? 's' : ''}`
                }
              </p>
            </div>
          )}

          {isProceeded && (
            <div className="pt-3 border-t border-slate-700">
              <div className="bg-green-900/30 text-green-400 px-4 py-3 rounded-lg text-sm text-center border border-green-800">
                Plan approved and ready for execution
              </div>
            </div>
          )}
        </div>
      )}

      {/* Visualizations Section */}
      {taskId && (
        <div className="bg-gradient-to-br from-blue-900/30 to-indigo-900/30 rounded-xl border border-blue-800 p-5">
          <h3 className="font-semibold text-slate-100 mb-2 flex items-center gap-2">
            <BarChart3 className="w-5 h-5 text-blue-400" />
            Analysis Results
          </h3>
          <p className="text-sm text-slate-300">
            Charts, graphs, and outputs will appear here after the plan is executed.
          </p>
        </div>
      )}

      {/* Empty state when no task */}
      {!taskId && (
        <div className="bg-slate-800 rounded-xl shadow-lg border border-slate-700 p-8 text-center">
          <div className="text-slate-500">
            <FileText className="w-12 h-12 mx-auto mb-3 opacity-50" />
            <p className="text-slate-300">No analysis yet</p>
            <p className="text-sm mt-1">
              Start a conversation to create a plan
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
