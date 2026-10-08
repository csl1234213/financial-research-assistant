import Uppy from '@uppy/core';
import Tus from '@uppy/tus';
import { authenticatedGateway, verifyReselectedPdf } from './resumableUploadContract.ts';

export interface ResumableUploadOptions {
  uploadId: string;
  gatewayUrl: string;
  origin: string;
  getToken: () => string | null;
  onProgress: (uploaded: number, total: number) => void;
  /** Authoritative values from the authenticated upload session. */
  expectedSize: number;
  expectedSha256: string;
  /** Set only after the server confirms a transport resource already exists. */
  existingResource?: boolean;
}

/** Headless standard transport. Upload completion is NOT document readiness. */
export function createResumableUpload(options: ResumableUploadOptions) {
  const gateway = new URL(authenticatedGateway(options.uploadId, options.gatewayUrl, options.origin));
  const uppy = new Uppy({
    autoProceed: false,
    restrictions: { maxNumberOfFiles: 1, maxFileSize: 50 * 1024 * 1024, allowedFileTypes: ['.pdf'] },
  });
  uppy.use(Tus, {
    endpoint: gateway.href,
    uploadUrl: options.existingResource === true ? gateway.href : undefined,
    limit: 1,
    chunkSize: 1024 * 1024,
    retryDelays: [0, 1000, 3000],
    allowedMetaFields: [],
    // Do not persist authenticated URLs under an unscoped file fingerprint.
    storeFingerprintForResuming: false,
    onBeforeRequest(request) {
      if (new URL(request.getURL(), options.origin).href !== gateway.href) {
        throw new Error('Unexpected upload resource URL');
      }
      const token = options.getToken();
      if (!token) throw new Error('Authentication required');
      request.setHeader('Authorization', `Bearer ${token}`);
    },
  });
  uppy.on('upload-progress', (_file, progress) => {
    options.onProgress(progress.bytesUploaded ?? 0, progress.bytesTotal ?? 0);
  });
  // Keep raw addFile private: a resumed resource must never receive bytes from
  // a different local file, even when its name and size happen to match.
  return {
    async selectFile(file: File) {
      await verifyReselectedPdf(file, options.expectedSize, options.expectedSha256);
      return uppy.addFile({ name: file.name, type: file.type, data: file });
    },
    upload: () => uppy.upload(),
    cancel: () => uppy.cancelAll(),
    destroy: () => uppy.destroy(),
  };
}
