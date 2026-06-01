import { useState } from 'react';
import { ArrowLeft, Upload } from 'lucide-react';
import ChatInterface from './ChatInterface';
import ResultsPanel from './ResultsPanel';
import FileUploadZone from './FileUploadZone';
import type { Message, PlanItem, UploadedFile } from '../types';

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

  const handleNewMessage = (message: Message) => {
    setMessages((prev) => [...prev, message]);
  };

  const handlePlanUpdate = (plan: PlanItem[], status?: string) => {
    setCurrentPlan(plan);
    if (status) setTaskStatus(status);
    // Reset selection when new plan arrives, default to all selected
    setSelectedSteps(plan.map(item => item.step));
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
    <div className="min-h-screen flex flex-col bg-slate-950">
      {/* Header */}
      <header className="bg-slate-900 shadow-lg border-b border-slate-800">
        <div className="px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h1 className="text-2xl font-bold text-slate-100">
              Time Series Analysis Agent
            </h1>
            <span className="px-3 py-1 bg-blue-600 text-blue-100 text-sm font-medium rounded-full">
              {dataSourceType.toUpperCase()}
            </span>
            {taskId && (
              <span className="text-sm text-slate-400">
                Task: {taskId.slice(0, 8)}...
              </span>
            )}
          </div>
          <button
            onClick={onBack}
            className="flex items-center gap-2 px-4 py-2 text-slate-300 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition"
          >
            <ArrowLeft className="w-5 h-5" />
            Back to Sources
          </button>
        </div>
      </header>

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Side: Upload + Chat */}
        <div className="flex-1 flex flex-col border-r border-slate-800 bg-slate-900">
          {/* File Upload Zone (CSV only, shown before task created) */}
          {dataSourceType === 'csv' && !taskId && (
            <div className="p-4 border-b border-slate-200 bg-slate-50">
              <FileUploadZone
                onFilesUploaded={handleFilesUploaded}
                uploadedFiles={uploadedFiles}
                onRemoveFile={handleRemoveFile}
              />
            </div>
          )}

          {/* Uploaded Files Summary (CSV only, after task created) */}
          {dataSourceType === 'csv' && taskId && uploadedFiles.length > 0 && (
            <div className="p-3 border-b border-slate-200 bg-blue-50">
              <div className="flex items-center gap-2 text-sm text-blue-700">
                <Upload className="w-4 h-4" />
                <span className="font-medium">
                  {uploadedFiles.length} file{uploadedFiles.length !== 1 ? 's' : ''} uploaded
                </span>
              </div>
            </div>
          )}

          {/* Database Placeholder */}
          {dataSourceType === 'database' && !taskId && (
            <div className="p-6 border-b border-slate-200 bg-slate-50">
              <div className="text-center py-8">
                <div className="text-slate-500 mb-2">Database connection</div>
                <div className="text-sm text-slate-400">
                  Coming soon - database integration is under development
                </div>
              </div>
            </div>
          )}

          {/* Chat Interface */}
          <div className="flex-1 overflow-hidden">
            <ChatInterface
              taskId={taskId}
              uploadedFiles={uploadedFiles}
              dataSourceType={dataSourceType}
              onTaskCreated={handleTaskCreated}
              onNewMessage={handleNewMessage}
              onPlanUpdate={handlePlanUpdate}
            />
          </div>
        </div>

        {/* Right Side: Results Panel */}
        <div className="w-[45%] bg-slate-900 overflow-auto">
          <ResultsPanel 
            messages={messages} 
            plan={currentPlan}
            taskId={taskId}
            taskStatus={taskStatus}
            onStatusChange={setTaskStatus}
            selectedSteps={selectedSteps}
            onStepsChange={setSelectedSteps}
          />
        </div>
      </div>
    </div>
  );
}
