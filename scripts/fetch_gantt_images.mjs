#!/usr/bin/env node
/**
 * Script d'automatisation Chromium pour générer et télécharger les diagrammes de Gantt.
 * Téléverse le CSV du backlog sur https://gant-notion.vercel.app/,
 * télécharge le PDF découpé par personne pour le sprint demandé,
 * convertit le PDF en PNG via /pdf-to-images et extrait les images dans le dossier cible.
 */

import path from 'path';
import fs from 'fs';
import { execSync } from 'child_process';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Résolution de Playwright (local, tmp ou global)
let chromium;
const candidatePwPaths = [
  path.join(__dirname, 'node_modules', 'playwright-core', 'index.mjs'),
  '/tmp/pw_test/node_modules/playwright-core/index.mjs',
  'playwright-core',
  'playwright'
];

for (const p of candidatePwPaths) {
  try {
    const mod = await import(p);
    chromium = mod.chromium;
    if (chromium) break;
  } catch (e) {
    // Continuer la recherche
  }
}

if (!chromium) {
  console.error("Playwright introuvable. Installation en cours dans /tmp/pw_test...");
  execSync('mkdir -p /tmp/pw_test && cd /tmp/pw_test && npm init -y && npm install playwright-core', { stdio: 'inherit' });
  const mod = await import('/tmp/pw_test/node_modules/playwright-core/index.mjs');
  chromium = mod.chromium;
}

// Recherche générique de Google Chrome ou Chromium (macOS, Linux, WSL)
function findChromeExecutable() {
  const candidates = [
    process.env.CHROME_PATH,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/usr/bin/google-chrome-stable',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium-browser',
    '/usr/bin/chromium',
    '/usr/bin/microsoft-edge',
    '/snap/bin/chromium'
  ];

  // Vérifier également dans le cache Playwright ~/.cache/ms-playwright
  const homeDir = process.env.HOME || '';
  const pwCacheDir = path.join(homeDir, '.cache', 'ms-playwright');
  if (fs.existsSync(pwCacheDir)) {
    try {
      const entries = fs.readdirSync(pwCacheDir);
      for (const entry of entries) {
        if (entry.startsWith('chromium-')) {
          const linuxChrome = path.join(pwCacheDir, entry, 'chrome-linux', 'chrome');
          const macChrome = path.join(pwCacheDir, entry, 'chrome-mac', 'Chromium.app', 'Contents', 'MacOS', 'Chromium');
          if (fs.existsSync(linuxChrome)) candidates.push(linuxChrome);
          if (fs.existsSync(macChrome)) candidates.push(macChrome);
        }
      }
    } catch (_) {}
  }

  for (const c of candidates) {
    if (c && fs.existsSync(c)) return c;
  }
  return undefined; // Laissera Playwright utiliser son binaire par défaut si disponible
}

async function main() {
  const args = process.argv.slice(2);
  let csvPath = '';
  let sprintNum = '8';
  let outDir = path.resolve(__dirname, '..', 'coaching', `gantt_sprint_${sprintNum}`);

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--csv' && args[i + 1]) csvPath = path.resolve(args[++i]);
    else if (args[i] === '--sprint' && args[i + 1]) {
      sprintNum = args[++i];
      outDir = path.resolve(__dirname, '..', 'coaching', `gantt_sprint_${sprintNum}`);
    }
    else if (args[i] === '--out' && args[i + 1]) outDir = path.resolve(args[++i]);
  }

  if (!csvPath) {
    csvPath = path.resolve(__dirname, '..', 'coaching', `sprint_${sprintNum}_backlog.csv`);
  }

  if (!fs.existsSync(csvPath)) {
    console.error(`Fichier CSV introuvable : ${csvPath}`);
    process.exit(1);
  }

  fs.mkdirSync(outDir, { recursive: true });

  const executablePath = findChromeExecutable();
  console.log(`Lancement du navigateur headless (binaire : ${executablePath || 'Playwright default'})...`);
  const browser = await chromium.launch({
    ...(executablePath ? { executablePath } : {}),
    headless: true
  });

  const context = await browser.newContext({ acceptDownloads: true });
  const page = await context.newPage();

  console.log(`[1/5] Navigation vers https://gant-notion.vercel.app/ ...`);
  await page.goto('https://gant-notion.vercel.app/', { waitUntil: 'networkidle' });

  console.log(`[2/5] Téléversement du CSV de backlog : ${csvPath}`);
  await page.locator('input[type="file"]').setInputFiles(csvPath);
  await page.waitForTimeout(2000);

  console.log(`[3/5] Exportation du PDF par personne pour le Sprint ${sprintNum}...`);
  await page.locator('button', { hasText: 'PDF / Personne' }).click();
  await page.waitForTimeout(800);

  const sprintMenuItem = page.locator('[role="menuitem"]', { hasText: `Sprint ${sprintNum}` });
  const count = await sprintMenuItem.count();
  const targetMenuItem = count > 0 ? sprintMenuItem.first() : page.locator('[role="menuitem"]', { hasText: 'Tous les sprints' });

  const [ pdfDownload ] = await Promise.all([
    page.waitForEvent('download'),
    targetMenuItem.click()
  ]);

  const pdfPath = path.join(outDir, `sprint_${sprintNum}_gantt.pdf`);
  await pdfDownload.saveAs(pdfPath);
  console.log(`✓ PDF téléchargé : ${pdfPath} (${fs.statSync(pdfPath).size} octets)`);

  console.log(`[4/5] Conversion PDF -> Images sur https://gant-notion.vercel.app/pdf-to-images ...`);
  await page.goto('https://gant-notion.vercel.app/pdf-to-images', { waitUntil: 'networkidle' });
  await page.locator('input[type="file"]').setInputFiles(pdfPath);
  await page.waitForTimeout(3000);

  console.log(`[5/5] Téléchargement du ZIP d'images PNG...`);
  const [ zipDownload ] = await Promise.all([
    page.waitForEvent('download'),
    page.locator('button', { hasText: 'Télécharger ZIP' }).click()
  ]);

  const zipPath = path.join(outDir, `gantt_images.zip`);
  await zipDownload.saveAs(zipPath);
  console.log(`✓ Archive ZIP enregistrée : ${zipPath}`);

  // Extraction portable (fonctionne sur Linux/WSL sans nécessiter le package 'unzip')
  try {
    execSync(`python3 -m zipfile -e "${zipPath}" "${outDir}"`);
  } catch (_) {
    execSync(`unzip -o "${zipPath}" -d "${outDir}"`);
  }
  
  // Nettoyage immédiat du fichier ZIP temporaire
  if (fs.existsSync(zipPath)) {
    fs.unlinkSync(zipPath);
    console.log(`✓ Fichier temporaire ${zipPath} nettoyé.`);
  }

  console.log(`✓ Images extraites avec succès dans : ${outDir}`);

  await browser.close();
}

main().catch(err => {
  console.error('Erreur lors du cycle Gantt :', err);
  process.exit(1);
});
