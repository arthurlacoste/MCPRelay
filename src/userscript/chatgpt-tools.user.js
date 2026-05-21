// ==UserScript==
// @name         chatgpt-tools
// @namespace    local.chatgpt.tools
// @version      1.0.2
// @description  Auto-send URL prompt, open first recent conversation, auto-click MCP primary action
// @match        https://chatgpt.com/*
// @match        https://chat.openai.com/*
// @run-at       document-end
// @grant        none
// ==/UserScript==

(function () {
  'use strict';

  const FEATURES = {
    autoSendPromptFromUrl: true,
    openFirstRecentOnHome: true,
    autoClickMcpPrimaryAction: true,
  };

  const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

  const isVisible = (el) => {
    if (!el || !(el instanceof Element)) return false;

    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);

    return (
      r.width > 0 &&
      r.height > 0 &&
      s.visibility !== 'hidden' &&
      s.display !== 'none' &&
      s.opacity !== '0'
    );
  };

  const fireClick = (el) => {
    for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
      el.dispatchEvent(new MouseEvent(type, {
        bubbles: true,
        cancelable: true,
        view: window
      }));
    }
  };

  function hasUrlPrompt() {
    return new URLSearchParams(location.search).has('prompt');
  }

  function initAutoSendPromptFromUrl() {
    if (!hasUrlPrompt()) return;

    const storageKey = `chatgpt-autosend:${location.href}`;
    if (sessionStorage.getItem(storageKey)) return;

    sessionStorage.setItem(storageKey, '1');

    function findSendButton() {
      return (
        document.querySelector('#composer-submit-button') ||
        document.querySelector('[data-testid="send-button"]') ||
        document.querySelector('button[aria-label="Send prompt"]')
      );
    }

    function clickWhenReady() {
      const button = findSendButton();

      if (!button || button.disabled || button.getAttribute('aria-disabled') === 'true') {
        return false;
      }

      fireClick(button);

      const cleanUrl = `${location.origin}${location.pathname}`;
      history.replaceState({}, '', cleanUrl);

      return true;
    }

    if (clickWhenReady()) return;

    const observer = new MutationObserver(() => {
      if (clickWhenReady()) {
        observer.disconnect();
        clearTimeout(timeout);
      }
    });

    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['disabled', 'aria-disabled']
    });

    const timeout = setTimeout(() => {
      observer.disconnect();
    }, 20000);
  }

  function initOpenFirstRecentOnHome() {
    // Important : ne pas quitter la page si on est venu avec ?prompt=...
    if (hasUrlPrompt()) return;

    const TAG = '[TM Latest Strict]';
    const MAX_WAIT_MS = 20000;
    const CHECK_EVERY_MS = 100;
    const lockKey = 'tm_latest_recent_opened_at';

    function log(...args) {
      console.log(TAG, ...args);
    }

    function isHome() {
      return (
        location.origin === 'https://chatgpt.com' &&
        location.pathname === '/'
      );
    }

    function recentlyOpened() {
      const last = Number(sessionStorage.getItem(lockKey) || 0);
      return Date.now() - last < 3000;
    }

    function getFirstRecentLinkStrict() {
      const history = document.querySelector('#history');
      if (!history) return null;

      return (
        history.querySelector('ul > li:first-child a[href^="/c/"][data-sidebar-item="true"]') ||
        history.querySelector('ul > li:first-child a[href^="/c/"]')
      );
    }

    function getFirstRecentLinkFallback() {
      return (
        document.querySelector('#history a[href^="/c/"][data-sidebar-item="true"]') ||
        document.querySelector('#history a[href^="/c/"]') ||
        document.querySelector('a[data-sidebar-item="true"][href^="/c/"]')
      );
    }

    function getLabel(link) {
      return link?.getAttribute('aria-label') || link?.textContent?.trim() || '';
    }

    function openFirstRecent(reason) {
      if (!isHome()) return true;

      if (recentlyOpened()) {
        log('lock actif, stop');
        return true;
      }

      const link = getFirstRecentLinkStrict() || getFirstRecentLinkFallback();

      if (!link) {
        log('pas encore de premier lien Recents', reason);
        return false;
      }

      const href = link.getAttribute('href');

      if (!href || !href.startsWith('/c/')) {
        log('lien ignoré, href invalide', { href });
        return false;
      }

      const url = new URL(href, location.origin).toString();

      log('premier lien récent trouvé', {
        reason,
        label: getLabel(link),
        href,
        url,
        active: link.hasAttribute('data-active')
      });

      sessionStorage.setItem(lockKey, String(Date.now()));
      location.replace(url);

      return true;
    }

    const startedAt = Date.now();

    const timer = setInterval(() => {
      if (openFirstRecent('interval')) {
        clearInterval(timer);
        return;
      }

      if (Date.now() - startedAt > MAX_WAIT_MS) {
        clearInterval(timer);
        log('timeout : aucun premier lien trouvé');
      }
    }, CHECK_EVERY_MS);

    const observer = new MutationObserver(() => {
      if (openFirstRecent('mutation')) {
        observer.disconnect();
        clearInterval(timer);
      }
    });

    observer.observe(document.documentElement, {
      childList: true,
      subtree: true
    });
  }

  function initAutoClickMcpPrimaryAction() {
    const SETTLE_MS = 5000;
    const MCP_NAME = 'MCP DL';
    const MCP_MATCH_MODE = 'CONTAIN';

    function scrollBottom() {
      requestAnimationFrame(() => {
        const candidates = [
          document.querySelector('main'),
          document.querySelector('[role="main"]'),
          document.scrollingElement,
          document.documentElement,
          document.body
        ].filter(Boolean);

        for (const el of candidates) {
          try {
            el.scrollTo({
              top: el.scrollHeight,
              behavior: 'smooth'
            });
          } catch {
            el.scrollTop = el.scrollHeight;
          }
        }
      });
    }

    function matchesMcpName(text) {
      if (!text) return false;

      if (MCP_MATCH_MODE === 'CONTAIN') {
        return text.includes(MCP_NAME);
      }

      return text.trim() === MCP_NAME;
    }

    function findMcpCards() {
      return [...document.querySelectorAll('.border-token-border-heavy.bg-token-bg-primary')]
        .filter(card => {
          const text = card.textContent || '';
          return matchesMcpName(text) && isVisible(card);
        });
    }

    function findPrimaryRightButton(card) {
      const directPrimary = card.querySelector(
        '[data-testid="tool-action-buttons"] button.btn-primary'
      );

      if (directPrimary && isVisible(directPrimary) && !directPrimary.disabled) {
        return directPrimary;
      }

      const footer =
        card.querySelector('[data-testid="tool-action-buttons"]') ||
        [...card.querySelectorAll('div')]
          .find(el => {
            const className = String(el.className || '');

            return (
              el.querySelector('button') &&
              (
                className.includes('justify-end') ||
                className.includes('gap-3') ||
                className.includes('flex')
              )
            );
          });

      if (!footer) return null;

      const buttons = [...footer.querySelectorAll('button')]
        .filter(btn => isVisible(btn) && !btn.disabled);

      const primary = buttons.find(btn =>
        String(btn.className || '').includes('btn-primary')
      );

      return primary || buttons.at(-1) || null;
    }

    async function actOnCard(card) {
      if (card.dataset.autoMcpClicked === '1') return;

      await sleep(SETTLE_MS);

      if (!document.body.contains(card) || !isVisible(card)) return;

      const button = findPrimaryRightButton(card);
      if (!button) return;

      card.dataset.autoMcpClicked = '1';

      fireClick(button);

      await sleep(300);
      scrollBottom();
    }

    function scan() {
      for (const card of findMcpCards()) {
        actOnCard(card);
      }
    }

    scan();

    new MutationObserver(() => {
      scan();
    }).observe(document, {
      childList: true,
      subtree: true
    });
  }

  if (FEATURES.autoSendPromptFromUrl) initAutoSendPromptFromUrl();
  if (FEATURES.openFirstRecentOnHome) initOpenFirstRecentOnHome();
  if (FEATURES.autoClickMcpPrimaryAction) initAutoClickMcpPrimaryAction();

})();