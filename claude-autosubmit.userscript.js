// ==UserScript==
// @name     Claude Auto-Submit
// @match    https://claude.ai/new*
// ==/UserScript==
(function() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('q') && params.get('submit') === '1') {
    const interval = setInterval(() => {
      const sendBtn = document.querySelector('button[aria-label="Send message"]');
      if (sendBtn && !sendBtn.disabled) {
        sendBtn.click();
        clearInterval(interval);
      }
    }, 500);
  }
})();