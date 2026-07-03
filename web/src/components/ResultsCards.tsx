import { centsToDollars, marginSummary, missingFieldQuestion, STATUS_LABELS } from '../lib'
import type { ProgramResult, ScreeningResult } from '../types'

function ProgramCard({ result }: { result: ProgramResult }) {
  return (
    <div className="program-card">
      <div className="program-header">
        <h3>{result.program_label}</h3>
        <span className={`pill pill-${result.status}`}>{STATUS_LABELS[result.status]}</span>
      </div>
      {result.estimated_benefit_cents !== null && (
        <p className="benefit">{centsToDollars(result.estimated_benefit_cents)}/month estimated</p>
      )}
      {result.income_margin && (
        <p
          className={`income-margin ${
            result.income_margin.margin_cents >= 0 ? 'income-margin-under' : 'income-margin-over'
          }`}
        >
          {marginSummary(result.income_margin)}
        </p>
      )}
      {result.reasons.length > 0 && (
        <ul className="reasons">
          {result.reasons.map((reason, i) => (
            <li key={reason.rule_id + i}>
              {reason.text}
              <sup>
                <a
                  href={reason.citation.url}
                  title={`${reason.citation.manual} ${reason.citation.section} — ${reason.citation.title}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  [{i + 1}]
                </a>
              </sup>
            </li>
          ))}
        </ul>
      )}
      {result.missing_fields.length > 0 && (
        <div className="missing">
          <h4>Still needed</h4>
          <ul>
            {result.missing_fields.map((path) => (
              <li key={path}>{missingFieldQuestion(path)}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export default function ResultsCards({ screening }: { screening: ScreeningResult | null }) {
  if (!screening) return null
  return (
    <div className="results">
      <h2>Results</h2>
      {screening.programs.map((p) => (
        <ProgramCard key={p.program} result={p} />
      ))}
    </div>
  )
}
