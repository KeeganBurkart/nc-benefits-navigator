import fs from 'node:fs/promises'
import { expect, test } from '@playwright/test'

// Full screening flow against the real server with NAV_FAKE_LLM=1.
// The fake replays a canned 3-turn conversation ending in a resolved screening.
test('chat → facts panel → edit → results → print plan', async ({ page }) => {
  await page.addInitScript(() => {
    ;(window as { __printed?: boolean }).__printed = false
    window.print = () => {
      ;(window as { __printed?: boolean }).__printed = true
    }
  })
  await page.goto('/')

  const input = page.getByLabel('Message')
  const send = page.getByRole('button', { name: 'Send' })

  // Turn 1: household + income facts land in the panel.
  await input.fill('Single adult, 34, citizen, earns $1200.50 a month')
  await send.click()
  await expect(page.getByLabel('age of m1')).toHaveValue('34')
  await expect(page.getByLabel('amount of i1')).toHaveValue('1200.5')

  // Turn 2: expenses recorded.
  await input.fill('Rent is 950, pays heating, utilities not included, no other expenses')
  await send.click()
  await expect(page.getByLabel('Rent / mortgage ($/mo)')).toHaveValue('950')

  // Turn 3: resolved summary with the exact disclaimer sentence.
  await input.fill("That's everything")
  await send.click()
  const summary = page.locator('.msg-assistant').last()
  await expect(summary).toContainText(
    'This is a screening estimate, not an eligibility determination.',
  )
  // Markdown renders as elements, never as literal ** markers.
  await expect(summary.locator('strong').first()).toHaveText('likely eligible')
  await expect(summary.locator('ul li')).toHaveCount(2)
  await expect(summary).not.toContainText('**')
  await expect(page.locator('.pill').first()).toHaveText('Likely eligible')
  // Four program cards now: FNS, Medicaid, WIC, Lifeline.
  await expect(page.locator('.pill')).toHaveCount(4)
  await expect(page.locator('.benefit').first()).toContainText('/month estimated')

  // Edit an income amount in place → results update from the server.
  await page.getByLabel('amount of i1').fill('5000')
  await expect(page.locator('.pill').first()).toHaveText('Likely not eligible', {
    timeout: 5_000,
  })

  // Print action plan: button calls window.print, print view has the goods.
  await page.getByRole('button', { name: 'Print action plan' }).click()
  await expect
    .poll(async () => page.evaluate(() => (window as { __printed?: boolean }).__printed))
    .toBe(true)
  await page.emulateMedia({ media: 'print' })
  const plan = page.locator('.action-plan')
  await expect(plan).toBeVisible()
  await expect(plan).toContainText(
    'This is a screening estimate, not an eligibility determination.',
  )
  await expect(plan.locator('.checklist li').first()).toBeVisible()
  await expect(plan).not.toContainText("That's everything")
})

// Import a session file into a fresh session, then export and compare.
test('session import populates the panel and export round-trips it', async ({ page }) => {
  const sessionFile = {
    app: 'nc-benefits-navigator',
    kind: 'session-export',
    version: 1,
    exported_at: '2026-07-03T00:00:00Z',
    household: {
      members: [
        {
          id: 'm1',
          age: 34,
          relationship: 'self',
          is_pregnant: false,
          is_disabled: false,
          immigration_status: 'citizen',
          is_student: false,
        },
      ],
      income: [
        {
          id: 'i1',
          member_id: 'm1',
          kind: 'wages',
          amount_cents: 120050,
          frequency: 'monthly',
          hours_per_week: null,
        },
      ],
      expenses: {
        rent_or_mortgage_cents: 95000,
        utilities_included: false,
        pays_heating_cooling: true,
        dependent_care_cents: null,
        child_support_paid_cents: null,
        medical_expenses_elderly_disabled_cents: null,
      },
      county: 'New Hanover',
      purchases_and_prepares_together: true,
    },
  }

  await page.goto('/')
  page.on('dialog', (dialog) => void dialog.accept())
  await page.getByLabel('Import session file').setInputFiles({
    name: 'session.json',
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify(sessionFile)),
  })

  // Imported facts land in the panel and the engine screens them.
  await expect(page.getByLabel('age of m1')).toHaveValue('34')
  await expect(page.getByLabel('amount of i1')).toHaveValue('1200.5')
  await expect(page.locator('.pill')).toHaveCount(4)
  // The complete income picture yields distance-to-limit readouts.
  await expect(page.locator('.income-margin').first()).toContainText('under the')

  // Export: the downloaded file carries the same household back out.
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export session' }).click()
  const download = await downloadPromise
  const text = await fs.readFile((await download.path())!, 'utf8')
  const parsed = JSON.parse(text)
  expect(parsed.kind).toBe('session-export')
  expect(parsed.household.members[0].age).toBe(34)
  expect(parsed.household.income[0].amount_cents).toBe(120050)
  expect(parsed.household.county).toBe('New Hanover')
})
