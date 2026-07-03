import { useCallback, useEffect, useRef, useState } from 'react'
import { createSession, deleteSession, getReport, patchHousehold } from './api'
import ActionPlan from './components/ActionPlan'
import Chat from './components/Chat'
import FactsPanel from './components/FactsPanel'
import NextSteps from './components/NextSteps'
import ResultsCards from './components/ResultsCards'
import { buildCaseNote, buildSessionExport, EPASS_URL, parseSessionImport } from './lib'
import type { Household, Patch, ScreeningResult } from './types'

export default function App() {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [demoMode, setDemoMode] = useState(false)
  const [household, setHousehold] = useState<Household | null>(null)
  const [screening, setScreening] = useState<ScreeningResult | null>(null)
  const [fatal, setFatal] = useState<string | null>(null)
  const [chatKey, setChatKey] = useState(0)
  const [noteCopied, setNoteCopied] = useState(false)
  const started = useRef(false)

  const startSession = useCallback(async () => {
    setFatal(null)
    try {
      const created = await createSession()
      setSessionId(created.sessionId)
      setDemoMode(created.demoMode)
      const report = await getReport(created.sessionId)
      setHousehold(report.household)
      setScreening(report.screening)
    } catch (e) {
      setFatal(`Could not reach the server: ${(e as Error).message}`)
    }
  }, [])

  useEffect(() => {
    if (started.current) return
    started.current = true
    void startSession()
  }, [startSession])

  async function newScreening() {
    if (!window.confirm('This will erase everything — nothing is saved.')) return
    const old = sessionId
    setSessionId(null)
    setHousehold(null)
    setScreening(null)
    setChatKey((k) => k + 1)
    if (old) {
      try {
        await deleteSession(old)
      } catch {
        // session may already be gone — creating a fresh one is what matters
      }
    }
    await startSession()
  }

  async function applyPatch(patch: Patch) {
    if (!sessionId) return
    await patchHousehold(sessionId, patch) // throws ApiError on 422 — FactsPanel renders it
    const report = await getReport(sessionId)
    setHousehold(report.household)
    setScreening(report.screening)
  }

  async function copyCaseNote() {
    if (!screening) return
    await navigator.clipboard.writeText(buildCaseNote(screening))
    setNoteCopied(true)
    window.setTimeout(() => setNoteCopied(false), 2000)
  }

  function exportSession() {
    if (!household) return
    const payload = buildSessionExport(household)
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `benefits-screening-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  async function importSession(file: File) {
    let imported: Household
    try {
      imported = parseSessionImport(await file.text())
    } catch (e) {
      window.alert((e as Error).message)
      return
    }
    if (!window.confirm('Importing replaces the current screening — nothing is saved. Continue?')) {
      return
    }
    const old = sessionId
    setSessionId(null)
    setHousehold(null)
    setScreening(null)
    setChatKey((k) => k + 1)
    if (old) {
      try {
        await deleteSession(old)
      } catch {
        // session may already be gone
      }
    }
    try {
      const created = await createSession()
      setSessionId(created.sessionId)
      setDemoMode(created.demoMode)
      // The exported household is a valid whole-household patch: lists merge
      // by id into the fresh session's empty household.
      await patchHousehold(created.sessionId, imported as unknown as Patch)
      const report = await getReport(created.sessionId)
      setHousehold(report.household)
      setScreening(report.screening)
    } catch (e) {
      setFatal(`Could not import the session: ${(e as Error).message}`)
    }
  }

  if (fatal) {
    return (
      <div className="fatal">
        <p>{fatal}</p>
        <button type="button" onClick={() => void startSession()}>
          Try again
        </button>
      </div>
    )
  }

  return (
    <div className="app">
      {demoMode && (
        <div className="demo-banner">
          Public demo — example data only. Do not enter real client information.
        </div>
      )}
      <header className="app-header">
        <h1>NC Benefits Navigator</h1>
        <div className="header-actions">
          <button type="button" onClick={() => window.print()} disabled={!screening}>
            Print action plan
          </button>
          <button type="button" onClick={() => void copyCaseNote()} disabled={!screening}>
            {noteCopied ? 'Copied ✓' : 'Copy case note'}
          </button>
          <button type="button" onClick={exportSession} disabled={!household}>
            Export session
          </button>
          <label className="import-label">
            Import session
            <input
              type="file"
              accept="application/json,.json"
              className="import-input"
              aria-label="Import session file"
              onChange={(e) => {
                const file = e.target.files?.[0]
                e.target.value = ''
                if (file) void importSession(file)
              }}
            />
          </label>
          <button type="button" onClick={() => void newScreening()}>
            New screening
          </button>
        </div>
      </header>
      <main className="panes">
        <section className="pane chat-pane" aria-label="Conversation">
          <Chat
            key={chatKey}
            sessionId={sessionId}
            onHousehold={setHousehold}
            onScreening={setScreening}
          />
        </section>
        <section className="pane facts-pane" aria-label="Household facts and results">
          <FactsPanel household={household} onPatch={applyPatch} />
          <ResultsCards screening={screening} />
          <NextSteps screening={screening} />
        </section>
      </main>
      <footer className="app-footer">
        This is a screening estimate, not an eligibility determination. Only your county DSS can
        determine eligibility. Apply online at{' '}
        <a href={EPASS_URL} target="_blank" rel="noreferrer">
          epass.nc.gov
        </a>
        .
      </footer>
      {screening && <ActionPlan screening={screening} />}
    </div>
  )
}
