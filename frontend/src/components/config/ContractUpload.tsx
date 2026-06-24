import { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { Upload, FileText } from 'lucide-react'
import { Label } from '@/components/ui/label'

interface ContractUploadProps {
  contractText: string
  fileName: string
  onFile: (text: string, name: string) => void
}

export function ContractUpload({ contractText, fileName, onFile }: ContractUploadProps) {
  const onDrop = useCallback(
    (acceptedFiles: File[]) => {
      const file = acceptedFiles[0]
      if (!file) return
      const reader = new FileReader()
      reader.onload = e => onFile((e.target?.result as string) ?? '', file.name)
      reader.readAsText(file)
    },
    [onFile],
  )

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'text/plain': ['.txt'] },
    multiple: false,
  })

  return (
    <div className="space-y-2">
      <Label>Contract File</Label>
      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
          isDragActive
            ? 'border-primary bg-primary/5'
            : 'border-border hover:border-primary/50'
        }`}
      >
        <input {...getInputProps()} />
        <Upload className="mx-auto mb-2 text-muted-foreground" size={24} />
        {fileName ? (
          <p className="text-sm flex items-center justify-center gap-1.5">
            <FileText size={14} />
            {fileName}
          </p>
        ) : (
          <p className="text-sm text-muted-foreground">
            {isDragActive
              ? 'Drop the file here'
              : 'Drag and drop a .txt file, or click to browse'}
          </p>
        )}
      </div>
      {contractText && (
        <textarea
          readOnly
          value={contractText}
          rows={6}
          className="w-full text-xs font-mono p-2 rounded-md border bg-muted resize-none"
        />
      )}
    </div>
  )
}
