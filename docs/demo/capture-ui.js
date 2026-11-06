// Run with playwright-cli run-code --filename docs/demo/capture-ui.js.
// Every API is intercepted. No credentials, providers or real transfers are used.
async (page) => {
  const now = new Date().toISOString();
  const quota = (window, remaining) => ({window,remaining,units:'percent',scope:'shared',state:'available',observed_at:now});
  const task = {slug:'search-index',goal:'Add search to the notes app',owner:'claude-demo',status:'active',checkpoint_matches:true,
    next_action:'Finish the search-index tests, then verify the result.',prepared_at:now,mismatches:[],
    acceptance:['Search returns matching notes','Empty queries return no results'],remaining:['Finish edge-case tests'],failures:[],reported_verification:[],
    verification:{status:'passed',command:['python','-m','unittest','tests.test_index'],finished_at:now,exit_code:0,output_tail:'12 tests passed (demo)'},
    recommendation:{action:'switch',recommended:'codex-demo',confidence:'low',reasons:['Claude is below the chosen reserve.','Codex has recorded capacity.'],uncertainty:'Recommendation, not quota enforcement.',next_step:'Stop the source writer, release ownership, then claim in Codex.'}};
  const data={repo:'demo/notes-app',branch:'feature/search',observed_at:now,checked_at:now,action_token:'demo-only',errors:[],warnings:[],setup_needed:false,
    remote_access:{authenticated:true,label:'Demo phone'},workstreams:[task],accounts:{
      'claude-demo':{provider:'claude',plan:'Example account',state:'available',capture_enabled:true,windows:[quota('five_hour',8),quota('seven_day',33)]},
      'codex-demo':{provider:'codex',plan:'Example account',state:'available',windows:[quota('weekly',72)]}}};
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    if(path==='/api/release') {task.status='released';task.release_ticket='demo-ticket';await route.fulfill({json:{status:'released'}});}
    else if(path==='/api/claim') {task.status='active';task.owner='codex-demo';await route.fulfill({json:{status:'claimed',prompt:'Continue search-index from handoffs/search-index.md.\nVerify the checkpoint before editing.\nNext: finish edge-case tests and run the test suite.'}});}
    else await route.fulfill({json:data});
  });
  await page.setViewportSize({width:1000,height:900});
  await page.goto('http://127.0.0.1:8790/');
  await page.locator('.account').first().waitFor();
  await page.locator('#accounts').screenshot({path:'docs/media/demo-capacity.png'});
  // Open the real checkpoint disclosure and capture its real UI.
  await page.locator('#details .block').nth(1).locator('summary').click();
  await page.locator('#details .block').nth(1).screenshot({path:'docs/media/demo-checkpoint.png'});
  await page.locator('#details .block').last().screenshot({path:'docs/media/demo-release.png'});
  await page.getByRole('checkbox').check();
  await page.getByRole('button',{name:'Release ownership',exact:true}).click();
  await page.getByRole('button',{name:'Claim & prepare resume prompt'}).waitFor();
  await page.getByLabel('Destination account').selectOption('codex-demo');
  await page.locator('#details .block').last().screenshot({path:'docs/media/demo-claim.png'});
  await page.getByRole('button',{name:'Claim & prepare resume prompt'}).click();
  await page.getByLabel('Resume prompt').waitFor();
  await page.locator('#details .block').last().screenshot({path:'docs/media/demo-resume.png'});
  await page.setViewportSize({width:390,height:844});
  await page.reload(); await page.locator('.account').first().waitFor();
  await page.screenshot({path:'docs/media/demo-mobile.png'});
  return 'Captured capacity, checkpoint, guarded release/claim, resume prompt and phone UI with simulated API data.';
}
