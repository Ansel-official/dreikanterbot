import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import Icon from './Icons'

export default function Modal({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
  size = 'md',
  closeOnOverlay = true,
}) {
  useEffect(() => {
    if (!open) return undefined
    const handler = (event) => {
      if (event.key === 'Escape') onClose?.()
    }
    document.addEventListener('keydown', handler)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', handler)
      document.body.style.overflow = previous
    }
  }, [open, onClose])

  if (!open) return null

  return createPortal(
    <div className="modal-root">
      <div
        className="modal-overlay"
        onMouseDown={(event) => {
          if (closeOnOverlay && event.target === event.currentTarget) onClose?.()
        }}
      />
      <div className={`modal modal-${size}`} role="dialog" aria-modal="true" aria-label={title}>
        <header className="modal-header">
          <div>
            <h2>{title}</h2>
            {subtitle ? <p className="modal-subtitle">{subtitle}</p> : null}
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="关闭">
            <Icon name="x" size={19} />
          </button>
        </header>
        <div className="modal-body">{children}</div>
        {footer ? <footer className="modal-footer">{footer}</footer> : null}
      </div>
    </div>,
    document.body
  )
}
