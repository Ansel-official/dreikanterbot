import { useCallback, useEffect, useRef, useState } from 'react'
import api, { errorMessage } from '../api/client'

const MAX_SECONDS = 120

/**
 * 浏览器录音 + 上传 /api/asr。
 * 支持取消、最长 2 分钟、自动停止麦克风、上传中断。
 */
export function useMediaRecorder({ onTranscribed, onError } = {}) {
  const [recording, setRecording] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [seconds, setSeconds] = useState(0)

  const recorderRef = useRef(null)
  const streamRef = useRef(null)
  const chunksRef = useRef([])
  const timerRef = useRef(null)
  const cancelledRef = useRef(false)
  const abortRef = useRef(null)
  const startTimeRef = useRef(0)
  const callbacksRef = useRef({ onTranscribed, onError })

  useEffect(() => {
    callbacksRef.current = { onTranscribed, onError }
  }, [onTranscribed, onError])

  const supported =
    typeof navigator !== 'undefined' &&
    Boolean(navigator.mediaDevices?.getUserMedia) &&
    typeof MediaRecorder !== 'undefined'

  const cleanupStream = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop())
      streamRef.current = null
    }
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const upload = useCallback(async (blob, mimeType) => {
    setUploading(true)
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const form = new FormData()
      const extension = mimeType.includes('mp4') ? 'm4a' : mimeType.includes('ogg') ? 'ogg' : 'webm'
      form.append('file', blob, `recording.${extension}`)
      const response = await api.post('/asr', form, {
        timeout: 180000,
        signal: controller.signal,
      })
      const text = (response.data?.text || '').trim()
      if (!text) {
        callbacksRef.current.onError?.('没有识别到语音内容，请靠近麦克风重试')
      } else {
        callbacksRef.current.onTranscribed?.(text, response.data)
      }
    } catch (error) {
      if (error?.code !== 'ERR_CANCELED' && error?.name !== 'CanceledError') {
        callbacksRef.current.onError?.(errorMessage(error, '语音识别失败，请稍后重试'))
      }
    } finally {
      abortRef.current = null
      setUploading(false)
    }
  }, [])

  const stop = useCallback(() => {
    const recorder = recorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop()
    }
    setRecording(false)
  }, [])

  const cancel = useCallback(() => {
    cancelledRef.current = true
    abortRef.current?.abort()
    const recorder = recorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      try {
        recorder.stop()
      } catch {
        /* ignore */
      }
    }
    cleanupStream()
    setRecording(false)
    setSeconds(0)
  }, [cleanupStream])

  const start = useCallback(async () => {
    if (!supported) {
      callbacksRef.current.onError?.('当前浏览器不支持录音，请使用 Chrome / Edge / Safari 最新版')
      return
    }
    if (recording || uploading) return

    cancelledRef.current = false
    setSeconds(0)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
      streamRef.current = stream

      const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus']
      const mimeType = candidates.find((type) => MediaRecorder.isTypeSupported?.(type)) || ''
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      recorderRef.current = recorder
      chunksRef.current = []

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) chunksRef.current.push(event.data)
      }

      recorder.onstop = () => {
        cleanupStream()
        setRecording(false)
        setSeconds(0)
        const chunks = chunksRef.current
        chunksRef.current = []
        const type = recorder.mimeType || mimeType || 'audio/webm'
        const blob = new Blob(chunks, { type })
        if (cancelledRef.current) return
        if (blob.size < 1200) {
          callbacksRef.current.onError?.('录音时间太短，请至少说一句话')
          return
        }
        upload(blob, type)
      }

      recorder.start(250)
      startTimeRef.current = Date.now()
      setRecording(true)
      timerRef.current = setInterval(() => {
        const elapsed = Math.floor((Date.now() - startTimeRef.current) / 1000)
        setSeconds(elapsed)
        if (elapsed >= MAX_SECONDS) {
          const active = recorderRef.current
          if (active && active.state !== 'inactive') active.stop()
        }
      }, 500)
    } catch (error) {
      cleanupStream()
      setRecording(false)
      if (error?.name === 'NotAllowedError' || error?.name === 'PermissionDeniedError') {
        callbacksRef.current.onError?.('麦克风权限被拒绝，请在浏览器地址栏允许麦克风权限')
      } else if (error?.name === 'NotFoundError') {
        callbacksRef.current.onError?.('未检测到麦克风设备')
      } else {
        callbacksRef.current.onError?.(errorMessage(error, '无法开始录音'))
      }
    }
  }, [cleanupStream, recording, supported, upload, uploading])

  useEffect(() => {
    return () => {
      cancelledRef.current = true
      abortRef.current?.abort()
      const recorder = recorderRef.current
      if (recorder && recorder.state !== 'inactive') {
        try {
          recorder.stop()
        } catch {
          /* ignore */
        }
      }
      cleanupStream()
    }
  }, [cleanupStream])

  return {
    supported,
    recording,
    uploading,
    seconds,
    start,
    stop,
    cancel,
    maxSeconds: MAX_SECONDS,
  }
}
