export async function copyText(text, { navigatorObject = globalThis.navigator, documentObject = globalThis.document } = {}) {
  if (navigatorObject?.clipboard?.writeText) return navigatorObject.clipboard.writeText(text);
  const field = documentObject.createElement('textarea');
  field.value = text;
  field.style.position = 'fixed'; field.style.opacity = '0';
  // Native modal dialogs make the rest of the document inert; keep fallback selection inside the active dialog.
  const host = documentObject.querySelector?.('dialog[open]') || documentObject.body;
  const previousFocus = documentObject.activeElement;
  host.appendChild(field); field.select();
  try { if (!documentObject.execCommand('copy')) throw new Error('Could not copy to clipboard'); }
  finally { field.remove(); if (previousFocus?.isConnected) previousFocus.focus(); }
}
