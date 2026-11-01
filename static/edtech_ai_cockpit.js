/* SkillSwap EdTech + AI cockpit. Uses the existing authenticated profile and Smart Match APIs. */
(()=>{
  const $=s=>document.querySelector(s), esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const stage=$('#skillMapStage'), list=$('#aiRecommendationList'); if(!stage||!list)return;
  let user=null, matches=[];
  const api=async path=>{const r=await fetch(path,{credentials:'include',cache:'no-store'});let d={};try{d=await r.json()}catch{}if(!r.ok)throw new Error(d.error||'Could not load this information.');return d};
  function renderMap(){
    const teach=Array.isArray(user?.teach)?user.teach:[], learn=Array.isArray(user?.learn)?user.learn:[];
    if(!user){stage.innerHTML='<div class="skill-map-empty"><span>✦</span><b>Your map begins with you.</b><p>Log in and add skills you can teach and want to learn to create a living map of your knowledge.</p><button type="button" data-cockpit-login>Build my skill map ↗</button></div>';stage.querySelector('[data-cockpit-login]')?.addEventListener('click',()=>document.querySelector('#topCta')?.click());return}
    const nodes=[...teach.slice(0,5).map((s,i)=>({s,kind:'teach',x:105,y:68+i*69})),...learn.slice(0,5).map((s,i)=>({s,kind:'learn',x:Math.max(0,stage.clientWidth-105),y:68+i*69}))];
    const width=Math.max(320,stage.clientWidth||620), height=Math.max(260,Math.min(420,Math.max(teach.length,learn.length,2)*69+80));
    const cx=width/2,cy=height/2; const positions=nodes.map(n=>({...n,x:n.kind==='teach'?Math.max(92,cx- Math.min(205,width*.31)):Math.min(width-92,cx+Math.min(205,width*.31))}));
    const lines=positions.map((n,i)=>`<path class="map-link ${n.kind}" d="M ${cx} ${cy} Q ${(cx+n.x)/2} ${(cy+n.y)/2-18} ${n.x} ${n.y}" style="--delay:${i*.08}s"/>`).join('');
    const dots=positions.map((n,i)=>`<g class="map-node ${n.kind}" transform="translate(${n.x},${n.y})" tabindex="0" role="img" aria-label="${esc(n.kind==='teach'?'Can teach':'Wants to learn')}: ${esc(n.s)}"><circle class="node-halo" r="27"/><circle class="node-core" r="19"/><text class="node-symbol" text-anchor="middle" y="5">${n.kind==='teach'?'↗':'✧'}</text><text class="node-label" text-anchor="middle" y="39">${esc(n.s.length>19?n.s.slice(0,17)+'…':n.s)}</text></g>`).join('');
    stage.innerHTML=`<svg class="skill-map-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Interactive map of your teach and learn skills"><defs><radialGradient id="mapCore"><stop stop-color="#b6f7ed"/><stop offset="1" stop-color="#7668f0"/></radialGradient></defs><g class="map-grid-lines">${Array.from({length:7},(_,i)=>`<path d="M ${i*width/6} 0 V ${height}"/>`).join('')}${Array.from({length:5},(_,i)=>`<path d="M 0 ${i*height/4} H ${width}"/>`).join('')}</g>${lines}<g class="map-you" transform="translate(${cx},${cy})"><circle r="43" class="you-aura"/><circle r="31" class="you-core"/><text text-anchor="middle" y="5">YOU</text></g>${dots}</svg><div class="map-counts"><span><b>${teach.length}</b> skills you share</span><span><b>${learn.length}</b> skills to explore</span></div>`;
  }
  function renderRecommendations(){
    if(!user){list.innerHTML='<div class="ai-recommend-placeholder">Log in to receive recommendations based on your skills and community matches.</div>';return}
    const learn=user.learn||[], teach=user.teach||[];
    const rows=[];
    if(matches.length){matches.slice(0,2).forEach((m,i)=>{const p=m.user||{};rows.push({icon:'◎',title:`Connect with ${p.name||'a learning partner'}`,desc:`${m.score||0}% compatibility · ${(m.they_can_teach_me||[]).slice(0,2).join(', ')||'Shared learning interests'}`,tag:i===0?'TOP MATCH':'COMMUNITY MATCH',view:'matches'})})}
    if(learn.length){rows.push({icon:'⌁',title:`Build your ${learn[0]} roadmap`,desc:`Turn “${learn[0]}” into weekly milestones with a guided learning plan.`,tag:'PERSONALIZED PATH',view:'learning-path'})}
    else rows.push({icon:'＋',title:'Add a learning goal',desc:'Choose one skill you want to learn to unlock tailored roadmaps.',tag:'PROFILE TIP',view:'profile'});
    if(teach.length){rows.push({icon:'✦',title:`Share your ${teach[0]} knowledge`,desc:'Find learners who want a skill you can already teach.',tag:'GIVE & GROW',view:'matches'})}
    list.innerHTML=rows.slice(0,3).map(r=>`<button type="button" class="ai-recommend-item" data-open-view="${r.view}"><span class="recommend-icon">${r.icon}</span><span class="recommend-copy"><small>${r.tag}</small><b>${esc(r.title)}</b><em>${esc(r.desc)}</em></span><span class="recommend-arrow">↗</span></button>`).join('');
  }
  async function init(){
    try{const d=await api('/api/me');user=d.user||null;}catch{user=null}
    renderMap();
    if(user){try{const d=await api('/api/smart-matches');matches=d.matches||[]}catch{matches=[]}}
    renderRecommendations();
  }
  window.addEventListener('resize',()=>{if(user)renderMap()},{passive:true});
  document.addEventListener('click',e=>{if(e.target.closest('[data-open-view="matches"]')&&window.skillSwapRefreshMatches)window.skillSwapRefreshMatches()});
  window.addEventListener('skillswap:profile-updated',init);
  init();
})();
