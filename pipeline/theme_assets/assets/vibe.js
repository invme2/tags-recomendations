/* Wanelo Vibe — shared interactions: favourite toggle, add-to-cart (AJAX), night mode, filter accordions. */
(function(){
  function ready(fn){ if(document.readyState!=='loading') fn(); else document.addEventListener('DOMContentLoaded', fn); }
  ready(function(){
    // favourite toggle (visual)
    document.querySelectorAll('[data-fav]').forEach(function(b){
      b.addEventListener('click', function(e){ e.preventDefault(); b.classList.toggle('on');
        var sv=b.querySelector('svg'); if(sv) sv.setAttribute('fill', b.classList.contains('on')?'var(--neon-mag)':'none'); });
    });
    // night mode
    var vh=document.querySelector('.vibe-home, .vibe-page');
    document.querySelectorAll('[data-night-toggle]').forEach(function(nt){
      if(vh){ try{ if(localStorage.getItem('vibe_night')==='1') vh.classList.add('night'); }catch(e){} }
      nt.addEventListener('click', function(){ if(!vh) return; vh.classList.toggle('night');
        try{ localStorage.setItem('vibe_night', vh.classList.contains('night')?'1':'0'); }catch(e){} });
    });
    // add to cart (AJAX) — delegated so dynamically-added cards (personalized feed) also work
    document.addEventListener('click', function(ev){
      var b = ev.target.closest && ev.target.closest('[data-add]'); if(!b) return;
      var id=b.getAttribute('data-add'); if(!id || b.classList.contains('added')) return;
      b.classList.add('added'); var old=b.innerHTML; b.textContent='✓ In cart';
      fetch('/cart/add.js',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({items:[{id:id,quantity:1}]})})
        .then(function(r){return r.json()}).then(function(){ var c=document.querySelector('.fhdr .ficon .cnt');
          if(c){ c.textContent=(parseInt(c.textContent||'0')+1); } else { var cart=document.querySelector('.fhdr .ficon[href*="cart"]'); if(cart){ var s=document.createElement('span'); s.className='cnt'; s.textContent='1'; cart.appendChild(s); } }
          setTimeout(function(){ b.classList.remove('added'); b.innerHTML=old; },1500); })
        .catch(function(){ b.classList.remove('added'); b.innerHTML=old; });
    });
    // filter group accordions (collection sidebar)
    document.querySelectorAll('.ffg__h').forEach(function(h){
      h.addEventListener('click', function(e){ e.preventDefault(); h.closest('.ffg').classList.toggle('closed'); });
    });
    // mobile filter drawer
    var fside=document.querySelector('.fcat-side');
    document.querySelectorAll('[data-filters-open]').forEach(function(b){ b.addEventListener('click',function(){ if(fside) fside.classList.add('open'); document.body.style.overflow='hidden'; }); });
    document.querySelectorAll('[data-filters-close]').forEach(function(b){ b.addEventListener('click',function(){ if(fside) fside.classList.remove('open'); document.body.style.overflow=''; }); });
    document.addEventListener('click',function(e){ if(fside && fside.classList.contains('open') && !fside.contains(e.target) && !e.target.closest('[data-filters-open]')){ fside.classList.remove('open'); document.body.style.overflow=''; } });

    // product card photo carousel (hover-zones desktop, swipe mobile)
    function initVpc(scope){
      (scope||document).querySelectorAll('[data-vpc]').forEach(function(vpc){
        if(vpc.getAttribute('data-vpc-ready')) return; vpc.setAttribute('data-vpc-ready','1');
        var slides=vpc.querySelectorAll('.vpc__slide'); if(slides.length<2) return;
        var wrap=vpc.closest('.fpcard__img'); var dots=wrap?wrap.querySelectorAll('.vpc__dots i'):[];
        var idx=0, moved=false, loaded=false;
        function loadAll(){ if(loaded)return; loaded=true; slides.forEach(function(s){ var d=s.getAttribute('data-src'); if(d && !s.getAttribute('src')){ s.src=d; } }); }
        function show(i){ i=Math.max(0,Math.min(slides.length-1,i)); if(i===idx)return; slides[idx].classList.remove('on'); slides[i].classList.add('on'); if(dots[idx])dots[idx].classList.remove('on'); if(dots[i])dots[i].classList.add('on'); idx=i; }
        if(wrap){ wrap.addEventListener('mouseenter', loadAll);
          wrap.addEventListener('mousemove',function(e){ var r=wrap.getBoundingClientRect(); if(!r.width) return; show(Math.floor((e.clientX-r.left)/r.width*slides.length)); });
          wrap.addEventListener('mouseleave',function(){ show(0); }); }
        var sx=null;
        vpc.addEventListener('touchstart',function(e){ loadAll(); sx=e.touches[0].clientX; moved=false; },{passive:true});
        vpc.addEventListener('touchmove',function(e){ if(sx===null)return; var dx=e.touches[0].clientX-sx; if(Math.abs(dx)>30){ show(idx+(dx<0?1:-1)); sx=e.touches[0].clientX; moved=true; } },{passive:true});
        vpc.addEventListener('touchend',function(){ sx=null; });
        if(wrap&&wrap.tagName==="A"){ wrap.addEventListener('click',function(e){ if(moved){ e.preventDefault(); moved=false; } }); }
      });
    }
    initVpc(document);
    // re-init for dynamically-added cards (personalized-feed infinite scroll, theme editor)
    document.addEventListener('shopify:section:load', function(){ initVpc(document); });
    var pfFeed=document.querySelector('.personalized-feed-section');
    if(pfFeed && 'MutationObserver' in window){ var pfDeb=null; new MutationObserver(function(){ if(pfDeb) return; pfDeb=setTimeout(function(){ pfDeb=null; initVpc(pfFeed); }, 120); }).observe(pfFeed, {childList:true, subtree:true}); }

    // ── feed scroll restoration: return to the same spot when coming back from a product ──
    var FEED='.personalized-feed-section';
    function vibeY(){ return window.scrollY || window.pageYOffset || document.documentElement.scrollTop || 0; }
    document.addEventListener('click', function(e){ var a=e.target.closest(FEED+' a[href*="/products/"]'); if(a){ try{ sessionStorage.setItem('vibe_feed_y', String(Math.round(vibeY()))); sessionStorage.setItem('vibe_feed_t', String(Date.now())); }catch(_){} } }, true);
    function vibeRestoreFeed(){
      if(!document.querySelector(FEED)) return;
      var fy=0, ft=0; try{ fy=parseInt(sessionStorage.getItem('vibe_feed_y')||'0',10); ft=parseInt(sessionStorage.getItem('vibe_feed_t')||'0',10); }catch(_){}
      if(!(fy>120 && (Date.now()-ft)<1800000)) return;
      try{ sessionStorage.removeItem('vibe_feed_y'); sessionStorage.removeItem('vibe_feed_t'); }catch(_){}
      try{ if('scrollRestoration' in history) history.scrollRestoration='manual'; }catch(_){}
      var dl=Date.now()+6000, last=-1, stall=0;
      (function chase(){
        window.scrollTo(0, fy);
        var y=vibeY();
        if(Math.abs(y-fy)<=6 || Date.now()>dl){ setTimeout(function(){ try{ if('scrollRestoration' in history) history.scrollRestoration='auto'; }catch(_){} }, 400); return; }
        if(y===last){ stall++; } else { stall=0; }
        last=y;
        if(stall>4){ window.scrollTo(0, document.body.scrollHeight); } // nudge the feed to reveal/load more
        requestAnimationFrame(chase);
      })();
    }
    vibeRestoreFeed();
    window.addEventListener('pageshow', function(e){ if(e.persisted){ setTimeout(vibeRestoreFeed, 60); } });

    // catalog category dropdown (Catalog button -> categories)
    (function(){
      var btn=document.querySelector('[data-catmenu-toggle]');
      var pop=document.querySelector('[data-catmenu]');
      var bg=document.querySelector('[data-catmenu-bg]');
      if(!btn||!pop) return;
      function isM(){ return window.innerWidth<=760; }
      function place(){ if(isM()){ pop.style.top=''; pop.style.left=''; pop.style.width=''; return; } var r=btn.getBoundingClientRect(); var w=Math.min(640, window.innerWidth-28); var left=Math.min(r.left, window.innerWidth-w-14); if(left<14)left=14; pop.style.width=w+'px'; pop.style.top=(r.bottom+10)+'px'; pop.style.left=left+'px'; }
      function open(){ place(); pop.classList.add('open'); if(bg)bg.classList.add('open'); btn.classList.add('on'); btn.setAttribute('aria-expanded','true'); if(isM()) document.body.style.overflow='hidden'; }
      function close(){ pop.classList.remove('open'); if(bg)bg.classList.remove('open'); btn.classList.remove('on'); btn.setAttribute('aria-expanded','false'); document.body.style.overflow=''; }
      btn.addEventListener('click', function(e){ e.preventDefault(); if(pop.classList.contains('open')) close(); else open(); });
      if(bg) bg.addEventListener('click', close);
      document.querySelectorAll('[data-catmenu-close]').forEach(function(c){ c.addEventListener('click', close); });
      document.addEventListener('click', function(e){ if(!pop.classList.contains('open')) return; if(pop.contains(e.target)||btn.contains(e.target)) return; close(); });
      document.addEventListener('keydown', function(e){ if((e.key==='Escape'||e.key==='Esc') && pop.classList.contains('open')) close(); });
      window.addEventListener('resize', function(){ if(pop.classList.contains('open')) place(); });
    })();
  });
})();
