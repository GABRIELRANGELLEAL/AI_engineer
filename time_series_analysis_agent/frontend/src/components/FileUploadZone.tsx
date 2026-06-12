import { useCallback, useState } from 'react';
import { Upload, X, FileText, Loader2 } from 'lucide-react';
import { uploadCsvFiles } from '../api';
import type { UploadedFile } from '../types';

interface Props {
  onFilesUploaded: (files: UploadedFile[]) => void;
  uploadedFiles: UploadedFile[];
  onRemoveFile: (path: string) => void;
}

export default function FileUploadZone({ onFilesUploaded, uploadedFiles, onRemoveFile }: Props) {
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;

    setUploading(true);
    setError(null);

    try {
      const fileArray = Array.from(files);

      const invalidFiles = fileArray.filter((f) => !f.name.toLowerCase().endsWith('.csv'));
      if (invalidFiles.length > 0) {
        setError(`Only CSV files are allowed: ${invalidFiles.map((f) => f.name).join(', ')}`);
        setUploading(false);
        return;
      }

      const newFiles = await uploadCsvFiles(fileArray);
      onFilesUploaded([...uploadedFiles, ...newFiles]);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to upload files');
    } finally {
      setUploading(false);
    }
  };

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      handleFiles(e.dataTransfer.files);
    },
    [uploadedFiles]
  );

  return (
    <div className="space-y-3">
      {/* Drop Zone */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className="relative rounded-lg p-6 text-center transition-colors"
        style={{
          border: isDragging
            ? '1.5px dashed #2563eb'
            : '1.5px dashed var(--border-hi)',
          background: isDragging ? 'rgba(37,99,235,0.08)' : 'var(--bg-surface)',
        }}
      >
        <input
          type="file"
          multiple
          accept=".csv"
          onChange={(e) => handleFiles(e.target.files)}
          className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
          disabled={uploading}
        />

        {uploading ? (
          <div className="flex flex-col items-center gap-2">
            <Loader2 className="w-8 h-8 animate-spin" style={{ color: '#2563eb' }} />
            <p className="text-sm" style={{ color: 'var(--text-body)' }}>
              Uploading files...
            </p>
          </div>
        ) : (
          <>
            <Upload className="w-10 h-10 mx-auto mb-3" style={{ color: 'var(--text-muted)' }} />
            <p className="text-sm mb-1" style={{ color: 'var(--text-body)' }}>
              <span style={{ fontWeight: 500, color: '#60a5fa' }}>Click to upload</span> or drag and drop
            </p>
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
              CSV files only (max 50MB per file)
            </p>
          </>
        )}
      </div>

      {/* Error Message */}
      {error && (
        <div
          className="px-4 py-2 rounded-lg text-sm"
          style={{
            color: '#f87171',
            border: '0.5px solid #7f1d1d',
            background: 'rgba(127,29,29,0.15)',
          }}
        >
          {error}
        </div>
      )}

      {/* Uploaded Files List */}
      {uploadedFiles.length > 0 && (
        <div className="space-y-2">
          <div
            className="text-xs font-medium uppercase tracking-wide"
            style={{ color: 'var(--text-secondary)' }}
          >
            Uploaded Files ({uploadedFiles.length})
          </div>
          {uploadedFiles.map((file) => (
            <div
              key={file.path}
              className="flex items-center justify-between gap-3 p-3 rounded-lg"
              style={{
                background: 'var(--bg-surface2)',
                border: '0.5px solid var(--border)',
              }}
            >
              <div className="flex items-center gap-2 flex-1 min-w-0">
                <FileText className="w-4 h-4 flex-shrink-0" style={{ color: '#60a5fa' }} />
                <span className="text-sm truncate" style={{ color: 'var(--text-main)' }} title={file.name}>
                  {file.name}
                </span>
              </div>
              <button
                onClick={() => onRemoveFile(file.path)}
                className="p-1 rounded transition-colors"
                title="Remove file"
                style={{ color: 'var(--text-secondary)' }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLElement).style.color = '#f87171';
                  (e.currentTarget as HTMLElement).style.background = 'var(--bg-hover)';
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLElement).style.color = 'var(--text-secondary)';
                  (e.currentTarget as HTMLElement).style.background = 'transparent';
                }}
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
