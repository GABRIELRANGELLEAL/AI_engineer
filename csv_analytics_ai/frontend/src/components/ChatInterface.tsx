import { useState, useRef, useEffect } from 'react';
import { ArrowUp, Loader2 } from 'lucide-react';
import { createTask, sendMessage } from '../api';
import type { Message, PlanItem, UploadedFile } from '../types';
import ReactMarkdown from 'react-markdown';

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

    if (dataSourceType === 'csv' && !taskId && uploadedFiles.length === 0) {
      setError('Please upload at least one CSV file before starting the conversation');
      return;
    }

    if (dataSourceType === 'database' && !taskId) {
      setError('Database connection is not yet implemented. Please use CSV upload.');
      return;
    }

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
    <div
      className="flex flex-col h-full"
      style={{ background: 'var(--bg-page)' }}
    >
      {/* Messages Container */}
      <div className="flex-1 overflow-y-auto px-4 py-5 space-y-5">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <p className="text-[15px] mb-1" style={{ color: 'var(--text-secondary)' }}>
                {dataSourceType === 'csv' && uploadedFiles.length === 0
                  ? 'Upload CSV files to get started'
                  : 'Start a conversation with the planner agent'}
              </p>
              <p className="text-[13px]" style={{ color: 'var(--text-muted)' }}>
                {dataSourceType === 'csv' && uploadedFiles.length > 0
                  ? `${uploadedFiles.length} file${uploadedFiles.length !== 1 ? 's' : ''} ready for analysis`
                  : 'Describe your time series analysis task'}
              </p>
            </div>
          </div>
        )}

        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex gap-3 ${
              message.role === 'user' ? 'justify-end' : 'justify-start items-start'
            }`}
          >
            {/* Bot avatar */}
            {message.role === 'assistant' && (
              <div
                className="flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center mt-0.5"
                style={{ background: 'var(--accent)' }}
              >
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                  <path
                    d="M8 1l1.5 4.5H14l-3.75 2.75L11.75 13 8 10.25 4.25 13l1.5-4.75L2 5.5h4.5L8 1z"
                    fill="white"
                  />
                </svg>
              </div>
            )}

            {message.role === 'user' ? (
              <div
                className="max-w-[75%] rounded-2xl px-4 py-2.5"
                style={{ background: 'var(--bg-surface2)' }}
              >
                <p
                  className="text-[14px] whitespace-pre-wrap leading-relaxed"
                  style={{ color: 'var(--text-main)' }}
                >
                  {message.content}
                </p>
              </div>
            ) : (
              <div className="max-w-[85%]">
                <p
                  className="text-[11px] mb-1.5 font-medium"
                  style={{ color: 'var(--text-secondary)' }}
                >
                  Agent
                </p>
                <div
                  className="prose prose-sm max-w-none"
                  style={{
                    '--tw-prose-body': 'var(--text-body)',
                    '--tw-prose-headings': 'var(--text-main)',
                    '--tw-prose-bold': 'var(--text-main)',
                    '--tw-prose-bullets': 'var(--text-secondary)',
                    '--tw-prose-counters': 'var(--text-secondary)',
                    '--tw-prose-links': '#4ade80',
                    '--tw-prose-code': '#4ade80',
                  } as React.CSSProperties}
                >
                  <ReactMarkdown
                    components={{
                      p: ({ children }) => (
                        <p style={{ color: 'var(--text-body)', lineHeight: '1.75', marginBottom: '0.5rem' }}>
                          {children}
                        </p>
                      ),
                      strong: ({ children }) => (
                        <strong style={{ color: 'var(--text-main)', fontWeight: 600 }}>{children}</strong>
                      ),
                      li: ({ children }) => (
                        <li style={{ color: 'var(--text-body)', marginBottom: '0.25rem' }}>{children}</li>
                      ),
                      code: ({ children, className }) => {
                        const isBlock = className?.includes('language-');
                        if (isBlock) {
                          return (
                            <code
                              className={className}
                              style={{
                                display: 'block',
                                background: 'var(--bg-surface)',
                                color: '#4ade80',
                                padding: '0.75rem 1rem',
                                borderRadius: '6px',
                                border: '0.5px solid var(--border)',
                                fontSize: '13px',
                                lineHeight: '1.7',
                                fontFamily: 'var(--font-mono, "JetBrains Mono", monospace)',
                                overflowX: 'auto',
                              }}
                            >
                              {children}
                            </code>
                          );
                        }
                        return (
                          <code
                            style={{
                              background: 'var(--bg-surface)',
                              color: '#4ade80',
                              padding: '1px 5px',
                              borderRadius: '4px',
                              fontSize: '12px',
                              fontFamily: 'var(--font-mono, "JetBrains Mono", monospace)',
                            }}
                          >
                            {children}
                          </code>
                        );
                      },
                      pre: ({ children }) => (
                        <pre
                          style={{
                            background: 'var(--bg-surface)',
                            border: '0.5px solid var(--border)',
                            borderRadius: '6px',
                            padding: '0.75rem 1rem',
                            overflowX: 'auto',
                            marginBottom: '0.75rem',
                          }}
                        >
                          {children}
                        </pre>
                      ),
                    }}
                  >
                    {message.content}
                  </ReactMarkdown>
                </div>
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div className="flex gap-3 justify-start items-center">
            <div
              className="flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center"
              style={{ background: 'var(--accent)' }}
            >
              <Loader2 className="w-3.5 h-3.5 text-white animate-spin" />
            </div>
            <div className="flex gap-1 items-center px-1 py-1">
              <span
                className="w-1.5 h-1.5 rounded-full animate-pulse"
                style={{ background: 'var(--text-muted)', animationDelay: '0ms' }}
              />
              <span
                className="w-1.5 h-1.5 rounded-full animate-pulse"
                style={{ background: 'var(--text-muted)', animationDelay: '150ms' }}
              />
              <span
                className="w-1.5 h-1.5 rounded-full animate-pulse"
                style={{ background: 'var(--text-muted)', animationDelay: '300ms' }}
              />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Error Message */}
      {error && (
        <div className="px-4 pb-2">
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
        </div>
      )}

      {/* Input Area */}
      <div
        className="flex-shrink-0 px-4 py-3"
        style={{
          borderTop: '0.5px solid var(--border)',
          background: 'var(--bg-sidebar)',
        }}
      >
        <div className="flex gap-2 items-end">
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
                ? 'You can still modify the plan...'
                : 'Pergunte sobre seus dados...'
            }
            rows={1}
            className="flex-1 px-3.5 py-2.5 rounded-xl text-[14px] resize-none leading-relaxed focus:outline-none"
            style={{
              background: 'var(--bg-surface)',
              border: '0.5px solid var(--border)',
              color: 'var(--text-main)',
            }}
            onFocus={(e) => {
              e.currentTarget.style.borderColor = 'var(--border-hi)';
            }}
            onBlur={(e) => {
              e.currentTarget.style.borderColor = 'var(--border)';
            }}
            disabled={
              loading ||
              (dataSourceType === 'csv' && !taskId && uploadedFiles.length === 0) ||
              taskStatus === 'executing' ||
              taskStatus === 'completed'
            }
          />
          <button
            onClick={handleSend}
            disabled={
              loading ||
              !input.trim() ||
              (dataSourceType === 'csv' && !taskId && uploadedFiles.length === 0) ||
              taskStatus === 'executing' ||
              taskStatus === 'completed'
            }
            className="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-lg transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            style={{
              background: 'var(--bg-surface2)',
              border: '0.5px solid var(--border)',
            }}
          >
            <ArrowUp className="w-4 h-4" style={{ color: 'var(--text-main)' }} />
          </button>
        </div>
      </div>
    </div>
  );
}
