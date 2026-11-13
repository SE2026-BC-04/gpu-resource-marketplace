import { writeFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

const workerLogin = process.env.PHASE1_E2E_WORKER_LOGIN;
const clientLogin = process.env.PHASE1_E2E_CLIENT_LOGIN;
const password = process.env.PHASE1_E2E_PASSWORD;
const otherListingId = process.env.PHASE1_E2E_OTHER_LISTING_ID;
const otherJobId = process.env.PHASE1_E2E_OTHER_JOB_ID;
const resultPath = process.env.PHASE1_E2E_RESULT_PATH;

test("Worker creates a Listing and Client submits, views, and cancels a Job", async ({ page }) => {
  if (!workerLogin || !clientLogin || !password || !otherListingId || !otherJobId || !resultPath) {
    throw new Error("The PostgreSQL E2E harness must provide the seeded accounts and result path.");
  }

  await page.goto("/");

  await page.getByLabel("Tên đăng nhập").fill(workerLogin);
  await page.getByLabel("Mật khẩu").fill(password);
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await expect(page.getByRole("region", { name: "Tài khoản hiện tại" })).toContainText(workerLogin);

  const listingResponsePromise = page.waitForResponse((response) =>
    response.request().method() === "POST" &&
    new URL(response.url()).pathname === "/api/v1/gpu-listings",
  );
  await page.getByRole("button", { name: "Tạo Listing" }).click();
  await page.getByLabel("Model GPU").fill("E2E Browser GPU");
  await page.getByLabel("VRAM (GB)").fill("80");
  await page.getByLabel("Tổng GPU").fill("4");
  await page.getByRole("button", { name: "Lưu Listing" }).click();

  const listingResponse = await listingResponsePromise;
  expect(listingResponse.status()).toBe(201);
  const listing = await listingResponse.json() as { id: string; status: string };
  expect(listing.status).toBe("ACTIVE");
  await expect(
    page.locator(".listings-grid").getByRole("heading", { name: "E2E Browser GPU" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Đăng xuất" }).click();
  await expect(page.getByRole("heading", { name: "Đăng nhập" })).toBeVisible();

  await page.getByLabel("Tên đăng nhập").fill(clientLogin);
  await page.getByLabel("Mật khẩu").fill(password);
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await expect(page.getByRole("heading", { name: "My Jobs" })).toBeVisible();
  await expect(
    page.locator(".listings-grid").getByRole("heading", { name: "E2E Browser GPU" }),
  ).toBeVisible();

  await page.getByLabel("Listing ID (UUIDv4)").fill(listing.id);
  await page.getByLabel("Số GPU").fill("1");
  await page.getByLabel("Thời lượng (giây)").fill("60");
  const submitResponsePromise = page.waitForResponse((response) =>
    response.request().method() === "POST" &&
    new URL(response.url()).pathname === "/api/v1/jobs",
  );
  await page.getByRole("button", { name: "Gửi công việc" }).click();
  const submitResponse = await submitResponsePromise;
  expect(submitResponse.status()).toBe(201);
  const job = await submitResponse.json() as { id: string; status: string; listing_id: string };
  expect(job.status).toBe("QUEUED");
  expect(job.listing_id).toBe(listing.id);

  await expect(page.getByText(new RegExp(`Đã gửi công việc ${job.id}`))).toBeVisible();
  const jobListItem = page.getByRole("button", { name: new RegExp(job.id) });
  await expect(jobListItem).toBeVisible();
  await expect(jobListItem.getByRole("status")).toHaveText("Đang chờ");
  await expect(page.locator(".job-detail").getByRole("status")).toHaveText("Đang chờ");

  await expect(page.getByRole("button", { name: new RegExp(otherJobId) })).toBeVisible();
  await page.getByLabel("Lọc theo Listing ID").fill(listing.id);
  const filteredListResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return response.request().method() === "GET" &&
      url.pathname === "/api/v1/jobs" &&
      url.searchParams.get("listing_id") === listing.id;
  });
  await page.getByRole("button", { name: "Áp dụng Listing" }).click();
  const filteredListResponse = await filteredListResponsePromise;
  expect(filteredListResponse.status()).toBe(200);
  await expect(page.getByRole("button", { name: new RegExp(otherJobId) })).toHaveCount(0);
  await expect(page.getByRole("button", { name: new RegExp(job.id) })).toBeVisible();

  const cancelResponsePromise = page.waitForResponse((response) =>
    response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/v1/jobs/${job.id}/cancel`,
  );
  await page.getByRole("button", { name: "Hủy công việc" }).click();
  const cancelResponse = await cancelResponsePromise;
  expect(cancelResponse.status()).toBe(200);
  expect((await cancelResponse.json() as { status: string }).status).toBe("CANCELLED");
  await expect(page.locator(".job-detail").getByRole("status")).toHaveText("Đã hủy");

  writeFileSync(resultPath, JSON.stringify({ listingId: listing.id, jobId: job.id }), "utf8");
});
