/** Record the real local Demo UI. Requires Playwright and its FFmpeg component.
 * No provider calls, API key input, browser-profile reuse or fabricated frames.
 */
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdir,writeFile,rename} from 'node:fs/promises';
import {resolve,join,dirname} from 'node:path';

const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const args=process.argv.slice(2);
const argument=(name,fallback)=>{const i=args.indexOf(name);return i<0?fallback:args[i+1];};
const localOrigin=value=>{
  const url=new URL(value);
  assert.equal(url.protocol,'http:');
  assert.ok(['localhost','127.0.0.1','[::1]'].includes(url.hostname));
  assert.ok(!url.username&&!url.password&&!url.search&&!url.hash&&url.pathname==='/');
  return url.origin;
};
const base=localOrigin(argument('--base-url','http://localhost:3000'));
const api=localOrigin(argument('--api-url','http://127.0.0.1:8000'));
const output=resolve(argument('--output',`runtime/stage5/demo-${Date.now()}`));
await mkdir(dirname(output),{recursive:true});
await mkdir(output);
const before=await (await fetch(api+'/local-settings')).json();
assert.ok(Object.values(before.providers).every(p=>!p.configured),'use a preview process without API keys');
const browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL||'msedge',headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1080},reducedMotion:'reduce',
  recordVideo:{dir:output,size:{width:1440,height:1080}}});
const page=await context.newPage();
const video=page.video();
const checkpoints=[];
const apiPosts=[];
page.on('request',request=>{if(request.url().startsWith(api)&&request.method()==='POST')apiPosts.push(new URL(request.url()).pathname);});
let lastNode;
const nodeResponse=scene=>page.waitForResponse(async response=>response.request().method()==='GET'&&
  /\/nodes\/[^/]+$/.test(new URL(response.url()).pathname)&&response.ok()&&(await response.json()).scene_id===scene);
const pause=ms=>page.waitForTimeout(ms);
async function show(name,ms=3500){
  await page.evaluate(()=>window.scrollTo(0,0));
  await pause(500);
  await page.screenshot({path:join(output,name+'.png')});
  checkpoints.push({name,scene:lastNode?.scene_id});
  await pause(ms);
}
async function choose(label,scene){
  const next=nodeResponse(scene);
  await page.getByRole('button',{name:label,exact:true}).click();
  lastNode=await (await next).json();
  await page.locator('.topbar-location').waitFor();
  await pause(700);
}
try{
  await page.goto(base,{waitUntil:'networkidle'});
  await show('01-library');
  const rootResponse=nodeResponse('s1');
  await page.getByRole('button',{name:'开始 Demo',exact:true}).click();
  lastNode=await (await rootResponse).json();
  await show('02-opening');
  await choose('前往档案室寻找日志','s2');
  const archive=structuredClone(lastNode);
  await page.getByRole('button',{name:'展开本幕',exact:true}).click();
  await show('03-discovery');
  await page.getByRole('button',{name:'线索',exact:false}).click();
  await show('04-evidence');
  await page.getByRole('button',{name:'关闭面板',exact:true}).click();
  await page.getByLabel('自由行动',{exact:true}).fill('这段草稿在刷新后仍然保留');
  const restored=nodeResponse('s2');
  await page.reload({waitUntil:'networkidle'});
  lastNode=await (await restored).json();
  assert.deepEqual(lastNode,archive);
  assert.equal(await page.getByLabel('自由行动',{exact:true}).inputValue(),'这段草稿在刷新后仍然保留');
  await show('05-refresh-restored');
  await choose('去码头追查脚印','s3');
  await show('06-dock');
  await choose('带着线索前往灯塔','s5');
  const lighthouse=structuredClone(lastNode);
  await show('07-final-choice');
  for(const [label,scene] of [['公开日志','e1'],['共同保管','e2'],['让秘密沉海','e3']]){
    await choose(label,scene);
    await show('08-'+scene);
    const previous=nodeResponse('s5');
    await page.getByRole('button',{name:'返回上一幕',exact:true}).click();
    lastNode=await (await previous).json();
    assert.deepEqual(lastNode,lighthouse);
  }
  await page.getByRole('button',{name:'记录',exact:true}).click();
  await show('09-branches',5000);
  const replay=nodeResponse('s2');
  await page.locator('.branch-item').filter({hasText:'旧档案室'}).click();
  lastNode=await (await replay).json();
  assert.deepEqual(lastNode,archive);
  await show('10-original-replay');
  await choose('去钟楼查旧记录','s4');
  assert.equal(lastNode.state_snapshot.flags.secret_shared,true);
  await show('11-new-branch');
  await page.getByRole('button',{name:'记录',exact:true}).click();
  await show('12-both-branches',5000);
  const after=await (await fetch(api+'/local-settings')).json();
  assert.deepEqual(after.budget,before.budget);
  assert.ok(apiPosts.every(path=>path==='/sessions'||path==='/turns'));
  await writeFile(join(output,'evidence.json'),JSON.stringify({measurement:'automated_real_browser_demo',
    scope:'Demo UI, three endings, branch isolation, immutable replay and refresh/draft restoration; not AI quality',
    viewport:{width:1440,height:1080},checkpoints,budget_unchanged:true,provider_calls:0},null,2)+'\n');
}finally{
  await context.close();
  await browser.close();
}
await rename(await video.path(),join(output,'demo.webm'));
console.log(JSON.stringify({video:join(output,'demo.webm'),checkpoints:checkpoints.length}));
