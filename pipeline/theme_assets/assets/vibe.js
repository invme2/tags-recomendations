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
  });
})();
