import { useEffect, useId, useRef } from 'react';

export default function FloorDialog({ title, onClose, children, actions }) {
  const ref = useRef(null), id = useId();
  useEffect(() => {
    const dialog = ref.current;
    const previousFocus = document.activeElement;
    dialog.showModal();
    return () => { dialog.close(); if (previousFocus?.isConnected) previousFocus.focus(); };
  }, []);
  return <dialog ref={ref} className="hf-dialog" aria-labelledby={id} onCancel={event => { event.preventDefault(); onClose(); }} onClick={event => { if (event.target === event.currentTarget) onClose(); }}><div className="hf-dialog-content"><header><h2 id={id}>{title}</h2><div className="hf-dialog-actions">{actions}<button className="hf-secondary" type="button" onClick={onClose}>Close</button></div></header>{children}</div></dialog>;
}
