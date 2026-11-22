import { expect, test } from '@playwright/test';

test.afterEach(async ({ request }) => {
  await request.delete('http://127.0.0.1:8740/api/watchlist/DEMO-HK-001');
});

test('概览、机会池、个股、自选与回放主流程可操作', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.request.delete('http://127.0.0.1:8740/api/watchlist/DEMO-HK-001');
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /市场全景/ })).toBeVisible();
  await expect(page.getByText('合成演示模式')).toBeVisible();
  await expect(page.getByText('DEMO', { exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: '切换浅色主题' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await page.getByRole('button', { name: '切换深色主题' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');

  await page.locator('.nav-item').filter({ hasText: '机会池' }).click();
  await expect(page.getByRole('heading', { name: /机会池/ })).toBeVisible();
  await page.getByRole('textbox', { name: '过滤证券' }).fill('SYN-HK-001');
  await expect(page.locator('.clickable-row')).toHaveCount(1);
  const csvDownload = page.waitForEvent('download');
  await page.getByRole('link', { name: '导出机会池CSV' }).click();
  expect((await csvDownload).suggestedFilename()).toBe('opportunities-HK.csv');
  await page.locator('.clickable-row').click();

  await expect(page.getByRole('heading', { name: /SYN-HK-001/ })).toBeVisible();
  await expect(page.getByLabel('日线K线图')).toBeVisible();
  await page.getByRole('button', { name: '加入自选' }).click();
  await expect(page.getByText('已加入自选')).toBeVisible();

  await page.locator('.nav-item').filter({ hasText: '我的自选' }).click();
  await expect(page.getByText('SYN-HK-001').first()).toBeVisible();
  await page.getByRole('textbox', { name: 'SYN-HK-001个人备注' }).fill('观察样例');
  await page.getByRole('textbox', { name: 'SYN-HK-001个人备注' }).press('Enter');
  await expect(page.getByText('备注已保存')).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'SYN-HK-001个人备注' })).toHaveValue('观察样例');

  await page.locator('.nav-item').filter({ hasText: '历史回放' }).click();
  await page.getByRole('button', { name: '运行单标的回放' }).click();
  await expect(page.getByText('模拟区间收益')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('逐日收盘估值', { exact: true })).toBeVisible();
  await page.locator('.nav-item').filter({ hasText: '我的自选' }).click();
  await page.getByRole('button', { name: '移除 SYN-HK-001' }).click();
});

test('市场筛选和排序可用，窄屏没有页面级横向溢出', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.locator('.nav-item').filter({ hasText: '机会池' }).click();
  await page.getByRole('button', { name: /US 美股/ }).click();
  await expect(page.getByRole('button', { name: /US 美股/ })).toHaveClass(/selected/);
  await page.getByRole('combobox', { name: '排序方式' }).selectOption('change_pct');
  await expect(page.locator('.clickable-row')).toHaveCount(15);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflow).toBe(false);
});
