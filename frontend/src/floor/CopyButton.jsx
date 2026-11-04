import { useEffect, useRef, useState } from 'react';
import { copyText } from './clipboard.js';
import './copyButton.css';

export default function CopyButton({ getText, label = 'Copy details' }) {
  const [status, setStatus] = useState(''), [error, setError] = useState('');
  const timer = useRef(), mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; clearTimeout(timer.current); }; }, []);
  async function copy() {
    clearTimeout(timer.current); setStatus('copying'); setError('');
    try {
      await copyText(getText());
      if (!mounted.current) return;
      setStatus('copied'); timer.current = setTimeout(() => { if (mounted.current) setStatus(''); }, 1600);
    } catch (failure) { if (mounted.current) { setStatus(''); setError(failure.message); } }
  }
  return <span className="hf-copy-control"><button type="button" className="hf-secondary hf-copy-button" disabled={status === 'copying'} onClick={copy}>{status === 'copied' ? 'Copied' : status === 'copying' ? 'Copying…' : label}</button><span className="hf-copy-announcement" role="status">{status === 'copied' ? 'Copied to clipboard.' : ''}</span>{error && <span className="hf-copy-error" role="alert">Copy failed: {error}. Try the copy button again.</span>}</span>;
}
