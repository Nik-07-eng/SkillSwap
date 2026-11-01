/* SkillSwap Treasure Hunt — daily server-verified collectibles hidden in app sections. */
(()=>{
  const $=id=>document.getElementById(id);
  const panel=$('treasureHuntPanel'); if(!panel)return;
  let state=null, busy=false, markers=new Map();
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',credentials:'same-origin',cache:'no-store',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});const d=await r.json().catch(()=>({}));if(!r.ok){const e=new Error(d.error||'Treasure hunt request failed.');e.status=r.status;throw e;}return d;}
  function message(text,kind=''){const el=$('treasureMessage');el.textContent=text;el.className='treasure-message'+(kind?' '+kind:'');}
  function render(){if(!state)return;
    $('treasureCount').textContent=`${state.collected}/${state.total}`;
    $('treasureProgressBar').style.width=`${state.total?state.collected/state.total*100:0}%`;
    $('treasureXpEarned').textContent=`⚡ ${state.xp_earned} XP collected`;
    $('treasureXpLeft').textContent=state.collected===state.total?'All treasures found!':`${state.xp_available} XP still hidden`;
    $('treasureClues').innerHTML=state.items.map((item,i)=>`<article class="treasure-clue-card ${item.collected?'is-found':''}" data-treasure-card="${esc(item.id)}"><div class="treasure-clue-icon">${item.collected?item.icon:'❔'}</div><div class="treasure-clue-copy"><span>${item.collected?'COLLECTED':`CLUE 0${i+1}`} · ${esc(item.area)}</span><b>${item.collected?esc(item.name):'Unknown collectible'}</b><p>${item.collected?'This treasure is safely in your collection.':esc(item.clue)}</p><small>${item.collected?`+${item.xp} XP added`:`Worth ${item.xp} XP`}</small></div><button type="button" class="treasure-find-btn" data-treasure-go="${esc(item.location)}" ${item.collected?'disabled':''}>${item.collected?'✓ Found':'Find it ↗'}</button></article>`).join('');
    state.items.forEach(item=>{if(item.collected)removeMarker(item.id);else ensureMarker(item);});
  }
  function removeMarker(id){const el=markers.get(id);if(el)el.remove();markers.delete(id);}
  function ensureMarker(item){
    const view=document.getElementById(`view-${item.location}`);if(!view)return;
    let btn=markers.get(item.id);
    if(!btn){btn=document.createElement('button');btn.type='button';btn.className='treasure-hidden-marker';btn.setAttribute('aria-label',`Hidden treasure in ${item.area}; collect ${item.xp} XP`);btn.innerHTML=`<span>✦</span><small>FOUND?</small>`;btn.addEventListener('click',()=>collect(item,btn));view.appendChild(btn);markers.set(item.id,btn);}
    btn.hidden=!view.classList.contains('active');
  }
  function syncMarkers(){if(!state)return;state.items.forEach(item=>{if(!item.collected)ensureMarker(item);});}
  async function collect(item,btn){if(busy||item.collected)return;busy=true;btn.disabled=true;btn.classList.add('is-collecting');try{const d=await api('/api/treasure-hunt/collect',{collectible_id:item.id,token:item.token});state=d.treasure_hunt;render();message(`🎉 ${item.name} discovered! +${d.xp_awarded} XP added to your Quest profile.`,'success');window.dispatchEvent(new CustomEvent('skillswap:xp-updated',{detail:d}));if(window.questRefresh)window.questRefresh();}catch(e){message(e.message,'error');btn.disabled=false;btn.classList.remove('is-collecting');if(e.status===403||e.status===409)load();}finally{busy=false;}}
  function navigate(location){const view=document.getElementById(`view-${location}`);if(!view)return;const nav=document.querySelector(`[data-view="${CSS.escape(location)}"]`);if(nav)nav.click();else{document.querySelectorAll('.view').forEach(v=>v.classList.toggle('active',v===view));}setTimeout(()=>{syncMarkers();view.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});},120);}
  async function load(){try{const d=await api('/api/treasure-hunt');state=d.treasure_hunt;$('treasureLogin').hidden=true;render();}catch(e){if(e.status===401){$('treasureLogin').hidden=false;$('treasureClues').innerHTML='';}else message(e.message,'error');}}
  $('treasureClues').addEventListener('click',e=>{const b=e.target.closest('[data-treasure-go]');if(b&&!b.disabled)navigate(b.dataset.treasureGo);});
  const observer=new MutationObserver(syncMarkers);document.querySelectorAll('.view').forEach(v=>observer.observe(v,{attributes:true,attributeFilter:['class']}));
  window.addEventListener('skillswap:auth-changed',load);document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')syncMarkers();});
  load();
})();
