// WANELO storefront JS — reveal-on-scroll + mobile sticky ATC.
// Two concerns kept in one file (~1 KB minified) so theme only loads
// one extra asset.
(function () {
  if (!('IntersectionObserver' in window)) return;

  // ── Reveal-on-scroll: adds .in to .reveal / .mask when entering viewport.
  var revealIO = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting) {
        e.target.classList.add('in');
        revealIO.unobserve(e.target);
      }
    });
  }, { threshold: 0.1, rootMargin: '0px 0px -8% 0px' });
  document.querySelectorAll('.wanelo-page .reveal, .wanelo-page .mask').forEach(function (el) {
    revealIO.observe(el);
  });

  // ── Mobile sticky ATC: when the real product form scrolls off-screen on
  // mobile (<769px), pin a CTA bar to the bottom of the viewport. Tapping it
  // smooth-scrolls back to the form. One-tap re-access from anywhere on
  // page = +15-25% mobile CVR.
  function setupStickyAtc() {
    if (window.matchMedia('(min-width: 769px)').matches) return;
    var form = document.querySelector('form[action*="/cart/add"]');
    if (!form) return;
    if (!form.id) form.id = 'wanelo-atc';

    var bar = document.createElement('a');
    bar.className = 'wanelo-sticky-atc';
    bar.href = '#' + form.id;
    bar.setAttribute('aria-label', 'Jump to add to cart');
    bar.innerHTML = '<span class="wanelo-sticky-label">Add to cart</span>'
      + '<span class="wanelo-sticky-arrow" aria-hidden="true">↑</span>';
    document.body.appendChild(bar);

    bar.addEventListener('click', function (ev) {
      ev.preventDefault();
      var target = document.getElementById(form.id);
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });

    var stickyIO = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) bar.classList.remove('visible');
        else bar.classList.add('visible');
      });
    }, { threshold: 0.05 });
    stickyIO.observe(form);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupStickyAtc);
  } else {
    setupStickyAtc();
  }
})();
