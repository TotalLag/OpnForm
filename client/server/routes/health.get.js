export default defineEventHandler(async (event) => {
  const timestamp = new Date().toISOString();
  const uptime = process.uptime();
  
  // Set cache headers to prevent caching
  setHeader(event, 'Cache-Control', 'no-cache, no-store, must-revalidate');
  setHeader(event, 'Pragma', 'no-cache');
  setHeader(event, 'Expires', '0');

  // Simplified health response - UI only
  const healthResponse = {
    status: 'healthy',
    timestamp,
    uptime,
    service: 'opnform-ui',
    checks: {
      ui: 'healthy',
      nitro: 'up'
    }
  };

  return healthResponse;
});