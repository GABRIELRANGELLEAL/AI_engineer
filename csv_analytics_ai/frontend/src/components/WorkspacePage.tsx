import { useState, useCallback } from 'react';
import { ArrowLeft, Upload } from 'lucide-react';
import ChatInterface from './ChatInterface';
import ResultsPanel from './ResultsPanel';
import StepResultsSection from './StepResultsSection';
import FileUploadZone from './FileUploadZone';
import type { Message, PlanItem, UploadedFile } from '../types';
import type { StepResultState } from './ExecutionPanel';

interface Props {
  dataSourceType: 'csv' | 'database';
  onBack: () => void;
}

export default function WorkspacePage({ dataSourceType, onBack }: Props) {
  const [taskId, setTaskId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [currentPlan, setCurrentPlan] = useState<PlanItem[] | null>(null);
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([]);
  const [taskStatus, setTaskStatus] = useState<string>('');
  const [selectedSteps, setSelectedSteps] = useState<number[]>([]);
  const [stepResults, setStepResults] = useState<Record<number, StepResultState>>({});
  const [completedSteps, setCompletedSteps] = useState<number[]>([]);

  const handleStepResultsChange = useCallback(
    (results: Record<number, StepResultState>, steps: number[]) => {
      setStepResults(results);
      setCompletedSteps(steps);
    },
    []
  );

  const hasStepResults = Object.keys(stepResults).length > 0;

  const handleNewMessage = (message: Message) => {
    setMessages((prev) => [...prev, message]);
  };

  const handlePlanUpdate = (plan: PlanItem[], status?: string) => {
    setCurrentPlan(plan);
    if (status) {
      setTaskStatus(status);
    }
    setSelectedSteps(plan.length > 0 ? plan.map((item) => item.step) : []);
  };

  const handleTaskCreated = (id: string, initialMessage: Message, assistantMessage: Message, status?: string) => {
    setTaskId(id);
    setMessages([initialMessage, assistantMessage]);
    if (status) setTaskStatus(status);
  };

  const handleFilesUploaded = (files: UploadedFile[]) => {
    setUploadedFiles(files);
  };

  const handleRemoveFile = (path: string) => {
    setUploadedFiles((prev) => prev.filter((f) => f.path !== path));
  };

  return (
    <div
      className="h-screen flex flex-col overflow-hidden"
      style={{ background: 'var(--bg-page)' }}
    >
      {/* Header */}
      <header
        className="flex-shrink-0 h-12 flex items-center justify-between px-4"
        style={{
          background: 'var(--bg-sidebar)',
          borderBottom: '0.5px solid var(--border)',
        }}
      >
        <div className="flex items-center gap-3">
          {/* Orange accent logo */}
          <div
            className="w-5 h-5 rounded-sm flex-shrink-0"
            style={{ background: 'var(--accent)' }}
          />
          <span className="text-[14px] font-medium leading-none" style={{ color: 'var(--text-main)' }}>
            Time Series Analysis Agent
          </span>
          <span
            className="text-[11px] font-medium uppercase tracking-wider"
            style={{ color: 'var(--text-muted)' }}
          >
            {dataSourceType}
          </span>
          {taskId && (
            <span className="text-[12px]" style={{ color: 'var(--text-muted)' }}>
              {taskId.slice(0, 8)}
            </span>
          )}
        </div>
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 px-3 h-7 text-[13px] rounded-md transition-colors"
          style={{
            color: 'var(--text-secondary)',
            border: '0.5px solid var(--border)',
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLElement).style.background = 'var(--bg-surface2)';
            (e.currentTarget as HTMLElement).style.color = 'var(--text-main)';
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLElement).style.background = 'transparent';
            (e.currentTarget as HTMLElement).style.color = 'var(--text-secondary)';
          }}
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back
        </button>
      </header>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
        {/* Upper pane: chat (60%) + plan panel (40%) */}
        <div
          className={`flex min-h-0 overflow-hidden ${
            hasStepResults ? 'h-[50vh] shrink-0' : 'flex-1'
          }`}
        >
          {/* Left Side: Upload + Chat — 60% */}
          <div
            className="flex flex-col min-h-0"
            style={{
              width: '60%',
              background: 'var(--bg-page)',
              borderRight: '0.5px solid var(--border)',
            }}
          >
            {/* File Upload Zone (CSV only, before task created) */}
            {dataSourceType === 'csv' && !taskId && (
              <div
                className="p-4"
                style={{ borderBottom: '0.5px solid var(--border)' }}
              >
                <FileUploadZone
                  onFilesUploaded={handleFilesUploaded}
                  uploadedFiles={uploadedFiles}
                  onRemoveFile={handleRemoveFile}
                />
              </div>
            )}

            {/* Uploaded Files Summary (CSV only, after task created) */}
            {dataSourceType === 'csv' && taskId && uploadedFiles.length > 0 && (
              <div
                className="px-4 py-2"
                style={{ borderBottom: '0.5px solid var(--border)' }}
              >
                <div className="flex items-center gap-2 text-[12px]" style={{ color: 'var(--text-muted)' }}>
                  <Upload className="w-3.5 h-3.5" />
                  <span>
                    {uploadedFiles.length} file{uploadedFiles.length !== 1 ? 's' : ''} uploaded
                  </span>
                </div>
              </div>
            )}

            {/* Database Placeholder */}
            {dataSourceType === 'database' && !taskId && (
              <div
                className="px-4 py-6 text-center"
                style={{ borderBottom: '0.5px solid var(--border)' }}
              >
                <div className="text-[14px] mb-1" style={{ color: 'var(--text-secondary)' }}>
                  Database connection
                </div>
                <div className="text-[12px]" style={{ color: 'var(--text-muted)' }}>
                  Coming soon — database integration is under development
                </div>
              </div>
            )}

            {/* Chat Interface */}
            <div className="flex-1 min-h-0 overflow-hidden">
              <ChatInterface
                taskId={taskId}
                uploadedFiles={uploadedFiles}
                dataSourceType={dataSourceType}
                taskStatus={taskStatus}
                onTaskCreated={handleTaskCreated}
                onNewMessage={handleNewMessage}
                onPlanUpdate={handlePlanUpdate}
              />
            </div>
          </div>

          {/* Right Side: Results Panel — 40% */}
          <div
            className="min-h-0 overflow-hidden"
            style={{ width: '40%', background: 'var(--bg-sidebar)' }}
          >
            <ResultsPanel
              messages={messages}
              plan={currentPlan}
              taskId={taskId}
              taskStatus={taskStatus}
              onStatusChange={setTaskStatus}
              selectedSteps={selectedSteps}
              onStepsChange={setSelectedSteps}
              onStepResultsChange={handleStepResultsChange}
            />
          </div>
        </div>

        {/* Full-width step results */}
        {hasStepResults && taskId && (
          <div
            className="flex-1 min-h-0 overflow-y-auto w-full"
            style={{
              borderTop: '0.5px solid var(--border)',
              background: 'var(--bg-page)',
            }}
          >
            <StepResultsSection
              stepResults={stepResults}
              completedSteps={completedSteps}
              taskId={taskId}
            />
          </div>
        )}
      </div>
    </div>
  );
}
