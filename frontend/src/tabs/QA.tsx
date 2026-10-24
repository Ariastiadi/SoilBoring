import { useEffect, useMemo, useRef, useState } from 'react'
import { askAI, getAuthToken } from '../api'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

// Must stay within the backend limits (20 turns, 4000 characters each, 2000-character question).
const MAX_HISTORY_MESSAGES = 16
const MAX_TURN_CHARS = 4000
const MAX_QUESTION_CHARS = 2000
const MAX_CONTEXT_CHARS = 8000

type HistoryEntry = { q: string, a: string, evidence?: string, ts: number }
const HISTORY_KEY = 'qa_history'

function loadHistory(): HistoryEntry[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]')
    if (!Array.isArray(parsed)) return []
    // Anything malformed (hand-edited storage, older versions) is dropped instead of crashing the app.
    return parsed
      .filter((h: any) => h && typeof h.q === 'string' && typeof h.a === 'string')
      .map((h: any, i: number) => ({
        q: h.q,
        a: h.a,
        evidence: typeof h.evidence === 'string' ? h.evidence : undefined,
        ts: typeof h.ts === 'number' ? h.ts : i,
      }))
  } catch {
    return []
  }
}

function saveHistory(entries: HistoryEntry[]) {
  try {
    if (entries.length) localStorage.setItem(HISTORY_KEY, JSON.stringify(entries))
    else localStorage.removeItem(HISTORY_KEY)
  } catch {
    // storage full or blocked: the conversation still works for this visit
  }
}

export default function QA() {
  const [question, setQuestion] = useState('')
  const [context, setContext] = useState('')
  const [history, setHistory] = useState<HistoryEntry[]>(loadHistory)
  const [status, setStatus] = useState('')
  const [pending, setPending] = useState(false)
  // Bumped by "Clear Conversation", so an answer still in flight is not added back.
  const generation = useRef(0)
  const mounted = useRef(false)

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])

  const onAsk = async () => {
    if (!question.trim() || pending) return
    const asked = question
    const myGeneration = generation.current
    const tokenAtStart = getAuthToken()
    setPending(true)
    setStatus('Thinking...')
    try {
      // Build chat history for backend: alternating user/assistant turns
      const turns: Array<{role: string, content: string}> = []
      history.forEach(h => {
        turns.push({ role: 'user', content: h.q.slice(0, MAX_TURN_CHARS) })
        if (h.a) turns.push({ role: 'assistant', content: h.a.slice(0, MAX_TURN_CHARS) })
      })
      const recentTurns = turns.slice(-MAX_HISTORY_MESSAGES)
      const res = await askAI(asked, context || undefined, recentTurns)
      // Signed out, session changed or conversation cleared meanwhile: drop the answer.
      if (generation.current !== myGeneration || getAuthToken() !== tokenAtStart || !tokenAtStart) return
      const entry: HistoryEntry = {
        q: asked,
        a: typeof res?.answer === 'string' ? res.answer : '',
        evidence: typeof res?.context === 'string' ? res.context : undefined,
        ts: Date.now(),
      }
      if (!mounted.current) {
        // The user switched tabs while waiting: keep the answer for when they come back.
        saveHistory([...loadHistory(), entry])
        return
      }
      setHistory(prev => {
        const next = [...prev, entry]
        saveHistory(next)
        return next
      })
      setStatus('')
    } catch (err: any) {
      if (mounted.current && generation.current === myGeneration) setStatus(`Error: ${err.message}`)
    } finally {
      if (mounted.current && generation.current === myGeneration) setPending(false)
    }
  }

  const copyAnswer = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setStatus('Answer copied')
    } catch {
      setStatus('Copy failed')
    }
  }

  function splitCsvLine(line: string): string[] {
    const out: string[] = []
    let cur = ''
    let inQuotes = false
    for (let i = 0; i < line.length; i++) {
      const ch = line[i]
      if (inQuotes) {
        if (ch === '"') {
          if (i + 1 < line.length && line[i + 1] === '"') {
            cur += '"'
            i++
          } else {
            inQuotes = false
          }
        } else {
          cur += ch
        }
      } else {
        if (ch === ',') {
          out.push(cur)
          cur = ''
        } else if (ch === '"') {
          inQuotes = true
        } else {
          cur += ch
        }
      }
    }
    out.push(cur)
    return out
  }

  function EvidenceTable({ csv }: { csv: string }) {
    const lines = csv.split(/\r?\n/).filter(Boolean)
    if (lines.length === 0) return null
    const headers = splitCsvLine(lines[0])
    const rows = lines.slice(1).map(line => splitCsvLine(line))
    return (
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              {headers.map(h => (
                <th key={h} style={{ textAlign: 'left', borderBottom: '1px solid #24304a', padding: '.4rem' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                {r.map((c, j) => (
                  <td key={j} style={{ padding: '.35rem', borderBottom: '1px dashed #1b263f', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: '.9rem' }}>{c}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  return (
    <div>
      <div className="row">
        <div>
          <label htmlFor="qa-question">Question</label>
          <textarea id="qa-question" value={question} maxLength={MAX_QUESTION_CHARS} onChange={e => setQuestion(e.target.value)} placeholder="Ask about soil boring progress, groundwater, or lab data..." />
        </div>
        <div>
          <label htmlFor="qa-context">Optional Context</label>
          <textarea id="qa-context" value={context} maxLength={MAX_CONTEXT_CHARS} onChange={e => setContext(e.target.value)} placeholder="Paste related report text or notes (optional)" />
        </div>
      </div>
      <div className="actions" style={{ marginTop: '.75rem', gap: '.5rem', display: 'flex', alignItems: 'center' }}>
        <button onClick={onAsk} disabled={pending || !question.trim()}>Ask</button>
        <button
          onClick={() => {
            generation.current += 1
            setPending(false)
            setHistory([])
            saveHistory([])
            setStatus('Cleared')
          }}
          disabled={history.length === 0 && !pending}
        >
          Clear Conversation
        </button>
        <span>{status}</span>
      </div>
      {history.length > 0 && (
        <div style={{ marginTop: '1rem' }}>
          {[...history].reverse().map((h, idx) => {
            const qNumber = history.length - idx
            return (
            <div key={h.ts} className="card" style={{ marginBottom: '.75rem' }}>
              <div style={{ color: 'var(--muted)', fontSize: '.9rem' }}>Q{qNumber}: {h.q}</div>
              <RenderedAnswer answer={h.a} />
              <div className="actions" style={{ marginTop: '.5rem' }}>
                <button onClick={() => copyAnswer(h.a)}>Copy Answer</button>
              </div>
              {h.evidence && (
                <div className="card" style={{ marginTop: '.5rem' }}>
                  <details>
                    <summary style={{ cursor: 'pointer' }}>Show Evidence (grounded from CSV)</summary>
                    <EvidenceTable csv={h.evidence} />
                  </details>
                </div>
              )}
            </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function RenderedAnswer({ answer }: { answer: string }) {
  const html = useMemo(() => {
    const raw = marked.parse(answer ?? '', { breaks: true }) as string
    return DOMPurify.sanitize(raw)
  }, [answer])

  return (
    <div className="card" style={{ marginTop: '1rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <label style={{ margin: 0 }}>Answer</label>
      </div>
      <div className="markdown" dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  )
}
