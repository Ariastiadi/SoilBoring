import { useEffect, useMemo, useState } from 'react'
import { askAI } from '../api'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

// Must stay within the backend limits (20 turns, 4000 characters each, 2000-character question).
const MAX_HISTORY_MESSAGES = 16
const MAX_TURN_CHARS = 4000
const MAX_QUESTION_CHARS = 2000
const MAX_CONTEXT_CHARS = 8000

export default function QA() {
  const [question, setQuestion] = useState('')
  const [context, setContext] = useState('')
  const [history, setHistory] = useState<Array<{ q: string, a: string, evidence?: string, ts: number }>>(() => {
    const raw = localStorage.getItem('qa_history')
    if (!raw) return []
    try { return JSON.parse(raw) } catch { return [] }
  })
  const [status, setStatus] = useState('')

  const onAsk = async () => {
    if (!question.trim()) return
    setStatus('Thinking...')
    try {
      // Build chat history for backend: alternating user/assistant turns
      const turns: Array<{role: string, content: string}> = []
      history.forEach(h => {
        turns.push({ role: 'user', content: h.q.slice(0, MAX_TURN_CHARS) })
        if (h.a) turns.push({ role: 'assistant', content: h.a.slice(0, MAX_TURN_CHARS) })
      })
      const recentTurns = turns.slice(-MAX_HISTORY_MESSAGES)
      const res = await askAI(question, context || undefined, recentTurns)
      const next = [...history, { q: question, a: res.answer, evidence: res.context, ts: Date.now() }]
      setHistory(next)
      localStorage.setItem('qa_history', JSON.stringify(next))
      setStatus('')
    } catch (err: any) {
      setStatus(`Error: ${err.message}`)
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
          <label>Question</label>
          <textarea value={question} maxLength={MAX_QUESTION_CHARS} onChange={e => setQuestion(e.target.value)} placeholder="Ask about soil boring progress, groundwater, or lab data..." />
        </div>
        <div>
          <label>Optional Context</label>
          <textarea value={context} maxLength={MAX_CONTEXT_CHARS} onChange={e => setContext(e.target.value)} placeholder="Paste related report text or notes (optional)" />
        </div>
      </div>
      <div className="actions" style={{ marginTop: '.75rem', gap: '.5rem', display: 'flex', alignItems: 'center' }}>
        <button onClick={onAsk} disabled={status === 'Thinking...'}>Ask</button>
        <button
          onClick={() => {
            setHistory([])
            localStorage.removeItem('qa_history')
            setStatus('Cleared')
          }}
          disabled={history.length === 0}
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
