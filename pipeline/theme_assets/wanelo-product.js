/* WANELO Reveal-on-scroll observer
 * Source: pipeline/page_builder.py BASIC_JS
 */

// ===== Reveal on scroll =====
const io = new IntersectionObserver((entries)=>{
  entries.forEach(e=>{ if(e.isIntersecting){ e.target.classList.add('in'); io.unobserve(e.target); } });
}, {threshold:.1, rootMargin:'0px 0px -8% 0px'});
document.querySelectorAll('.reveal, .words, .mask').forEach(el=>io.observe(el));