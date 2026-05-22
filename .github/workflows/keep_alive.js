const puppeteer = require('puppeteer');

(async () => {
  const url = process.env.APP_URL || 'https://your-streamlit-app-url.streamlit.app';
  console.log(`Visiting ${url} to keep it awake...`);
  
  const browser = await puppeteer.launch({ 
    headless: "new",
    args: ['--no-sandbox', '--disable-setuid-sandbox'] 
  });
  const page = await browser.newPage();
  
  try {
    // We wait until network is idle to ensure the Streamlit React app fully loads and triggers the wake-up
    await page.goto(url, { waitUntil: 'networkidle2', timeout: 60000 });
    console.log('Successfully loaded the page and fully woke up the Streamlit backend.');
  } catch (error) {
    console.error(`Failed to load page: ${error}`);
  } finally {
    await browser.close();
  }
})();
