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
    // add to cart (AJAX)
    document.querySelectorAll('[data-add]').forEach(function(b){
      b.addEventListener('click', function(){ var id=b.getAttribute('data-add'); if(!id) return;
        b.classList.add('added'); var old=b.innerHTML; b.textContent='✓ In cart';
        fetch('/cart/add.js',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({items:[{id:id,quantity:1}]})})
          .then(function(r){return r.json()}).then(function(){ var c=document.querySelector('.fhdr .ficon .cnt');
            if(c){ c.textContent=(parseInt(c.textContent||'0')+1); } else { var cart=document.querySelector('.fhdr .ficon[href*="cart"]'); if(cart){ var s=document.createElement('span'); s.className='cnt'; s.textContent='1'; cart.appendChild(s); } }
            setTimeout(function(){ b.classList.remove('added'); b.innerHTML=old; },1500); })
          .catch(function(){ b.classList.remove('added'); b.innerHTML=old; }); });
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
    document.querySelectorAll('[data-vpc]').forEach(function(vpc){
      var slides=vpc.querySelectorAll('.vpc__slide'); if(slides.length<2) return;
      var wrap=vpc.closest('.fpcard__img'); var dots=wrap?wrap.querySelectorAll('.vpc__dots i'):[];
      var idx=0, moved=false, loaded=false;
      function loadAll(){ if(loaded)return; loaded=true; slides.forEach(function(s){ var d=s.getAttribute('data-src'); if(d && !s.getAttribute('src')){ s.src=d; } }); }
      function show(i){ i=Math.max(0,Math.min(slides.length-1,i)); if(i===idx)return; slides[idx].classList.remove('on'); slides[i].classList.add('on'); if(dots[idx])dots[idx].classList.remove('on'); if(dots[i])dots[i].classList.add('on'); idx=i; }
      if(wrap){ wrap.addEventListener('mouseenter', loadAll);
        wrap.addEventListener('mousemove',function(e){ var r=wrap.getBoundingClientRect(); show(Math.floor((e.clientX-r.left)/r.width*slides.length)); });
        wrap.addEventListener('mouseleave',function(){ show(0); }); }
      var sx=null;
      vpc.addEventListener('touchstart',function(e){ loadAll(); sx=e.touches[0].clientX; moved=false; },{passive:true});
      vpc.addEventListener('touchmove',function(e){ if(sx===null)return; var dx=e.touches[0].clientX-sx; if(Math.abs(dx)>30){ show(idx+(dx<0?1:-1)); sx=e.touches[0].clientX; moved=true; } },{passive:true});
      vpc.addEventListener('touchend',function(){ sx=null; });
      if(wrap&&wrap.tagName==="A"){ wrap.addEventListener('click',function(e){ if(moved){ e.preventDefault(); moved=false; } }); }
    });

    // ── feed scroll restoration: come back from a product to the same spot in the feed ──
    var FEED='.personalized-feed-section';
    document.addEventListener('click', function(e){ var a=e.target.closest(FEED+' a[href*="/products/"]'); if(a){ try{ sessionStorage.setItem('vibe_feed_y', String(Math.round(window.scrollY))); sessionStorage.setItem('vibe_feed_t', String(Date.now())); }catch(_){} } }, true);
    if(document.querySelector(FEED)){
      var fy=0, ft=0; try{ fy=parseInt(sessionStorage.getItem('vibe_feed_y')||'0',10); ft=parseInt(sessionStorage.getItem('vibe_feed_t')||'0',10); }catch(_){}
      if(fy>150 && (Date.now()-ft)<900000){
        try{ if('scrollRestoration' in history) history.scrollRestoration='manual'; }catch(_){}
        var n=0, iv=setInterval(function(){ n++; if(document.body.scrollHeight>=fy+window.innerHeight){ window.scrollTo(0,fy); clearInterval(iv); } else { window.scrollTo(0,document.body.scrollHeight); } if(n>45){ clearInterval(iv); window.scrollTo(0,Math.min(fy,document.body.scrollHeight)); } }, 90);
        setTimeout(function(){ try{ sessionStorage.removeItem('vibe_feed_y'); sessionStorage.removeItem('vibe_feed_t'); }catch(_){} try{ if('scrollRestoration' in history) history.scrollRestoration='auto'; }catch(_){} }, 4200);
      }
    }
  });
})();
