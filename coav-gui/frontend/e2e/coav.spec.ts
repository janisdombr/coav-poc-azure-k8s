import { test, expect, type Page } from '@playwright/test'

// ── Helpers ────────────────────────────────────────────────────────────────────

async function waitForLive(page: Page) {
  await expect(page.locator('.ws-indicator.live')).toBeVisible({ timeout: 15_000 })
}

async function waitForFlights(page: Page) {
  await expect(page.locator('.flight-count')).not.toContainText('0 aircraft', { timeout: 15_000 })
}

async function switchTab(page: Page, label: 'Supervisor' | 'FDO' | 'ATCO' | 'Dashboard') {
  await page.locator('.role-pill', { hasText: label }).click()
}

// ── Suite setup ───────────────────────────────────────────────────────────────

test.describe('COAV E2E', () => {
  // Uncaught JS exceptions only (pageerror).
  // console.error is intentionally excluded — browsers emit it for any 404 resource
  // (Leaflet icons, favicons) which are not our code paths. API 4xx are caught separately.
  const jsErrors: string[] = []

  // 4xx/5xx on /api/ endpoints — the actual bug class we care about.
  const apiErrors: string[] = []

  test.beforeEach(async ({ page }) => {
    jsErrors.length = 0
    apiErrors.length = 0
    page.on('pageerror', err => jsErrors.push(err.message))
    page.on('response', res => {
      if (res.url().includes('/api/') && res.status() >= 400) {
        apiErrors.push(`HTTP ${res.status()} ${res.request().method()} ${res.url()}`)
      }
    })
    await page.goto('/')
  })

  // ── 1. App load ─────────────────────────────────────────────────────────────

  test('page loads — header and map visible', async ({ page }) => {
    await expect(page.locator('.coav-header')).toBeVisible()
    await expect(page.locator('.map-section')).toBeVisible()
  })

  test('WebSocket connects within 15 s', async ({ page }) => {
    await waitForLive(page)
  })

  test('flights appear from simulator', async ({ page }) => {
    await waitForLive(page)
    await waitForFlights(page)
    const text = await page.locator('.flight-count').textContent()
    expect(parseInt(text ?? '0')).toBeGreaterThan(0)
  })

  // ── 2. No JavaScript errors ──────────────────────────────────────────────────

  test('no uncaught JS exceptions after 5 s runtime', async ({ page }) => {
    await waitForLive(page)
    await waitForFlights(page)
    await page.waitForTimeout(5_000)
    expect(jsErrors, `Uncaught JS errors: ${jsErrors.join('; ')}`).toHaveLength(0)
  })

  test('no uncaught JS exceptions while switching all tabs', async ({ page }) => {
    await waitForLive(page)
    for (const tab of ['Supervisor', 'FDO', 'ATCO', 'Dashboard'] as const) {
      await switchTab(page, tab)
      await page.waitForTimeout(500)
    }
    expect(jsErrors, `Uncaught JS errors: ${jsErrors.join('; ')}`).toHaveLength(0)
  })

  test('no 4xx/5xx on /api/ endpoints during load', async ({ page }) => {
    await waitForLive(page)
    await waitForFlights(page)
    await page.waitForTimeout(3_000)
    expect(apiErrors, `API errors: ${apiErrors.join('; ')}`).toHaveLength(0)
  })

  // ── 3. ATCO — correction form ────────────────────────────────────────────────

  test('ATCO: alert cards visible when flights are active', async ({ page }) => {
    await waitForLive(page)
    await waitForFlights(page)
    await switchTab(page, 'ATCO')
    await expect(page.locator('.alert-card').first()).toBeVisible({ timeout: 20_000 })
  })

  test('ATCO: "Change FL" opens inline correction form', async ({ page }) => {
    await waitForLive(page)
    await switchTab(page, 'ATCO')
    await expect(page.locator('.alert-card').first()).toBeVisible({ timeout: 20_000 })
    await page.locator('.btn-correct').first().click()
    await expect(page.locator('.correction-form')).toBeVisible()
  })

  test('ATCO: correction POST returns 200 and shows acknowledgement', async ({ page }) => {
    await waitForLive(page)
    await switchTab(page, 'ATCO')
    await expect(page.locator('.alert-card').first()).toBeVisible({ timeout: 20_000 })

    const responsePromise = page.waitForResponse(
      res => res.url().includes('/api/correction') && res.request().method() === 'POST',
      { timeout: 10_000 }
    )

    await page.locator('.btn-correct').first().click()
    await expect(page.locator('.correction-form')).toBeVisible()
    await page.locator('.correction-form .form-input').last().fill('Contrail avoidance E2E test')
    await page.locator('.btn-send').click()

    const response = await responsePromise
    expect(response.status()).toBe(200)

    await expect(page.locator('.ack-banner')).toBeVisible({ timeout: 5_000 })
    await expect(page.locator('.ack-banner')).toContainText('ATC instruction')
  })

  test('ATCO: POST /api/correction is NOT 405 (regression guard)', async ({ page }) => {
    await waitForLive(page)
    await switchTab(page, 'ATCO')
    await expect(page.locator('.alert-card').first()).toBeVisible({ timeout: 20_000 })

    const correctionErrors: { url: string; status: number }[] = []
    page.on('response', res => {
      if (res.url().includes('/api/correction') && res.status() >= 400) {
        correctionErrors.push({ url: res.url(), status: res.status() })
      }
    })

    await page.locator('.btn-correct').first().click()
    await page.locator('.btn-send').click()
    await page.waitForTimeout(2_000)

    expect(correctionErrors, `Got error responses: ${JSON.stringify(correctionErrors)}`).toHaveLength(0)
  })

  // ── 4. FDO panel ─────────────────────────────────────────────────────────────

  test('FDO: panel shows advisories or sector-clear message', async ({ page }) => {
    await waitForLive(page)
    await switchTab(page, 'FDO')
    const hasAdvisories = await page.locator('.advisory-card').count()
    const hasEmpty      = await page.locator('.empty, .critical-note').count()
    expect(hasAdvisories + hasEmpty).toBeGreaterThan(0)
  })

  // ── 5. Supervisor panel ───────────────────────────────────────────────────────

  test('Supervisor: GO/NOGO toggle changes label', async ({ page }) => {
    await waitForLive(page)
    await switchTab(page, 'Supervisor')

    const toggle = page.locator('.go-btn, .nogo-btn').first()
    await expect(toggle).toBeVisible()
    const before = await toggle.textContent()

    await toggle.click()
    await page.waitForTimeout(300)

    expect(await toggle.textContent()).not.toBe(before)
  })

  // ── 6. Dashboard ─────────────────────────────────────────────────────────────

  test('Dashboard: /api/advisory/stats returns 200', async ({ page }) => {
    const responsePromise = page.waitForResponse(
      res => res.url().includes('/api/advisory/stats'),
      { timeout: 10_000 }
    )
    await switchTab(page, 'Dashboard')
    expect((await responsePromise).status()).toBe(200)
  })

  test('Dashboard: stats grid shows numeric values', async ({ page }) => {
    await waitForLive(page)
    await switchTab(page, 'Dashboard')

    // Filter the stats-grid that belongs to the Dashboard panel (has "Advisories Generated")
    const dashGrid = page.locator('.stats-grid').filter({ hasText: 'Advisories Generated' })
    await expect(dashGrid).toBeVisible({ timeout: 10_000 })

    const firstValue = await dashGrid.locator('.stat-value').first().textContent()
    expect(firstValue).toMatch(/\d/)
  })
})
