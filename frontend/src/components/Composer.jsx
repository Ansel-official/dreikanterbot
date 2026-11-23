import { useLayoutEffect, useRef, useState } from 'react'
import Icon from './Icons'
import { useToast } from './Toast'
import { useMediaRecorder } from '../hooks/useMediaRecorder'

function formatClock(seconds) {
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`
}

export default function Composer({ onSend, onStop, streaming, connectionStatus, quota }) {
  const toast = useToast()
  const [text, setText] = useState('')
  const textareaRef = useRef(null)

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
  const canSend = connected && !streaming && !recording && !uploading && text.trim().length > 0
  const lowQuota = quota && quota.limit != null && quota.remaining <= 10

  const submit = () => {
    const value = text.trim()
    if (!value || !canSend) return
    const result = onSend?.(value)
    if (result !== false) {
      setText('')
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

  return (
    <div className="composer-wrap">
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

        {lowQuota ? (
          <div className="composer-notice quota-warning">
            <Icon name="alert" size={13} /> 今日额度仅剩 {quota.remaining} 次
          </div>
        ) : null}

        <div className={`composer ${recording ? 'is-recording' : ''}`}>
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
              placeholder={connected ? '给 DeepSeek 发消息…' : '等待连接…'}
              rows={1}
              maxLength={20000}
              disabled={!connected || uploading}
              aria-label="消息内容"
            />
          )}

          <div className="composer-toolbar">
            <div className="composer-tools">
              <button
                type="button"
                className={`icon-btn mic-btn ${recording ? 'active' : ''}`}
                onClick={toggleRecording}
                disabled={!supported || !connected || streaming || uploading}
                title={
                  !supported
                    ? '当前浏览器不支持录音'
                    : recording
                      ? '停止录音并转写'
                      : '按住说话（点击开始录音）'
                }
                aria-label={recording ? '停止录音' : '语音输入'}
              >
                {uploading ? <span className="spinner spinner-sm" /> : <Icon name="mic" size={19} />}
              </button>
              <span className="composer-hint">
                {recording ? '录音中…' : 'Enter 发送 · Shift + Enter 换行'}
              </span>
            </div>

            <div className="composer-actions">
              {text.length > 12000 ? <span className="char-count">{text.length}/20000</span> : null}
              {streaming ? (
                <button
                  type="button"
                  className="btn btn-stop"
                  onClick={() => onStop?.()}
                  title="停止生成"
                >
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
        <p className="composer-footer">
          DeepSeek 内部助手 · 回复由 AI 生成，请注意甄别
        </p>
      </div>
    </div>
  )
}
