/* wanelo.js — reveal + section rail + sticky ATC + smooth-scroll
   + hero parallax + sticky-story toggle. All motion early-returns
   under prefers-reduced-motion. */
(function () {
  'use strict';
  var page = document.querySelector('.wanelo-page');
  if (!page) return;

  var mqReduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var mqDesk = window.matchMedia && window.matchMedia('(min-width: 1024px)').matches;
  var mqMob = window.matchMedia && window.matchMedia('(max-width: 768px)').matches;
  var mqRail = window.matchMedia && window.matchMedia('(min-width: 1100px)').matches;

  /* Reveal-on-scroll */
  var revealTargets = page.querySelectorAll('.reveal');
  if (mqReduce || !('IntersectionObserver' in window)) {
    revealTargets.forEach(function (el) { el.classList.add('in'); });
  } else {
    var revealIO = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.classList.add('in');
          revealIO.unobserve(e.target);
        }
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -50px 0px' });
    revealTargets.forEach(function (el) { revealIO.observe(el); });
  }

  /* Section-progress rail (desktop ≥1100px) */
  if (mqRail && !mqReduce) {
    var sections = page.querySelectorAll(':scope > section');
    if (sections.length > 1) {
      var rail = document.createElement('div');
      rail.className = 'wanelo-rail';
      rail.setAttribute('aria-hidden', 'true');
      sections.forEach(function () {
        var dot = document.createElement('span');
        dot.className = 'wanelo-rail__dot';
        rail.appendChild(dot);
      });
      page.appendChild(rail);
      var dots = rail.querySelectorAll('.wanelo-rail__dot');
      var total = sections.length - 1 || 1;
      dots.forEach(function (d, i) { d.style.top = ((i / total) * 100) + '%'; });
      var railIO = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) {
            var idx = Array.prototype.indexOf.call(sections, e.target);
            dots.forEach(function (d, i) { d.classList.toggle('active', i === idx); });
          }
        });
      }, { threshold: 0.4 });
      sections.forEach(function (s) { railIO.observe(s); });
    }
  }

  /* Sticky mobile ATC */
  var atcAnchor = document.getElementById('wanelo-atc') ||
                  document.querySelector('product-form, [data-product-form], form[action*="/cart/add"]');
  if (atcAnchor && mqMob) {
    if (!atcAnchor.id) atcAnchor.id = 'wanelo-atc';
    var sticky = document.createElement('a');
    sticky.href = '#wanelo-atc';
    sticky.className = 'wanelo-sticky-atc';
    sticky.setAttribute('data-wanelo-atc-link', '');
    sticky.innerHTML = 'Add to cart <span class="wanelo-sticky-arrow">\u2191</span>';
    document.body.appendChild(sticky);
    var stickyIO = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { sticky.classList.toggle('visible', !e.isIntersecting); });
    }, { threshold: 0 });
    stickyIO.observe(atcAnchor);
  }

  /* Smooth-scroll for any [data-wanelo-atc-link] (added at document level
     so the sticky link injected above also gets it). */
  document.addEventListener('click', function (e) {
    var link = e.target.closest && e.target.closest('[data-wanelo-atc-link]');
    if (!link) return;
    var href = link.getAttribute('href');
    if (!href || href.charAt(0) !== '#') return;
    var target = document.querySelector(href);
    if (!target) return;
    e.preventDefault();
    target.scrollIntoView({
      behavior: mqReduce ? 'auto' : 'smooth',
      block: 'start'
    });
  });

  /* Hero parallax — translate Y at 0.4× scroll rate. Desktop only,
     reduced-motion respected. Read via rAF for smoothness. */
  if (!mqReduce && mqDesk) {
    var parallaxEls = page.querySelectorAll('[data-parallax]');
    if (parallaxEls.length) {
      var rafId = 0, lastY = -1;
      var tick = function () {
        rafId = 0;
        var y = window.pageYOffset || 0;
        if (y === lastY) return;
        lastY = y;
        parallaxEls.forEach(function (el) {
          var rate = parseFloat(el.getAttribute('data-parallax')) || 0.4;
          var rect = el.getBoundingClientRect();
          /* Only translate while element is roughly in view. */
          if (rect.bottom > -200 && rect.top < window.innerHeight + 200) {
            var top = rect.top + y;
            /* Anchor parallax to "scroll progress past the element's natural
               top" — clamp to >= 0 so the image NEVER translates upward into
               content above it (which on a stacked hero would overlap the
               CTA buttons). At scrollY=0, offset is 0 → photo sits at its
               natural position. */
            var progress = Math.max(0, y - top);
            var offset = progress * rate;
            el.style.transform = 'translate3d(0,' + offset.toFixed(1) + 'px,0)';
          }
        });
      };
      window.addEventListener('scroll', function () {
        if (!rafId) rafId = window.requestAnimationFrame(tick);
      }, { passive: true });
      tick();
    }
  }

  /* Sticky-story — IO toggles .has-sticky-active on each row when it
     enters viewport (used for entrance reveal of in-row text). Sticky
     positioning itself is pure CSS; this hook is for analytics + future
     scroll-linked effects. Disabled below 1024px and under reduced-motion. */
  if (!mqReduce && mqDesk && 'IntersectionObserver' in window) {
    var storyRows = page.querySelectorAll('.wanelo-story-row.is-sticky');
    if (storyRows.length) {
      var storyIO = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          e.target.classList.toggle('has-sticky-active', e.isIntersecting);
        });
      }, { threshold: 0.25 });
      storyRows.forEach(function (r) { storyIO.observe(r); });
    }
  }

  /* Video-demo lazy-load — click the poster to swap in the real player.
     No third-party request until the user opts in (privacy + perf).
     Direct source → <video controls autoplay>; YouTube/Vimeo → <iframe>. */
  page.querySelectorAll('.wanelo-video-demo__poster').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var src = btn.getAttribute('data-video-embed');
      var source = btn.getAttribute('data-video-source') || 'youtube';
      if (!src) return;
      var frame = btn.parentNode;
      var el;
      if (source === 'direct') {
        el = document.createElement('video');
        el.src = src;
        el.controls = true;
        if (!mqReduce) el.autoplay = true;
        el.playsInline = true;
      } else {
        el = document.createElement('iframe');
        el.src = src;
        el.setAttribute('allow', 'autoplay; encrypted-media; picture-in-picture');
        el.setAttribute('allowfullscreen', '');
        el.setAttribute('title', 'Product demo video');
        el.setAttribute('loading', 'lazy');
      }
      frame.replaceChild(el, btn);
    });
  });

  /* Subscription-refill toggle — visual-only state swap between
     "One-time" and "Subscribe" option cards. Actual cart logic is the
     operator's responsibility (Recharge / Skio / Shopify Subscriptions). */
  page.querySelectorAll('[data-subscription-toggle]').forEach(function (group) {
    var opts = group.querySelectorAll('.wanelo-subscription-refill__option');
    opts.forEach(function (opt) {
      opt.addEventListener('click', function () {
        opts.forEach(function (o) { o.classList.remove('is-active'); });
        opt.classList.add('is-active');
      });
    });
  });

  /* Move .wanelo-page INTO the Hyper-theme `.product` flex container
     so visually the long-form description is part of the same product
     card (one DOM block, no two-card overlap-coordination needed).
     The container is `<product-info> > .shopify-section > .product`
     in Hyper-new theme. We append wanelo as a full-width flex child
     at the END (after image gallery + product details column). */
  var prodCard = document.querySelector('product-info .product, .product.product--vertical, .product.flex.flex-wrap');
  if (prodCard && page && prodCard !== page.parentNode) {
    /* Wrap so we can force full-width inside the flex container */
    var wrap = document.createElement('div');
    wrap.className = 'wanelo-merged-wrap';
    wrap.style.flexBasis = '100%';
    wrap.style.width = '100%';
    prodCard.appendChild(wrap);
    wrap.appendChild(page);
  }

  /* Rating relocation block removed 2026-05-27 — wanelo-rating snippet
     no longer rendered (synthetic star count was a fake trust signal).
     If real-review sync (Judge.me / Loox / Stamped) is wired later,
     restore the snippet render in wanelo-product-page.liquid and the
     priceTarget lookup + slot insertion here. */

  /* Collapse-card toggle — long-form description is clipped to
     `max-height: 680px` by CSS; this button removes the clip on click.
     If natural content height fits the clip threshold, the toggle hides
     itself (no point showing it). */
  var collapseEl = page.querySelector('[data-wanelo-collapse]');
  var toggleEl = page.querySelector('[data-wanelo-toggle]');
  if (collapseEl && toggleEl) {
    var inner = collapseEl.querySelector('.wanelo-page__collapse-inner');
    var checkOverflow = function () {
      if (!inner) return;
      var natural = inner.scrollHeight;
      var clipped = collapseEl.clientHeight;
      /* Hide toggle if content already fits */
      toggleEl.hidden = natural <= clipped + 20;
    };
    /* Recompute after fonts/images settle */
    if (document.readyState === 'complete') checkOverflow();
    else window.addEventListener('load', checkOverflow, { once: true });
    setTimeout(checkOverflow, 800);

    toggleEl.addEventListener('click', function () {
      var expanded = collapseEl.classList.toggle('is-expanded');
      toggleEl.setAttribute('aria-expanded', expanded ? 'true' : 'false');
      toggleEl.querySelector('.wanelo-page__toggle-more').hidden = expanded;
      toggleEl.querySelector('.wanelo-page__toggle-less').hidden = !expanded;
      /* When collapsing back, scroll to keep the toggle in view */
      if (!expanded) {
        var rect = collapseEl.getBoundingClientRect();
        if (rect.top < 0) {
          collapseEl.scrollIntoView({ behavior: mqReduce ? 'auto' : 'smooth', block: 'start' });
        }
      }
    });
  }
})();
