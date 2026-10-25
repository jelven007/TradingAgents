import React, { useEffect, useId, useRef } from 'react';
import { label } from './api';

const paths = {
  grid: 'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
  task: 'M9 5h11M9 12h11M9 19h11M3 5h1M3 12h1M3 19h1',
  report: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h5',
  experiment: 'M9 3h6M10 3v6l-6 10a2 2 0 0 0 2 3h12a2 2 0 0 0 2-3L14 9V3M8 15h8',
  ops: 'M4 20V10M12 20V4M20 20v-7M2 20h20',
  settings: 'M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1zM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
  plus: 'M12 5v14M5 12h14',
  arrow: 'M5 12h14M14 7l5 5-5 5',
  chevron: 'M9 5l7 7-7 7',
  close: 'M6 6l12 12M6 18L18 6',
  refresh: 'M20 7v5h-5M4 17v-5h5M6 7a8 8 0 0 1 13-1l1 6M4 12l1 6a8 8 0 0 0 13-1',
  shield: 'M12 2l8 4v6c0 5-8 10-8 10S4 17 4 12V6zM8 12l3 3 5-6',
  link: 'M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2',
  menu: 'M4 6h16M4 12h16M4 18h16',
  check: 'M5 12l4 4L19 6',
  download: 'M12 3v12M7 10l5 5 5-5M4 17v4h16v-4',
  clock: 'M12 8v4l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
};

export function Icon({ name, size = 20 }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d={paths[name] || paths.report} />
  </svg>;
}

export function Button({ children, icon, secondary, danger, className = '', ...props }) {
  return <button className={`button ${secondary ? 'secondary' : ''} ${danger ? 'danger' : ''} ${className}`} {...props}>
    {icon ? <Icon name={icon} size={17} /> : null}{children}
  </button>;
}

export function Badge({ value }) {
  return <span className={`badge status-${value}`}>{label(value)}</span>;
}

export function Empty({ title, text, action, actionLabel, icon = 'report' }) {
  return <div className="empty">
    <div className="empty-icon"><Icon name={icon} size={32} /></div>
    <h3>{title}</h3><p>{text}</p>
    {action ? <button className="text-button" onClick={action}>{actionLabel}<Icon name="arrow" size={16} /></button> : null}
  </div>;
}

export function Field({ label: title, hint, children, wide, source, error }) {
  const id = useId();
  const controls = React.Children.map(children, child => {
    if (!React.isValidElement(child) || !['input', 'select', 'textarea'].includes(child.type)) return child;
    return React.cloneElement(child, {
      'aria-label': child.props['aria-label'] || (typeof title === 'string' ? title : undefined),
      'aria-describedby': [source ? `${id}-source` : '', hint ? `${id}-hint` : '', error ? `${id}-error` : ''].filter(Boolean).join(' ') || undefined,
      'aria-invalid': Boolean(error),
    });
  });
  return <label className={`field ${wide ? 'wide' : ''}`}>
    <span className="field-title">{title}{source ? <span className="field-source" id={`${id}-source`}>{source}</span> : null}</span>
    {controls}{hint ? <small id={`${id}-hint`}>{hint}</small> : null}
    {error ? <small id={`${id}-error`} className="field-error" role="alert">{error}</small> : null}
  </label>;
}

export function Modal({ title, subtitle, onClose, children, wide }) {
  const ref = useRef(null);
  useEffect(() => {
    const previous = document.activeElement;
    ref.current.showModal();
    const first = [...ref.current.querySelectorAll('input, select, textarea')].find(el =>
      !el.disabled && el.type !== 'file' && el.getClientRects().length);
    first?.focus();
    return () => {
      ref.current?.close();
      previous?.focus?.();
    };
  }, []);
  return <dialog ref={ref} className={`modal ${wide ? 'modal-wide' : ''}`}
    onCancel={event => { event.preventDefault(); onClose(); }}
    onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="modal-heading"><div><h2>{title}</h2>{subtitle ? <p>{subtitle}</p> : null}</div>
      <button className="icon-button" onClick={onClose} aria-label="关闭"><Icon name="close" /></button>
    </div>
    {children}
  </dialog>;
}

export function PageHeading({ title, description, children }) {
  return <div className="page-heading"><div><h1>{title}</h1><p>{description}</p></div>
    <div className="heading-actions">{children}</div>
  </div>;
}

export function Pager({ total, offset, onChange, count = 50 }) {
  if (total <= count) return null;
  return <div className="pager"><span>共 {total} 条 · {offset + 1}–{Math.min(total, offset + count)}</span>
    <Button secondary disabled={offset === 0} onClick={() => onChange(offset - count)}>上一页</Button>
    <Button secondary disabled={offset + count >= total} onClick={() => onChange(offset + count)}>下一页</Button>
  </div>;
}

export function Permission({ onBack }) {
  return <Empty icon="shield" title="当前账号未开放此页面" text="返回工作台查看当前账号可以使用的功能。"
    action={onBack} actionLabel="返回工作台" />;
}

export function ErrorLine({ error }) {
  return error ? <div className="error-message" role="alert">{error.message || error}
    {error.requestId ? <small>请求编号：{error.requestId}</small> : null}
  </div> : null;
}
