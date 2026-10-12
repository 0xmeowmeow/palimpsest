// Uses an existing local Playwright installation; no dependency download.
const {chromium} = await import(process.env.PALIMPSEST_PLAYWRIGHT_MODULE || 'playwright');
import {spawn} from 'node:child_process';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
const temp=await mkdtemp(path.join(tmpdir(),'palimpsest-browser-'));
const server=spawn('python3',['-m','palimpsest','--db',path.join(temp,'notebook.sqlite3'),'serve','--port','18766'],{stdio:['ignore','pipe','pipe']});
let browser;
try{
 await new Promise((resolve,reject)=>{server.stdout.once('data',resolve);server.once('exit',code=>reject(Error('Server exited '+code)));server.stderr.on('data',d=>process.stderr.write(d));});
 browser=await chromium.launch({headless:true,executablePath:process.env.PALIMPSEST_CHROMIUM || undefined,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1440,height:1100}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:18766');await page.waitForFunction(()=>document.querySelector('#route').textContent.includes('Local model'));
 await page.waitForSelector('[data-question=boundary]');await page.screenshot({path:'/tmp/palimpsest-desktop.png',fullPage:true});
 await page.locator('[data-question=boundary]').click();await page.waitForSelector('#desk:not([hidden])');
 await page.locator('#body').fill('BROWSER FIXTURE: a failed attempt');await page.locator('#capture button[type=submit]').click();await page.waitForFunction(()=>document.querySelectorAll('.leaf').length===1);
 await page.locator('.leaf button').click();await page.locator('#body').fill('BROWSER FIXTURE: a corrected attempt');await page.locator('#capture button[type=submit]').click();await page.waitForFunction(()=>document.querySelector('.leaf select').value==='2');
 await page.locator('.leaf select').selectOption('1');await page.locator('.leaf input[type=checkbox]').check();await page.locator('#question').fill('Which attempt is supplied here?');await page.locator('#preview').click();await page.waitForSelector('#preview-area:not([hidden])');
 const context=await page.locator('#context').textContent();if(!context.includes('a failed attempt')||context.includes('a corrected attempt'))throw Error('Wrong revision in request');
 await page.locator('#question').fill('Just explain the selected observation directly.');await page.locator('#preview').click();await page.waitForFunction(()=>document.querySelector('#mode').value==='direct help');await page.reload();await page.waitForFunction(()=>document.querySelector('#mode').value==='direct help');
 await page.locator('[data-tab=desk]').click();await page.locator('.leaf input[type=checkbox]').check();const [dl]=await Promise.all([page.waitForEvent('download'),page.locator('#export').click()]);if(dl.suggestedFilename()!=='palimpsest-sources.json')throw Error('Missing export');
 const [edition]=await Promise.all([page.waitForEvent('download'),page.locator('#compile').click()]);if(!edition.suggestedFilename().endsWith('.zip'))throw Error('Edition bundle missing');
 await page.locator('[data-tab=landscape]').click();if(await page.locator('#paths article').count()!==11)throw Error('Coverage omitted');
 await page.setViewportSize({width:390,height:844});await page.locator('[data-tab=desk]').click();await page.screenshot({path:'/tmp/palimpsest-mobile.png',fullPage:true});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile overflow');
 const security=await page.evaluate(async()=>({noToken:(await fetch('/api/capture',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({body:'not allowed'})})).status}));if(security.noToken!==403)throw Error('CSRF token not enforced');
 await page.locator('#back-to-map').click();await page.locator('#new-question-button').click();await page.locator('#new-question-text').fill('My unexpected question');await page.locator('#new-question button').click();await page.waitForFunction(()=>document.querySelector('#notebook-title').textContent==='My unexpected question');if(await page.locator('.leaf').count()!==0)throw Error('Another question leaked into this notebook');
 await page.locator('#show-all-notes').check();await page.locator('.leaf input[type=checkbox]').check();await page.locator('#link-notes').click();await page.waitForFunction(()=>document.querySelector('#notice').textContent.startsWith('Selected notes are now linked'));await page.locator('#show-all-notes').uncheck();if(await page.locator('.leaf').count()!==1)throw Error('Cross-question link was lost');
 await page.reload();await page.waitForFunction(()=>document.querySelector('#notebook-title').textContent==='My unexpected question');await page.locator('[data-tab=desk]').click();if(await page.locator('.leaf').count()!==1)throw Error('Question notebook did not survive reload');await page.locator('#back-to-map').click();await page.screenshot({path:'/tmp/palimpsest-atlas-mobile.png',fullPage:true});
 // Native Open WebUI availability is checked separately; its outage must not fail bridge tests.
 if(errors.length)throw Error(errors.join('\n'));
 console.log(JSON.stringify({capture:true,revisionSelection:true,contextPreview:true,modeResume:true,export:true,coverage:11,mobileOverflow:false,csrf:security.noToken,pageErrors:errors,screenshots:['/tmp/palimpsest-desktop.png','/tmp/palimpsest-mobile.png']}));
}finally{if(browser)await browser.close();server.kill('SIGTERM');}
