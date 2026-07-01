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
  await expect(page.locator('.msg-assistant').last()).toContainText(
    'This is a screening estimate, not an eligibility determination.',
  )
  await expect(page.locator('.pill').first()).toHaveText('Likely eligible')
  await expect(page.locator('.benefit')).toContainText('/month estimated')

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
