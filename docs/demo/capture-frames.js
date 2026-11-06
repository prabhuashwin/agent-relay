async (page) => {
  await page.setViewportSize({width:1280,height:720});
  for(let i=0;i<7;i++){
    await page.goto('http://127.0.0.1:8790/docs/demo/walkthrough.html?scene='+i);
    await page.locator('img').evaluateAll(images=>Promise.all(images.map(img=>img.decode())));
    await page.screenshot({path:'output/playwright/relay-scene-'+i+'.png'});
  }
  await page.goto('http://127.0.0.1:8790/docs/demo/walkthrough.html?guide=1');
  await page.screenshot({path:'docs/media/relay-workflow.png'});
  return 'Seven 1280x720 captioned scenes and a three-step visual guide captured';
}
