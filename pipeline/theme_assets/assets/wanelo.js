// WANELO Reveal-on-scroll IntersectionObserver
// Adds class "in" to .reveal/.mask elements when they enter viewport.
// CSS transitions then animate them into view.
(function () {
  if (!('IntersectionObserver' in window)) return;
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting) {
        e.target.classList.add('in');
        io.unobserve(e.target);
      }
    });
  }, { threshold: 0.1, rootMargin: '0px 0px -8% 0px' });
  document.querySelectorAll('.wanelo-page .reveal, .wanelo-page .mask').forEach(function (el) {
    io.observe(el);
  });
})();
