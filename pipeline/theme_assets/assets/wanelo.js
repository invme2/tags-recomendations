/* wanelo.js — sticky ATC + reveal-on-scroll + section rail */
(function () {
  'use strict';
  const page = document.querySelector('.wanelo-page');
  if (!page) return;

  const prefersReducedMotion = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- Reveal-on-scroll ---------- */
  const revealTargets = page.querySelectorAll('.reveal, .mask');
  if (prefersReducedMotion) {
    revealTargets.forEach(el => el.classList.add('in'));
  } else if ('IntersectionObserver' in window) {
    const revealIO = new IntersectionObserver(entries => {
      entries.forEach(e => {
        if (e.isIntersecting) {
          e.target.classList.add('in');
          revealIO.unobserve(e.target);
        }
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -50px 0px' });
    revealTargets.forEach(el => revealIO.observe(el));
  } else {
    revealTargets.forEach(el => el.classList.add('in'));
  }

  /* ---------- Section-progress rail (desktop only) ---------- */
  if (window.matchMedia('(min-width: 1100px)').matches && !prefersReducedMotion) {
    const sections = page.querySelectorAll(':scope > section');
    if (sections.length > 1) {
      const rail = document.createElement('div');
      rail.className = 'wanelo-rail';
      rail.setAttribute('aria-hidden', 'true');
      sections.forEach(() => {
        const dot = document.createElement('span');
        dot.className = 'wanelo-rail__dot';
        rail.appendChild(dot);
      });
      page.appendChild(rail);
      const dots = rail.querySelectorAll('.wanelo-rail__dot');
      const railIO = new IntersectionObserver(entries => {
        entries.forEach(e => {
          if (e.isIntersecting) {
            const idx = Array.prototype.indexOf.call(sections, e.target);
            dots.forEach((d, i) => d.classList.toggle('active', i === idx));
          }
        });
      }, { threshold: 0.4 });
      sections.forEach(s => railIO.observe(s));
    }
  }

  /* ---------- Sticky mobile ATC ---------- */
  const atcAnchor = document.getElementById('wanelo-atc') ||
                    document.querySelector('product-form, [data-product-form], form[action*="/cart/add"]');
  if (atcAnchor && window.matchMedia('(max-width: 768px)').matches) {
    if (!atcAnchor.id) atcAnchor.id = 'wanelo-atc';
    const sticky = document.createElement('a');
    sticky.href = '#wanelo-atc';
    sticky.className = 'wanelo-sticky-atc';
    sticky.setAttribute('data-wanelo-atc-link', '');
    sticky.innerHTML = 'Add to cart <span class="wanelo-sticky-arrow">↑</span>';
    document.body.appendChild(sticky);
    const stickyIO = new IntersectionObserver(entries => {
      entries.forEach(e => sticky.classList.toggle('visible', !e.isIntersecting));
    }, { threshold: 0 });
    stickyIO.observe(atcAnchor);
  }

  /* ---------- Smooth-scroll for any [data-wanelo-atc-link] ---------- */
  document.querySelectorAll('[data-wanelo-atc-link]').forEach(link => {
    link.addEventListener('click', e => {
      const target = document.querySelector(link.getAttribute('href'));
      if (!target) return;
      e.preventDefault();
      target.scrollIntoView({
        behavior: prefersReducedMotion ? 'auto' : 'smooth',
        block: 'start',
      });
    });
  });
})();
