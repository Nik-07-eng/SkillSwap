(() => {
  const $ = (s, root=document) => root.querySelector(s);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const api = async (url, options={}) => {
    const response = await fetch(url, {credentials:'include', cache:'no-store', ...options, headers:{...(options.body?{'Content-Type':'application/json'}:{}), ...(options.headers||{})}});
    let data={}; try { data=await response.json(); } catch {}
    if(!response.ok){const error=new Error(data.error || 'Could not complete this action.');error.status=response.status;throw error;}
    return data;
  };
  let current=null;
  const notify=(message,isError=false)=>{
    if(typeof window.toast==='function') window.toast(message,isError);
    else {const box=$('#toast');if(box){box.textContent=message;box.classList.add('show');setTimeout(()=>box.classList.remove('show'),3000);}}
  };
  const dateLabel=value=>{if(!value)return '';const d=new Date(`${value}T12:00:00`);return d.toLocaleDateString(undefined,{day:'numeric',month:'short'});};
  const link=(url,label)=>url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${label} ↗</a>`:'';

  function renderCompetition(c, loggedIn){
    const box=$('#arenaContest'); if(!box)return;
    const own=c.my_submission;
    box.innerHTML=`<div class="arena-contest-top"><div><span class="arena-live-tag"><i></i> THIS WEEK'S CHALLENGE</span><span class="arena-theme">${esc(c.theme)}</span></div><span class="arena-week-pill">WEEK ${esc(c.week_key.slice(-2))}</span></div><div class="arena-contest-content"><div class="arena-contest-copy"><h2>${esc(c.title)}</h2><p>${esc(c.brief)}</p><div class="arena-deliverables"><b>WHAT TO SUBMIT</b><span>${esc(c.deliverables)}</span></div><div class="arena-contest-meta"><span>◷ ${dateLabel(c.starts_on)} – ${dateLabel(c.ends_on)}</span><span>✦ ${c.submission_count} entr${c.submission_count===1?'y':'ies'}</span><span>⌛ ${c.is_open?`${c.days_left} day${c.days_left===1?'':'s'} left`:'Submission closed'}</span></div></div><div class="arena-contest-art"><div class="arena-trophy-orbit"><span>🏆</span><i></i><b></b></div><strong>${c.is_open?'OPEN FOR ENTRIES':'CLOSED'}</strong><small>${own?'Your entry is published':(loggedIn?'Your idea belongs here':'Log in to participate')}</small></div></div>`;
    const form=$('#arenaSubmitForm');
    if(form){
      form.elements.title.value=own?.title||'';form.elements.description.value=own?.description||'';form.elements.demo_url.value=own?.demo_url||'';form.elements.repo_url.value=own?.repo_url||'';form.elements.tags.value=(own?.tags||[]).join(', ');
      const hint=$('#arenaSubmitHint'); if(hint)hint.textContent=!loggedIn?'Sign in to submit. One entry per learner; you can edit it until the deadline.':own?'Your entry is live. You can edit and republish it before the deadline.':'Your first published entry earns 50 Quest XP. One entry per learner this week.';
      form.querySelector('button[type="submit"]').disabled=!c.is_open;
      [...form.elements].forEach(el=>{if(el.name)el.disabled=!c.is_open;});
    }
  }
  function renderEntries(c, loggedIn){
    const box=$('#arenaEntries'); if(!box)return;
    if(!c.submissions.length){box.innerHTML='<div class="arena-empty"><span>✦</span><h3>Be the first creator this week.</h3><p>Build a small, thoughtful solution and share it with the SkillSwap community.</p></div>';return;}
    box.innerHTML=c.submissions.map((s,i)=>`<article class="arena-entry-card"><div class="arena-entry-top"><span class="arena-entry-rank">#${i+1}</span><div class="arena-entry-author"><span class="arena-entry-avatar">${esc((s.user_name||'L').trim().slice(0,1).toUpperCase())}</span><span><b>${esc(s.user_name)}</b><small>${s.created_at?new Date(s.created_at).toLocaleDateString():''}</small></span></div><span class="arena-vote-count">♥ ${s.votes} vote${s.votes===1?'':'s'}</span></div><h3>${esc(s.title)}</h3><p class="arena-entry-description">${esc(s.description)}</p>${s.tags?.length?`<div class="arena-entry-tags">${s.tags.map(t=>`<span>${esc(t)}</span>`).join('')}</div>`:''}<div class="arena-entry-footer"><div class="arena-entry-links">${link(s.demo_url,'Live demo')}${link(s.repo_url,'Source code')}</div><div class="arena-entry-actions">${s.is_owner?'<span class="arena-own-entry">Your entry</span>':loggedIn?`<button type="button" class="arena-vote-button ${s.voted?'voted':''}" data-arena-vote="${s.id}" aria-pressed="${s.voted}">${s.voted?'♥ Voted':'♡ Support this'}</button>`:'<span class="muted">Log in to vote</span>'}</div></div></article>`).join('');
  }
  function renderLeaderboard(c){
    const box=$('#arenaLeaderboard');if(!box)return;
    if(!c.submissions.length){box.innerHTML='<p class="muted">The leaderboard will appear when the first entries arrive.</p>';return;}
    box.innerHTML=c.submissions.slice(0,8).map((s,i)=>`<div class="arena-leader-row"><span class="arena-leader-rank ${i===0?'first':''}">${i===0?'🏆':`#${i+1}`}</span><span><b>${esc(s.title)}</b><small>${esc(s.user_name)}</small></span><strong>${s.votes} ♥</strong></div>`).join('');
  }
  async function load(){
    const entries=$('#arenaEntries');if(entries)entries.innerHTML='<div class="empty-state">Loading this week’s entries…</div>';
    try{
      const data=await api('/api/arena');current=data.competition;
      renderCompetition(current,data.logged_in);renderEntries(current,data.logged_in);renderLeaderboard(current);
    }catch(error){if(entries)entries.innerHTML=`<div class="empty-state">${esc(error.message)}</div>`;}
  }
  async function submit(event){
    event.preventDefault();
    const form=event.currentTarget;
    if(!window.skillSwapUserId){$('#topAuth')?.click();notify('Please log in to enter this week’s competition.');return;}
    const button=form.querySelector('button[type="submit"]');button.disabled=true;button.textContent='Publishing…';
    const payload=Object.fromEntries(new FormData(form).entries());
    try{
      const data=await api('/api/arena/submit',{method:'POST',body:JSON.stringify(payload)});
      current=data.competition;renderCompetition(current,true);renderEntries(current,true);renderLeaderboard(current);
      notify(data.message+(data.xp_awarded?` +${data.xp_awarded} Quest XP!`:''));
      if(window.questRefresh)window.questRefresh();
    }catch(error){notify(error.message,true);if(error.status===401)$('#topAuth')?.click();}
    finally{button.disabled=!current?.is_open;button.textContent='Publish my entry ↗';}
  }
  async function vote(id,button){
    button.disabled=true;
    try{const data=await api(`/api/arena/submissions/${id}/vote`,{method:'POST',body:JSON.stringify({})});notify(data.message);await load();}
    catch(error){notify(error.message,true);if(error.status===401)$('#topAuth')?.click();}
    finally{button.disabled=false;}
  }
  document.addEventListener('submit',event=>{if(event.target?.id==='arenaSubmitForm')submit(event);});
  document.addEventListener('click',event=>{const voteButton=event.target.closest('[data-arena-vote]');if(voteButton)vote(voteButton.dataset.arenaVote,voteButton);});
  $('#arenaRefresh')?.addEventListener('click',load);
  window.arenaLoad=load;
})();
