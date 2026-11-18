// Highlight the right download for the visitor's OS. No tracking, no cookies.
(function () {
  var ua = navigator.userAgent || ''
  var platform = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || ''
  var os = null
  if (/Win/i.test(platform) || /Windows/i.test(ua)) os = 'windows'
  else if (/Mac/i.test(platform) || /Mac OS X/i.test(ua)) os = 'mac-arm' // most current Macs are Apple Silicon
  else if (/Linux/i.test(platform) && !/Android/i.test(ua)) os = 'linux'

  var labels = { windows: 'Download for Windows', 'mac-arm': 'Download for macOS', linux: 'Download for Linux' }
  if (!os) return
  var card = document.querySelector('.dl[data-os="' + os + '"]')
  if (card) card.classList.add('recommended')
  var hero = document.getElementById('hero-download')
  if (hero && card) {
    hero.textContent = labels[os]
    hero.href = card.href
  }
})()
