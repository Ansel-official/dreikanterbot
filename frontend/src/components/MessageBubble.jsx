import { useMemo } from 'react'
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

export default function MessageBubble({ message, streaming }) {
  const toast = useToast()
  const isUser = message.role === 'user'
  const pending = message.status === 'streaming'
  const content = message.content || ''
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
          <Icon name="sparkles" size={16} />
        </div>
      ) : null}

      <div className="msg-main">
        <div className="msg-head">
          <span className="msg-author">{isUser ? '你' : 'DeepSeek'}</span>
          <time className="msg-time" dateTime={message.created_at || undefined}>
            {formatTime(message.created_at)}
          </time>
        </div>

        <div className={`bubble ${isUser ? 'bubble-user' : 'bubble-assistant'}`}>
          {isUser ? (
            <div className="user-text">{content}</div>
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
