#!/usr/bin/env node
/*
 * HTML -> PDF (A4) via headless Chrome. Gegenstueck zu render_image_post.cjs
 * fuer Dokumente statt Stills (z.B. die Zitat-Liste eines Testimonials).
 *
 * Usage: node render_pdf.cjs <html_path> <out_pdf>
 */
const path = require("path");
const fs = require("fs");
const puppeteer = require("puppeteer-core");

const CHROME_CANDIDATES = [
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  process.env.CHROME_PATH || "",
].filter(Boolean);

function findChrome() {
  for (const c of CHROME_CANDIDATES) if (fs.existsSync(c)) return c;
  throw new Error("Kein Chrome/Chromium gefunden. CHROME_PATH setzen.");
}

(async () => {
  const [, , htmlPath, outPath] = process.argv;
  if (!htmlPath || !outPath) {
    console.error("usage: node render_pdf.cjs <html> <out.pdf>");
    process.exit(2);
  }
  const browser = await puppeteer.launch({
    executablePath: findChrome(),
    headless: "new",
    args: ["--no-sandbox"],
  });
  try {
    const page = await browser.newPage();
    await page.goto("file://" + path.resolve(htmlPath), { waitUntil: "load", timeout: 60000 });
    await page.evaluate(async () => {
      if (document.fonts && document.fonts.ready) await document.fonts.ready;
      await Promise.all(Array.from(document.images).map((img) =>
        img.complete ? Promise.resolve() : new Promise((res) => { img.onload = img.onerror = res; })));
    });
    await page.pdf({
      path: outPath, format: "A4", printBackground: true,
      margin: { top: "18mm", bottom: "18mm", left: "18mm", right: "18mm" },
    });
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e); process.exit(1); });
