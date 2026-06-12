import { Database, FileSpreadsheet } from 'lucide-react';

interface Props {
  onSelectSource: (type: 'csv' | 'database') => void;
}

export default function DataSourceSelector({ onSelectSource }: Props) {
  return (
    <div
      className="min-h-screen flex items-center justify-center p-4"
      style={{ background: 'var(--bg-page)' }}
    >
      <div className="max-w-xl w-full">
        <div className="text-center mb-10">
          <div className="flex items-center justify-center gap-3 mb-4">
            <div
              className="w-6 h-6 rounded-sm"
              style={{ background: 'var(--accent)' }}
            />
          </div>
          <h1
            className="text-[34px] font-medium mb-2 leading-tight tracking-tight"
            style={{ color: 'var(--text-main)' }}
          >
            Time Series Analysis Agent
          </h1>
          <p className="text-[15px] font-normal" style={{ color: 'var(--text-secondary)' }}>
            Choose your data source to get started
          </p>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <button
            onClick={() => onSelectSource('csv')}
            className="group flex flex-col items-center gap-3 p-8 rounded-xl transition-colors duration-150"
            style={{
              background: 'var(--bg-sidebar)',
              border: '0.5px solid var(--border)',
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLElement).style.background = 'var(--bg-surface)';
              (e.currentTarget as HTMLElement).style.borderColor = 'var(--border-hi)';
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLElement).style.background = 'var(--bg-sidebar)';
              (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)';
            }}
          >
            <FileSpreadsheet className="w-8 h-8" style={{ color: 'var(--text-secondary)' }} />
            <div>
              <div className="text-[16px] font-medium mb-1" style={{ color: 'var(--text-main)' }}>
                CSV File
              </div>
              <div className="text-[13px] font-normal" style={{ color: 'var(--text-secondary)' }}>
                Upload one or more CSV files for analysis
              </div>
            </div>
          </button>

          <button
            onClick={() => onSelectSource('database')}
            className="group flex flex-col items-center gap-3 p-8 rounded-xl transition-colors duration-150"
            style={{
              background: 'var(--bg-sidebar)',
              border: '0.5px solid var(--border)',
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLElement).style.background = 'var(--bg-surface)';
              (e.currentTarget as HTMLElement).style.borderColor = 'var(--border-hi)';
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLElement).style.background = 'var(--bg-sidebar)';
              (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)';
            }}
          >
            <Database className="w-8 h-8" style={{ color: 'var(--text-secondary)' }} />
            <div>
              <div className="text-[16px] font-medium mb-1" style={{ color: 'var(--text-main)' }}>
                Database
              </div>
              <div className="text-[13px] font-normal" style={{ color: 'var(--text-secondary)' }}>
                Connect to a database for analysis
              </div>
            </div>
          </button>
        </div>
      </div>
    </div>
  );
}
