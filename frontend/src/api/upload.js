import { apiFetchFormData } from './client';

// One POST /upload per file (each returns a per-image success/failure state
// in the UI). The backend reads a single multipart field named `file`.
async function uploadImage(file) {
  const formData = new FormData();
  formData.append('file', file);

  return apiFetchFormData('/upload', formData);
}

// Upload one or more images. Returns an array of backend responses in the
// same order as the input files.
export async function uploadImages(files) {
  return Promise.all(files.map(uploadImage));
}

export async function uploadTicketScreenshotBatch(files) {
  const formData = new FormData();
  files.forEach((file) => formData.append('files', file));
  return apiFetchFormData('/upload/tickets', formData);
}

export async function uploadDocketImageBatch(files) {
  const formData = new FormData();
  files.forEach((file) => formData.append('files', file));
  return apiFetchFormData('/upload/dockets', formData);
}

// Upload the two reference sources for one branch + day in a single request,
// because the backend cross-verifies the slip against the Excel log before it
// stores anything.
//   imageFile  Source 1 - the long slip bill (printed Work Period Report)
//   excelFile  Source 2 - the Excel "Daily Exception Report" (.xlsx)
// Either may be null. On success returns the stored report record; on a 409
// mismatch it returns the structured disagreement so the operator can choose a
// source, so this call reads the body itself rather than going through
// apiFetchFormData (which flattens a structured `detail` into a string).
export async function uploadSalesReport(imageFile, excelFile, restaurant, reportDate, confirm) {
  const formData = new FormData();
  if (imageFile) {
    formData.append('file', imageFile);
  }
  if (excelFile) {
    formData.append('excel_file', excelFile);
  }
  if (restaurant && restaurant.trim()) {
    formData.append('restaurant', restaurant.trim());
  }
  if (reportDate && reportDate.trim()) {
    formData.append('report_date', reportDate.trim());
  }
  if (confirm && confirm.trim()) {
    formData.append('confirm', confirm.trim());
  }

  const response = await fetch('/api/upload/sales-reports', { method: 'POST', body: formData });
  const body = await response.json().catch(() => null);

  if (response.status === 409 && body && body.detail) {
    return { conflict: body.detail };
  }
  if (!response.ok) {
    const detail = body && body.detail;
    throw new Error(
      typeof detail === 'string' ? detail : (detail ? JSON.stringify(detail) : response.statusText)
    );
  }
  return body;
}