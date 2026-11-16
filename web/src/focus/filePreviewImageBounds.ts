export const IMAGE_PREVIEW_PIXELS = 24_000_000;

export function checkPreviewImageSize(width: number, height: number): void {
  if (!(Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0)) {
    throw new Error('focus.filePreviewImageInvalid');
  }
  if (width * height > IMAGE_PREVIEW_PIXELS || width > 32768 || height > 32768) {
    throw new Error('focus.filePreviewImageTooLarge');
  }
}
