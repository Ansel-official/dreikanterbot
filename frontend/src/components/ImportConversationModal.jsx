import { useEffect, useRef, useState } from 'react'
import api, { errorMessage } from '../api/client'
import Modal from './Modal'
import Icon from './Icons'
import { useToast } from './Toast'

export default function ImportConversationModal({ open, onClose, onImported }) {
  const toast = useToast()
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [result, setResult] = useState(null)
  const inputRef = useRef(null)

  useEffect(() => {
    if (open) {
      setFile(null)
      setResult(null)
      setBusy(false)
      setDragOver(false)
    }
  }, [open])

  const runImport = async (selected) => {
    if (!selected) return
    setFile(selected)
    setBusy(true)
    setResult(null)
    const form = new FormData()
    form.append('file', selected, selected.name)
    try {
      const response = await api.post('/imports/deepseek', form, { timeout: 120000 })
      setResult(response.data)
      toast('对话导入成功，可以继续聊', 'success')
    } catch (error) {
      toast(errorMessage(error, '对话导入失败'), 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={busy ? () => {} : onClose}
      title="继续 DeepSeek 对话"
      subtitle="导入 DeepSeek 官方导出的 JSON，接着原来的上下文聊"
      size="md"
      footer={
        result?.continue_session_id ? (
          <>
            <button className="btn btn-ghost" onClick={onClose}>
              稍后
            </button>
            <button
              className="btn btn-primary"
              onClick={() => onImported?.(result.continue_session_id)}
            >
              <Icon name="message" size={16} />
              继续聊
            </button>
          </>
        ) : null
      }
    >
      <div className="import-layout">
        <div
          className={`import-drop ${dragOver ? 'over' : ''} ${busy ? 'busy' : ''}`}
          onDragOver={(event) => {
            event.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(event) => {
            event.preventDefault()
            setDragOver(false)
            const dropped = event.dataTransfer?.files?.[0]
            if (dropped) runImport(dropped)
          }}
          onClick={() => !busy && inputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') inputRef.current?.click()
          }}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".json,application/json"
            className="file-input-hidden"
            onChange={(event) => {
              const selected = event.target.files?.[0]
              if (selected) runImport(selected)
              event.target.value = ''
            }}
          />
          {busy ? (
            <>
              <span className="spinner" />
              <strong>正在导入并重建对话…</strong>
              <span>{file?.name}</span>
            </>
          ) : (
            <>
              <span className="import-icon">
                <Icon name="upload" size={26} />
              </span>
              <strong>选择或拖入 DeepSeek 对话 JSON</strong>
              <span>支持官方导出、本应用导出及常见 conversations / messages 结构</span>
              <small>单个文件最大 20MB</small>
            </>
          )}
        </div>

        {result ? (
          <div className="import-result">
            <div className="import-result-stat">
              <Icon name="check" size={18} />
              <span>
                已导入 <strong>{result.imported_sessions}</strong> 个会话、<strong>{result.imported_messages}</strong> 条消息
              </span>
            </div>
            <p>导入的对话会出现在左侧历史里，点击「继续聊」会打开最新会话并保留原有上下文。</p>
          </div>
        ) : (
          <div className="import-tips">
            <p>
              <strong>如何导出：</strong>在 DeepSeek 账号的数据导出/备份入口下载 JSON（不同版本入口可能不同），然后在这里导入。
            </p>
            <p>导入不会上传到第三方；解析在你的服务器内完成。</p>
          </div>
        )}
      </div>
    </Modal>
  )
}
