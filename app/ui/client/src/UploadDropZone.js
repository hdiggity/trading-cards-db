import React, { useState, useCallback } from 'react';
import './UploadDropZone.css';

function UploadDropZone({ onUploadComplete }) {
  const [isDragOver, setIsDragOver] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState(null);

  const supportedFormats = [
    'image/jpeg',
    'image/jpg', 
    'image/png',
    'image/heic',
    'image/heif',
    'image/webp',
    'image/tiff',
    'image/bmp'
  ];

  const supportedExtensions = ['.jpg', '.jpeg', '.png', '.heic', '.heif', '.webp', '.tiff', '.tif', '.bmp'];

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  }, []);

  const validateFile = (file) => {
    // Check file type
    if (!supportedFormats.includes(file.type) && !supportedExtensions.some(ext => 
      file.name.toLowerCase().endsWith(ext))) {
      return { valid: false, error: `Unsupported file format: ${file.name}` };
    }

    // Check file size (50MB limit)
    const maxSize = 50 * 1024 * 1024; // 50MB
    if (file.size > maxSize) {
      return { valid: false, error: `File too large: ${file.name} (max 50MB)` };
    }

    return { valid: true };
  };

  const uploadFiles = async (files) => {
    setIsUploading(true);
    setUploadStatus(null);

    const validFiles = [];
    const errors = [];

    // Validate all files first
    for (const file of files) {
      const validation = validateFile(file);
      if (validation.valid) {
        validFiles.push(file);
      } else {
        errors.push(validation.error);
      }
    }

    if (errors.length > 0) {
      setUploadStatus({ 
        success: false, 
        message: `Validation errors:\n${errors.join('\n')}` 
      });
      setIsUploading(false);
      return;
    }

    if (validFiles.length === 0) {
      setUploadStatus({ 
        success: false, 
        message: 'No valid files to upload' 
      });
      setIsUploading(false);
      return;
    }

    try {
      const formData = new FormData();
      validFiles.forEach((file) => {
        formData.append('images', file);
      });

      const response = await fetch('http://localhost:3001/api/upload-raw-scans', {
        method: 'POST',
        body: formData,
      });

      const result = await response.json();

      if (response.ok) {
        setUploadStatus({
          success: true,
          message: `Successfully uploaded ${validFiles.length} file(s) to raw scans folder`
        });
        
        // Call callback if provided
        if (onUploadComplete) {
          onUploadComplete(validFiles.length);
        }
      } else {
        setUploadStatus({
          success: false,
          message: result.error || 'Upload failed'
        });
      }
    } catch (error) {
      console.error('Upload error:', error);
      setUploadStatus({
        success: false,
        message: `Upload failed: ${error.message}`
      });
    }

    setIsUploading(false);
  };

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);

    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) {
      uploadFiles(files);
    }
  }, []);

  const handleFileInput = (e) => {
    const files = Array.from(e.target.files);
    if (files.length > 0) {
      uploadFiles(files);
    }
    // Reset input
    e.target.value = '';
  };

  const handleClick = () => {
    document.getElementById('file-input').click();
  };

  return (
    <div className="upload-drop-zone-container">
      <div
        className={`upload-drop-zone ${isDragOver ? 'drag-over' : ''} ${isUploading ? 'uploading' : ''}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleClick}
      >
        <input
          id="file-input"
          type="file"
          multiple
          accept={supportedExtensions.join(',')}
          onChange={handleFileInput}
          style={{ display: 'none' }}
        />
        
        <div className="upload-content">
          {isUploading ? (
            <>
              <div className="upload-spinner"></div>
              <h3>uploading files...</h3>
              <p>please wait while files are copied to raw scans folder</p>
            </>
          ) : (
            <>
              <div className="upload-icon">⬆</div>
              <h3>drop photos here</h3>
              <p>or click to browse files</p>
              <div className="supported-formats">
                <span>supported formats: jpg, png, heic, webp, tiff, bmp</span>
                <span>max size: 50mb per file</span>
              </div>
            </>
          )}
        </div>
      </div>

      {uploadStatus && (
        <div className={`upload-status ${uploadStatus.success ? 'success' : 'error'}`}>
          <div className="status-message">
            {uploadStatus.message}
          </div>
          <button 
            className="status-close"
            onClick={() => setUploadStatus(null)}
          >
            ×
          </button>
        </div>
      )}
    </div>
  );
}

export default UploadDropZone;