import { Database, FileSpreadsheet } from 'lucide-react';

interface Props {
  onSelectSource: (type: 'csv' | 'database') => void;
}

export default function DataSourceSelector({ onSelectSource }: Props) {
  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-slate-950">
      <div className="max-w-2xl w-full">
        <div className="text-center mb-12">
          <h1 className="text-5xl font-bold text-slate-100 mb-4">
            Time Series Analysis Agent
          </h1>
          <p className="text-slate-400 text-lg">
            Choose your data source to get started
          </p>
        </div>

        <div className="grid grid-cols-2 gap-6">
          <button
            onClick={() => onSelectSource('csv')}
            className="group p-10 rounded-2xl border-2 border-slate-700 bg-slate-900 hover:border-blue-500 hover:bg-slate-800 transition-all duration-200 transform hover:scale-105"
          >
            <FileSpreadsheet className="w-16 h-16 mx-auto mb-4 text-slate-400 group-hover:text-blue-500 transition-colors" />
            <div className="font-semibold text-xl text-slate-100 mb-2">
              CSV File
            </div>
            <div className="text-sm text-slate-400">
              Upload one or more CSV files for analysis
            </div>
          </button>

          <button
            onClick={() => onSelectSource('database')}
            className="group p-10 rounded-2xl border-2 border-slate-700 bg-slate-900 hover:border-blue-500 hover:bg-slate-800 transition-all duration-200 transform hover:scale-105"
          >
            <Database className="w-16 h-16 mx-auto mb-4 text-slate-400 group-hover:text-blue-500 transition-colors" />
            <div className="font-semibold text-xl text-slate-100 mb-2">
              Database
            </div>
            <div className="text-sm text-slate-400">
              Connect to a database for analysis
            </div>
          </button>
        </div>
      </div>
    </div>
  );
}
