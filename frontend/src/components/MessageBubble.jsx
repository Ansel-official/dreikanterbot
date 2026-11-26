import { useEffect, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import Icon from './Icons'
import { useToast } from './Toast'
import { copyText, formatTime } from '../utils'

function extractText(node) {
  if (node == null || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(extractText).join('')
  if (typeof node === 'object' && node.props) return extractText(node.props.children)
  return ''
}

function formatFileSize(bytes) {
  if (!bytes) return ''
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

function CodeBlock({ children }) {
  const toast = useToast()
  const code = extractText(children).replace(/\n$/, '')

  const copy = async () => {
    const ok = await copyText(code)
    toast(ok ? '代码已复制' : '复制失败，请手动选择', ok ? 'success' : 'error')
  }

  return (
    <div className="code-block">
      <div className="code-head">
        <span>代码</span>
        <button type="button" className="code-copy" onClick={copy}>
          <Icon name="copy" size={13} />
          复制
        </button>
      </div>
      <pre>{children}</pre>
    </div>
  )
}

const markdownComponents = {
  pre: CodeBlock,
  a: ({ node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
  table: ({ node, ...props }) => (
    <div className="table-wrap">
      <table {...props} />
    </div>
  ),
  img: ({ node, alt, ...props }) => (
    <img {...props} alt={alt || ''} loading="lazy" referrerPolicy="no-referrer" />
  ),
}

function StatusNote({ message }) {
  if (message.status === 'sending') {
    return (
      <span className="msg-status">
        <span className="spinner spinner-xs" /> 发送中
      </span>
    )
  }
  if (message.status === 'failed') {
    return (
      <span className="msg-status msg-status-error">
        <Icon name="alert" size={12} /> 发送失败
      </span>
    )
  }
  if (message.status === 'error') {
    return (
      <span className="msg-status msg-status-error">
        <Icon name="alert" size={12} /> 生成失败
      </span>
    )
  }
  if (message.status === 'stopped') {
    return <span className="msg-status">已停止生成</span>
  }
  return null
}

function ReasoningPanel({ message, pending }) {
  const reasoning = message.reasoning || ''
  const live = Boolean(message.reasoningLive) || (pending && !message.content)
  const [expanded, setExpanded] = useState(false)
  const [progress, setProgress] = useState(live ? 8 : 100)

  useEffect(() => {
    if (!live) {
      setProgress(100)
      return undefined
    }
    setProgress((value) => Math.max(8, value))
    const timer = setInterval(() => {
      setProgress((value) => {
        if (value >= 94) return 94
        const step = Math.max(0.7, (94 - value) * 0.07)
        return Math.min(94, value + step)
      })
    }, 420)
    return () => clearInterval(timer)
  }, [live])

  useEffect(() => {
    if (reasoning.length) {
      setProgress((value) => {
        const estimated = Math.min(92, 12 + Math.log2(reasoning.length + 2) * 7)
        return Math.max(value, estimated)
      })
    }
  }, [reasoning.length])

  const elapsed = message.reasoningElapsedMs
    ? `${(message.reasoningElapsedMs / 1000).toFixed(1)} 秒`
    : message.reasoningStartedAt
      ? `${Math.max(1, Math.round((Date.now() - message.reasoningStartedAt) / 1000))} 秒`
      : ''

  if (!reasoning && !live) return null

  return (
    <div className={`reasoning-panel ${live ? 'is-live' : 'is-done'} ${expanded ? 'expanded' : ''}`}>
      <button
        type="button"
        className="reasoning-head"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
      >
        <span className="reasoning-title">
          <span className={`reasoning-orb ${live ? 'pulse' : ''}`}>
            <Icon name="brain" size={13} />
          </span>
          {live ? '正在推理' : '推理过程'}
          {elapsed ? <span className="reasoning-time">{elapsed}</span> : null}
        </span>
        <Icon name={expanded ? 'chevronDown' : 'chevronRight'} size={15} />
      </button>
      <div className="reasoning-progress" aria-hidden="true">
        <span style={{ width: `${Math.round(progress)}%` }} />
      </div>
      <div className={`reasoning-body ${expanded || live ? 'show' : ''}`}>
        <pre>{reasoning || '模型正在组织推理过程…'}</pre>
      </div>
    </div>
  )
}

export default function MessageBubble({ message, streaming }) {
  const toast = useToast()
  const isUser = message.role === 'user'
  const pending = message.status === 'streaming'
  const content = message.content || ''
  const attachments = Array.isArray(message.attachments) ? message.attachments : []
  const markdown = useMemo(
    () => (
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {content}
      </ReactMarkdown>
    ),
    [content]
  )

  const copy = async () => {
    if (!content) return
    const ok = await copyText(content)
    toast(ok ? '已复制消息' : '复制失败，请手动选择', ok ? 'success' : 'error')
  }

  return (
    <article className={`msg-row ${isUser ? 'msg-user' : 'msg-assistant'}`}>
      {!isUser ? (
        <div className="msg-avatar" aria-hidden="true">
          <span>D</span>
        </div>
      ) : null}

      <div className="msg-main">
        <div className="msg-head">
          <span className="msg-author">{isUser ? '你' : 'Dreikanterbot'}</span>
          {!isUser && message.mode === 'reasoner' ? <span className="msg-mode">R1</span> : null}
          <time className="msg-time" dateTime={message.created_at || undefined}>
            {formatTime(message.created_at)}
          </time>
        </div>

        {!isUser && (message.mode === 'reasoner' || message.reasoning) ? (
          <ReasoningPanel message={message} pending={pending} />
        ) : null}

        <div className={`bubble ${isUser ? 'bubble-user' : 'bubble-assistant'}`}>
          {attachments.length ? (
            <div className="message-attachments">
              {attachments.map((item, index) => (
                <div className="message-attachment" key={`${item.name}-${index}`}>
                  <Icon name="fileText" size={14} />
                  <span>{item.name}</span>
                  <small>{formatFileSize(item.size)}</small>
                </div>
              ))}
            </div>
          ) : null}

          {isUser ? (
            content ? <div className="user-text">{content}</div> : null
          ) : content ? (
            <div className="markdown">{markdown}</div>
          ) : pending ? (
            <div className="typing" aria-label="正在思考">
              <span />
              <span />
              <span />
            </div>
          ) : (
            <div className="empty-reply">（无内容）</div>
          )}

          {streaming && content ? <span className="stream-cursor" aria-hidden="true" /> : null}
        </div>

        <div className="msg-foot">
          <StatusNote message={message} />
          {content ? (
            <button type="button" className="msg-action" onClick={copy} title="复制这条消息">
              <Icon name="copy" size={13} />
              复制
            </button>
          ) : null}
          {message.usage?.total_tokens ? (
            <span className="msg-tokens">{message.usage.total_tokens} tokens</span>
          ) : null}
        </div>
      </div>
    </article>
  )
}
