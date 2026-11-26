import { useLayoutEffect, useRef, useState } from 'react'
import api, { errorMessage } from '../api/client'
import Icon from './Icons'
import { useToast } from './Toast'
import { useMediaRecorder } from '../hooks/useMediaRecorder'
import { formatContextWindow, makeClientId } from '../utils'

const MAX_FILES = 10
const MAX_FILE_MB = 100

function formatClock(seconds) {
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`
}

function formatFileSize(bytes) {
  if (!bytes) return '0 KB'
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

export default function Composer({
  onSend,
  onStop,
  streaming,
  connectionStatus,
  quota,
  mode,
  onModeChange,
  aiReady = true,
  onOpenAi,
  plugins = [],
  contextWindow = 128000,
  showKeyNotice = true,
}) {
  const toast = useToast()
  const [text, setText] = useState('')
  const [attachments, setAttachments] = useState([])
  const [dragOver, setDragOver] = useState(false)
  const textareaRef = useRef(null)
  const fileInputRef = useRef(null)

  const { supported, recording, uploading, seconds, start, stop, cancel, maxSeconds } =
    useMediaRecorder({
      onTranscribed: (transcript) => {
        setText((current) => (current.trim() ? `${current.trim()}\n${transcript}` : transcript))
        toast('语音已转文字', 'success')
        requestAnimationFrame(() => textareaRef.current?.focus())
      },
      onError: (message) => toast(message, 'error'),
    })

  useLayoutEffect(() => {
    const element = textareaRef.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 220)}px`
  }, [text])

  const connected = connectionStatus === 'connected'
  const extracting = attachments.some((item) => item.loading)
  const readyAttachments = attachments.filter((item) => !item.loading && !item.error)
  const canSend =
    connected &&
    aiReady &&
    !streaming &&
    !recording &&
    !uploading &&
    !extracting &&
    (text.trim().length > 0 || readyAttachments.length > 0)
  const lowQuota = quota && quota.limit != null && quota.remaining <= 10
  const promptPlugins = (plugins || [])
    .filter((plugin) => plugin.enabled)
    .flatMap((plugin) =>
      (plugin.prompts || []).map((prompt) => ({
        ...prompt,
        pluginName: plugin.name,
      }))
    )
    .slice(0, 30)

  const usePluginPrompt = (prompt) => {
    setText((current) => (current.trim() ? `${current.trim()}\n\n${prompt.prompt}` : prompt.prompt))
    if (prompt.mode === 'reasoner' && mode !== 'reasoner') onModeChange?.('reasoner')
    requestAnimationFrame(() => textareaRef.current?.focus())
  }

  const uploadFile = async (file) => {
    const id = makeClientId()
    const item = {
      id,
      name: file.name || '附件',
      size: file.size,
      mime: file.type || null,
      text: '',
      text_chars: 0,
      note: null,
      loading: true,
      error: false,
    }
    setAttachments((current) => [...current, item])
    const form = new FormData()
    form.append('file', file, file.name || 'attachment')
    try {
      const response = await api.post('/files/extract', form, { timeout: 120000 })
      setAttachments((current) =>
        current.map((candidate) =>
          candidate.id === id
            ? {
                ...candidate,
                ...response.data,
                loading: false,
                error: false,
              }
            : candidate
        )
      )
      if (response.data.note) toast(`${file.name}：${response.data.note}`, 'info')
    } catch (error) {
      setAttachments((current) =>
        current.map((candidate) =>
          candidate.id === id ? { ...candidate, loading: false, error: true } : candidate
        )
      )
      toast(errorMessage(error, `${file.name} 解析失败`), 'error')
    }
  }

  const addFiles = (fileList) => {
    const files = Array.from(fileList || [])
    if (!files.length) return
    const remaining = MAX_FILES - attachments.length
    if (remaining <= 0) {
      toast(`单条消息最多 ${MAX_FILES} 个文件`, 'warning')
      return
    }
    files.slice(0, remaining).forEach((file) => {
      if (file.size > MAX_FILE_MB * 1024 * 1024) {
        toast(`${file.name} 超过 ${MAX_FILE_MB}MB，已跳过`, 'error')
        return
      }
      uploadFile(file)
    })
    if (files.length > remaining) toast(`最多 ${MAX_FILES} 个文件，多余文件已忽略`, 'warning')
  }

  const removeAttachment = (id) => {
    setAttachments((current) => current.filter((item) => item.id !== id))
  }

  const submit = () => {
    const value = text.trim()
    if (!canSend) return
    const payload = readyAttachments.map((item) => ({
      name: item.name,
      size: item.size,
      mime: item.mime,
      text: item.text || '',
      text_chars: item.text_chars || 0,
      note: item.note || null,
    }))
    const result = onSend?.(value, payload)
    if (result !== false) {
      setText('')
      setAttachments([])
      requestAnimationFrame(() => {
        const element = textareaRef.current
        if (element) {
          element.style.height = 'auto'
          element.focus()
        }
      })
    }
  }

  const handleKeyDown = (event) => {
    if (event.key !== 'Enter' || event.shiftKey) return
    if (event.nativeEvent?.isComposing || event.isComposing) return
    event.preventDefault()
    submit()
  }

  const toggleRecording = () => {
    if (uploading) return
    if (recording) stop()
    else start()
  }

  const handleDrop = (event) => {
    event.preventDefault()
    setDragOver(false)
    if (event.dataTransfer?.files?.length) addFiles(event.dataTransfer.files)
  }

  const handlePaste = (event) => {
    const files = event.clipboardData?.files
    if (files?.length) {
      event.preventDefault()
      addFiles(files)
    }
  }

  return (
    <div
      className={`composer-wrap ${dragOver ? 'is-dragging' : ''}`}
      onDragOver={(event) => {
        event.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={(event) => {
        if (event.currentTarget === event.target) setDragOver(false)
      }}
      onDrop={handleDrop}
    >
      <div className="composer-inner">
        {!connected ? (
          <div className={`composer-notice ${connectionStatus === 'connecting' ? 'connecting' : ''}`}>
            <span className="notice-dot" />
            {connectionStatus === 'connecting'
              ? '正在连接服务器…'
              : connectionStatus === 'unauthorized'
                ? '登录状态失效，请刷新页面重新登录'
                : '连接已断开，正在自动重连…'}
          </div>
        ) : null}

        {connected && !aiReady && showKeyNotice ? (
          <div className="composer-notice key-required">
            <Icon name="key" size={14} />
            <span>需要先接入模型 API Key</span>
            <button type="button" className="inline-link" onClick={onOpenAi}>
              去接入
            </button>
          </div>
        ) : null}

        {lowQuota ? (
          <div className="composer-notice quota-warning">
            <Icon name="alert" size={13} /> 今日额度仅剩 {quota.remaining} 次
          </div>
        ) : null}

        <div className={`composer ${recording ? 'is-recording' : ''}`}>
          <div className="composer-modebar">
            <div className="mode-switch" role="group" aria-label="对话模式">
              <button
                type="button"
                className={mode === 'chat' ? 'active' : ''}
                onClick={() => onModeChange?.('chat')}
                disabled={streaming}
              >
                <Icon name="zap" size={14} />
                快速回答
              </button>
              <button
                type="button"
                className={mode === 'reasoner' ? 'active' : ''}
                onClick={() => onModeChange?.('reasoner')}
                disabled={streaming}
              >
                <Icon name="brain" size={14} />
                深度思考
              </button>
            </div>
            <span className="mode-hint">
              {mode === 'reasoner'
                ? '先推理，再给结论'
                : `${formatContextWindow(contextWindow)} 上下文 · 快速回答`}
            </span>
          </div>

          {attachments.length ? (
            <div className="attachment-row">
              {attachments.map((item) => (
                <div
                  className={`attachment-chip ${item.loading ? 'loading' : ''} ${item.error ? 'error' : ''}`}
                  key={item.id}
                  title={item.note || item.name}
                >
                  {item.loading ? (
                    <span className="spinner spinner-xs" />
                  ) : (
                    <Icon name="fileText" size={14} />
                  )}
                  <span className="attachment-name">{item.name}</span>
                  <span className="attachment-size">
                    {item.error ? '失败' : formatFileSize(item.size)}
                  </span>
                  <button
                    type="button"
                    className="attachment-remove"
                    onClick={() => removeAttachment(item.id)}
                    aria-label={`移除 ${item.name}`}
                  >
                    <Icon name="x" size={12} />
                  </button>
                </div>
              ))}
            </div>
          ) : null}

          {uploading ? (
            <div className="transcribing">
              <span className="spinner spinner-sm" />
              正在识别语音，请稍候…
            </div>
          ) : null}

          {recording ? (
            <div className="recording-bar">
              <span className="rec-dot" />
              <span className="recording-time">{formatClock(seconds)}</span>
              <span className="recording-wave" aria-hidden="true">
                <i />
                <i />
                <i />
                <i />
                <i />
              </span>
              <span className="recording-hint">正在录音，最长 {formatClock(maxSeconds)}</span>
              <button type="button" className="btn btn-sm btn-primary" onClick={stop}>
                停止并转写
              </button>
              <button type="button" className="icon-btn" onClick={cancel} title="取消录音">
                <Icon name="x" size={17} />
              </button>
            </div>
          ) : (
            <textarea
              ref={textareaRef}
              className="composer-input"
              value={text}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              placeholder={connected ? (aiReady ? '写下问题、材料或任务…' : '接入模型后开始') : '等待连接…'}
              rows={1}
              maxLength={500000}
              disabled={!connected || uploading || !aiReady}
              aria-label="消息内容"
            />
          )}

          <div className="composer-toolbar">
            <div className="composer-tools">
              {promptPlugins.length ? (
                <details className="composer-plugin-menu">
                  <summary className="icon-btn" title="插入插件模板" aria-label="插入插件模板">
                    <Icon name="plug" size={18} />
                  </summary>
                  <div className="menu-panel plugin-menu-panel">
                    <div className="menu-label">插件模板</div>
                    {promptPlugins.map((prompt) => (
                      <button
                        key={`${prompt.pluginName}-${prompt.title}`}
                        type="button"
                        onClick={(event) => {
                          event.currentTarget.closest('details')?.removeAttribute('open')
                          usePluginPrompt(prompt)
                        }}
                      >
                        <span>
                          <strong>{prompt.title}</strong>
                          <small>{prompt.pluginName}</small>
                        </span>
                        <span className="prompt-mode">{prompt.mode === 'reasoner' ? '推理' : '日常'}</span>
                      </button>
                    ))}
                  </div>
                </details>
              ) : null}
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="file-input-hidden"
                onChange={(event) => {
                  addFiles(event.target.files)
                  event.target.value = ''
                }}
              />
              <button
                type="button"
                className="icon-btn"
                onClick={() => fileInputRef.current?.click()}
                disabled={!connected || extracting || streaming}
                title="导入文件（文档、表格、PDF、代码、压缩包…）"
                aria-label="导入文件"
              >
                <Icon name="paperclip" size={18} />
              </button>
              <button
                type="button"
                className={`icon-btn mic-btn ${recording ? 'active' : ''}`}
                onClick={toggleRecording}
                disabled={!supported || !connected || streaming || uploading}
                title={!supported ? '当前浏览器不支持录音' : recording ? '停止录音并转写' : '语音输入'}
                aria-label={recording ? '停止录音' : '语音输入'}
              >
                {uploading ? <span className="spinner spinner-sm" /> : <Icon name="mic" size={19} />}
              </button>
              <span className="composer-hint">
                {recording ? '录音中…' : extracting ? '正在解析文件…' : 'Enter 发送 · Shift + Enter 换行'}
              </span>
            </div>

            <div className="composer-actions">
              {text.length > 120000 ? <span className="char-count">{text.length}/200000</span> : null}
              {streaming ? (
                <button type="button" className="btn-stop" onClick={() => onStop?.()} title="停止生成">
                  <Icon name="stop" size={15} />
                  停止
                </button>
              ) : (
                <button
                  type="button"
                  className="send-btn"
                  onClick={submit}
                  disabled={!canSend}
                  title="发送消息"
                  aria-label="发送消息"
                >
                  <Icon name="send" size={18} />
                </button>
              )}
            </div>
          </div>
        </div>
        <p className="composer-footer">Dreikanterbot V3.1.1 · 内容由模型生成，关键结论请核对</p>
      </div>
      {dragOver ? (
        <div className="drop-overlay">
          <Icon name="paperclip" size={28} />
          <strong>松手导入文件</strong>
          <span>支持 PDF、Word、Excel、PPT、代码、文本和 ZIP</span>
        </div>
      ) : null}
    </div>
  )
}
