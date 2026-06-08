import { useState, useRef, useEffect } from 'react';
import { Send, Loader2, Bot, User } from 'lucide-react';
import { createTask, sendMessage } from '../api';
import type { Message, PlanItem, UploadedFile } from '../types';
import ReactMarkdown from 'react-markdown';

// Normalize plan to ensure consistent PlanItem[] format
const normalizePlan = (plan: PlanItem[] | string[] | null | undefined): PlanItem[] => {
  if (!plan || !Array.isArray(plan) || plan.length === 0) return [];
  
  return plan.map((item, index) => {
    if (typeof item === 'string') {
      return { step: index + 1, description: item };
    }
    if (typeof item === 'object' && item !== null) {
      return {
        step: item.step || index + 1,
        description: item.description || String(item),
        agent: item.agent,
      };
    }
    return { step: index + 1, description: String(item) };
  });
};

interface Props {
  taskId: string | null;
  uploadedFiles: UploadedFile[];
  dataSourceType: 'csv' | 'database';
  taskStatus?: string;
  onTaskCreated: (taskId: string, userMessage: Message, assistantMessage: Message, status?: string) => void;
  onNewMessage: (message: Message) => void;
  onPlanUpdate: (plan: PlanItem[], status?: string) => void;
}

export default function ChatInterface({
  taskId,
  uploadedFiles,
  dataSourceType,
  taskStatus = '',
  onTaskCreated,
  onNewMessage,
  onPlanUpdate,
}: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || loading) return;

    // For CSV: require at least one uploaded file before first message
    if (dataSourceType === 'csv' && !taskId && uploadedFiles.length === 0) {
      setError('Please upload at least one CSV file before starting the conversation');
      return;
    }

    // For Database: show coming soon message
    if (dataSourceType === 'database' && !taskId) {
      setError('Database connection is not yet implemented. Please use CSV upload.');
      return;
    }

    // Prevent messages during execution
    if (taskStatus === 'executing' || taskStatus === 'completed') {
      setError('Cannot send messages while task is executing or completed');
      return;
    }

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setLoading(true);
    setError(null);

    try {
      if (!taskId) {
        // First message - create task
        const response = await createTask({
          data_source_type: dataSourceType,
          data_source_meta:
            dataSourceType === 'csv'
              ? { csv_paths: uploadedFiles.map((f) => f.path) }
              : { database_id: 'placeholder' },
          prompt: input,
        });

        const assistantMessage: Message = {
          id: response.interaction_id,
          role: 'assistant',
          content: response.answer,
          timestamp: new Date(),
        };

        setMessages((prev) => [...prev, assistantMessage]);
        onTaskCreated(response.task_id, userMessage, assistantMessage, response.status);

        const normalized = normalizePlan(response.plan);
        if (normalized.length > 0) {
          onPlanUpdate(normalized, response.status);
        }
      } else {
        // Follow-up message
        const response = await sendMessage(taskId, { prompt: input });

        const assistantMessage: Message = {
          id: response.interaction_id,
          role: 'assistant',
          content: response.answer,
          timestamp: new Date(),
        };

        setMessages((prev) => [...prev, assistantMessage]);
        onNewMessage(assistantMessage);

        const normalized = normalizePlan(response.plan);
        if (normalized.length > 0) {
          onPlanUpdate(normalized, response.status);
        }
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to send message');
    } finally {
      setLoading(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col h-full bg-slate-900">
      {/* Messages Container */}
      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center text-slate-500">
              <Bot className="w-16 h-16 mx-auto mb-4 opacity-50" />
              <p className="text-lg mb-2 text-slate-300">
                {dataSourceType === 'csv' && uploadedFiles.length === 0
                  ? 'Upload CSV files to get started'
                  : 'Start a conversation with the planner agent'}
              </p>
              <p className="text-sm">
                {dataSourceType === 'csv' && uploadedFiles.length > 0
                  ? `${uploadedFiles.length} file${uploadedFiles.length !== 1 ? 's' : ''} ready for analysis`
                  : 'Ask questions about your analysis task'}
              </p>
            </div>
          </div>
        )}

        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex gap-3 ${
              message.role === 'user' ? 'justify-end' : 'justify-start'
            }`}
          >
            {message.role === 'assistant' && (
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-500 flex items-center justify-center">
                <Bot className="w-5 h-5 text-white" />
              </div>
            )}

            <div
              className={`max-w-[70%] rounded-2xl px-4 py-3 ${
                message.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-800 text-slate-200 border border-slate-700'
              }`}
            >
              {message.role === 'assistant' ? (
                <div className="prose prose-sm max-w-none prose-invert">
                  <ReactMarkdown>{message.content}</ReactMarkdown>
                </div>
              ) : (
                <p className="whitespace-pre-wrap">{message.content}</p>
              )}
              <div
                className={`text-xs mt-2 ${
                  message.role === 'user' ? 'text-blue-100' : 'text-slate-500'
                }`}
              >
                {message.timestamp.toLocaleTimeString()}
              </div>
            </div>

            {message.role === 'user' && (
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-slate-700 flex items-center justify-center">
                <User className="w-5 h-5 text-white" />
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div className="flex gap-3 justify-start">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-500 flex items-center justify-center">
              <Bot className="w-5 h-5 text-white" />
            </div>
            <div className="bg-slate-800 border border-slate-700 rounded-2xl px-4 py-3">
              <Loader2 className="w-5 h-5 text-slate-400 animate-spin" />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Error Message */}
      {error && (
        <div className="px-6 py-2">
          <div className="bg-red-900/30 text-red-400 px-4 py-2 rounded-lg text-sm border border-red-800">
            {error}
          </div>
        </div>
      )}

      {/* Input Area */}
      <div className="border-t border-slate-800 p-4 bg-slate-900">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder={
              dataSourceType === 'csv' && !taskId && uploadedFiles.length === 0
                ? 'Upload CSV files first...'
                : taskStatus === 'executing' || taskStatus === 'completed'
                ? 'Chat is disabled during execution...'
                : taskStatus === 'proceeded'
                ? 'You can still modify the plan before execution starts...'
                : 'Type your message... (Press Enter to send, Shift+Enter for new line)'
            }
            rows={2}
            className="flex-1 px-4 py-3 rounded-lg bg-slate-800 border border-slate-700 text-slate-200 placeholder-slate-500 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none resize-none"
            disabled={loading || (dataSourceType === 'csv' && !taskId && uploadedFiles.length === 0) || taskStatus === 'executing' || taskStatus === 'completed'}
          />
          <button
            onClick={handleSend}
            disabled={loading || !input.trim() || (dataSourceType === 'csv' && !taskId && uploadedFiles.length === 0) || taskStatus === 'executing' || taskStatus === 'completed'}
            className="px-6 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center"
          >
            {loading ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Send className="w-5 h-5" />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
