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
      
      // Validate CSV files
      const invalidFiles = fileArray.filter(f => !f.name.toLowerCase().endsWith('.csv'));
      if (invalidFiles.length > 0) {
        setError(`Only CSV files are allowed: ${invalidFiles.map(f => f.name).join(', ')}`);
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

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    handleFiles(e.dataTransfer.files);
  }, [uploadedFiles]);

  return (
    <div className="space-y-3">
      {/* Drop Zone */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`relative border-2 border-dashed rounded-lg p-6 text-center transition-colors ${
          isDragging
            ? 'border-blue-500 bg-blue-900/30'
            : 'border-slate-700 bg-slate-800 hover:border-blue-500'
        }`}
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
            <Loader2 className="w-8 h-8 text-blue-400 animate-spin" />
            <p className="text-sm text-slate-300">Uploading files...</p>
          </div>
        ) : (
          <>
            <Upload className="w-10 h-10 mx-auto mb-3 text-slate-500" />
            <p className="text-sm text-slate-300 mb-1">
              <span className="font-medium text-blue-400">Click to upload</span> or drag and drop
            </p>
            <p className="text-xs text-slate-500">CSV files only (max 50MB per file)</p>
          </>
        )}
      </div>

      {/* Error Message */}
      {error && (
        <div className="bg-red-900/30 text-red-400 px-4 py-2 rounded-lg text-sm border border-red-800">
          {error}
        </div>
      )}

      {/* Uploaded Files List */}
      {uploadedFiles.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs font-medium text-slate-400 uppercase tracking-wide">
            Uploaded Files ({uploadedFiles.length})
          </div>
          {uploadedFiles.map((file) => (
            <div
              key={file.path}
              className="flex items-center justify-between gap-3 p-3 bg-slate-800 border border-slate-700 rounded-lg"
            >
              <div className="flex items-center gap-2 flex-1 min-w-0">
                <FileText className="w-4 h-4 text-blue-400 flex-shrink-0" />
                <span className="text-sm text-slate-200 truncate" title={file.name}>
                  {file.name}
                </span>
              </div>
              <button
                onClick={() => onRemoveFile(file.path)}
                className="p-1 hover:bg-slate-700 rounded transition"
                title="Remove file"
              >
                <X className="w-4 h-4 text-slate-400 hover:text-red-400" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
