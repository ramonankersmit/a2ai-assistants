import './styles.css';

// Load bd-app defensively so we never end up with a silent white screen if bd-app.js fails during module eval.
function _escapeHtml(s) {
  return String(s)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function _showLoadError(e) {
  // Keep this extremely simple and dependency-free.
  const msg = (e && (e.stack || e.message)) ? (e.stack || e.message) : String(e);
  // eslint-disable-next-line no-console
  console.error('Web-shell load error (bd-app.js)', e);

  document.body.innerHTML = `
    <div style="padding:16px;font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
      <div style="max-width:960px;margin:0 auto;border:1px solid #e5e7eb;border-radius:14px;background:#fff;box-shadow:0 6px 18px rgba(0,0,0,0.06);">
        <div style="padding:16px 18px;border-bottom:1px solid #e5e7eb;">
          <div style="font-size:18px;font-weight:650;">Web-shell error</div>
          <div style="margin-top:6px;color:#6b7280;font-size:13px;">
            bd-app.js kon niet geladen worden. Dit is meestal een runtime error tijdens module-evaluatie.
            Kopieer de fout hieronder en plak die in de chat.
          </div>
        </div>
        <div style="padding:16px 18px;">
          <pre style="white-space:pre-wrap;background:#f3f4f6;border-radius:10px;padding:12px;margin:0;">${_escapeHtml(msg)}</pre>
          <div style="margin-top:10px;color:#6b7280;font-size:13px;">
            Tip: open DevTools Console voor de volledige stacktrace.
          </div>
        </div>
      </div>
    </div>
  `;
}

// Also surface runtime errors (after successful import) in the DOM.
window.addEventListener('error', (ev) => {
  // eslint-disable-next-line no-console
  console.error('Runtime error', ev.error || ev.message);
});
window.addEventListener('unhandledrejection', (ev) => {
  // eslint-disable-next-line no-console
  console.error('Unhandled promise rejection', ev.reason);
});

(async () => {
  try {
    await import('./shell/bd-app.js');
  } catch (e) {
    _showLoadError(e);
  }
})();
