import type { ScreeningResult } from '../types'

// Warm-handoff block: shown when the screening found an urgent food need
// (expedited FNS flag) or when no program screened likely eligible — the
// point where a worker's referral network takes over from the screener.

export function hasExpeditedFlag(screening: ScreeningResult): boolean {
  return screening.programs.some((p) => p.reasons.some((r) => r.rule_id === 'fns.expedited'))
}

export function allLikelyIneligible(screening: ScreeningResult): boolean {
  return (
    screening.programs.length > 0 &&
    screening.programs.every((p) => p.status === 'likely_ineligible')
  )
}

const RESOURCES = [
  {
    name: 'NC 211',
    detail: 'dial 2-1-1 or nc211.org — statewide referral line for food, housing, and utility help',
    url: 'https://nc211.org',
  },
  {
    name: 'Local food banks',
    detail: 'no application needed — find a pantry via Feeding the Carolinas',
    url: 'https://feedingthecarolinas.org',
  },
  {
    name: 'LIEAP (energy assistance)',
    detail: 'seasonal heating help through county DSS; applications typically open in December',
    url: 'https://www.ncdhhs.gov/divisions/social-services/energy-assistance',
  },
  {
    name: 'NC MedAssist',
    detail: 'free pharmacy program for uninsured, low-income residents',
    url: 'https://medassist.org',
  },
  {
    name: 'Legal Aid of North Carolina',
    detail: 'free help with benefit denials and fair hearings',
    url: 'https://legalaidnc.org',
  },
]

export default function NextSteps({ screening }: { screening: ScreeningResult | null }) {
  if (!screening) return null
  const expedited = hasExpeditedFlag(screening)
  const nothingFound = allLikelyIneligible(screening)
  if (!expedited && !nothingFound) return null

  return (
    <div className="next-steps">
      {expedited && (
        <p className="urgent-note">
          This household may need food help <strong>today</strong>: local food pantries require no
          application — call NC 211 (dial 2-1-1) — and the FNS application qualifies for a 7-day
          expedited decision.
        </p>
      )}
      {nothingFound && (
        <>
          <h3>No likely eligibility found — where to point this household next</h3>
          <ul>
            {RESOURCES.map((r) => (
              <li key={r.name}>
                <a href={r.url} target="_blank" rel="noreferrer">
                  {r.name}
                </a>{' '}
                — {r.detail}
              </li>
            ))}
          </ul>
          <p className="next-steps-note">
            A screening is not a determination: the household can still apply and get a formal
            decision, and appeal it if they disagree.
          </p>
        </>
      )}
    </div>
  )
}
