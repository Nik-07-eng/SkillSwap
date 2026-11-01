/* SkillSwap Quest — persistent daily missions, XP, streaks and achievements. */
(()=>{
  const $=s=>document.querySelector(s);
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const localDay=()=>{const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`};
  let state=null, busy=false;
  async function questApi(path,options={}){
    const response=await fetch(path,{credentials:'include',cache:'no-store',...options,headers:{...(options.body?{'Content-Type':'application/json'}:{}),...(options.headers||{})}});
    let data={};try{data=await response.json()}catch{}
    if(!response.ok){const error=new Error(data.error||'Could not update your Quest progress.');error.status=response.status;throw error}return data;
  }
  function updateMini(){
    const q=state;if(!q)return;
    const xp=q.xp||0,within=q.level_progress||0;
    if($('#gamXp'))$('#gamXp').textContent=xp;
    if($('#gamLevel'))$('#gamLevel').textContent=`LEVEL ${q.level}`;
    if($('#levelPercent'))$('#levelPercent').textContent=`${within}%`;
    if($('#levelRing'))$('#levelRing').style.setProperty('--progress',`${within*3.6}deg`);
    if($('#xpBar'))$('#xpBar').style.width=`${within}%`;
    if($('#xpCaption'))$('#xpCaption').textContent=`${100-within} XP to Level ${q.level+1} · Earn XP through real learning activity.`;
    if($('#streakCount'))$('#streakCount').innerHTML=`${q.streak} <small>days</small>`;
    const badges=(q.achievements||[]).slice(0,4);
    if($('#achievementBadges'))$('#achievementBadges').innerHTML=badges.map(b=>`<span class="achievement ${b.unlocked?'unlocked':'locked'}" title="${b.unlocked?'Unlocked':'Locked'}: ${esc(b.name)}">${esc(b.icon)}<small>${esc(b.name)}</small></span>`).join('');
    if($('#achievementCaption'))$('#achievementCaption').textContent=`${(q.achievements||[]).filter(b=>b.unlocked).length} of ${(q.achievements||[]).length} achievements unlocked · ${q.total_checkins||0} check-ins`;
    const checkin=q.challenges?.find(c=>c.id==='daily_checkin');
    if($('#dailyCheckin')){ $('#dailyCheckin').disabled=!!checkin?.completed;$('#dailyCheckin').textContent=checkin?.completed?'✓ Check-in completed today':'Complete daily check-in  ＋'; }
  }
  function renderChallenges(){
    const box=$('#questChallenges');if(!box||!state)return;
    box.innerHTML=(state.challenges||[]).map((c,i)=>{
      const status=c.completed?'Completed':c.available?'Ready to claim':'Action needed';
      const action=c.completed?'<span class="quest-done-mark">✓ Completed</span>':c.id==='join_room'?`<button class="secondary-button quest-go-btn" data-quest-go="rooms">Open rooms ↗</button><button class="primary-button quest-claim-btn" data-quest-claim="${esc(c.id)}" ${!c.available?'disabled':''}>Claim +${c.points} XP</button>`:c.id==='room_chat'?`<button class="secondary-button quest-go-btn" data-quest-go="rooms">Open room chat ↗</button><button class="primary-button quest-claim-btn" data-quest-claim="${esc(c.id)}" ${!c.available?'disabled':''}>Claim +${c.points} XP</button>`:`<button class="primary-button quest-claim-btn" data-quest-claim="${esc(c.id)}" ${!c.available?'disabled':''}>${c.completed?'Completed':`Complete +${c.points} XP`}</button>`;
      return `<article class="quest-challenge ${c.completed?'is-complete':''}"><div class="quest-challenge-icon">${esc(c.icon)}</div><div class="quest-challenge-copy"><div class="quest-challenge-top"><span class="quest-step">MISSION 0${i+1}</span><span class="quest-status ${c.completed?'done':c.available?'ready':'pending'}">${status}</span></div><h3>${esc(c.title)}</h3><p>${esc(c.description)}</p><small>${esc(c.hint)}</small></div><div class="quest-challenge-reward"><b>+${c.points}</b><small>XP</small><div class="quest-challenge-actions">${action}</div></div></article>`;
    }).join('');
    box.querySelectorAll('[data-quest-claim]').forEach(btn=>btn.addEventListener('click',()=>complete(btn.dataset.questClaim,btn)));
    box.querySelectorAll('[data-quest-go]').forEach(btn=>btn.addEventListener('click',()=>window.showView?window.showView(btn.dataset.questGo):document.querySelector(`[data-view="${btn.dataset.questGo}"]`)?.click()));
  }
  function renderAchievements(){
    const box=$('#questAchievements');if(!box||!state)return;
    const list=state.achievements||[],unlocked=list.filter(a=>a.unlocked).length;
    if($('#questAchievementCount'))$('#questAchievementCount').textContent=`${unlocked} / ${list.length} unlocked`;
    box.innerHTML=list.map(a=>`<article class="quest-achievement ${a.unlocked?'unlocked':'locked'}"><span class="quest-achievement-icon">${esc(a.icon)}</span><div><b>${esc(a.name)}</b><p>${esc(a.description)}</p></div><span class="quest-achievement-state">${a.unlocked?'UNLOCKED':'LOCKED'}</span></article>`).join('');
  }
  function renderLeaderboard(){
    const box=$('#questLeaderboard');if(!box||!state)return;
    box.innerHTML=(state.leaderboard||[]).length?(state.leaderboard||[]).map((u,i)=>`<div class="quest-leader-row ${u.is_you?'is-you':''}"><span class="quest-rank">${i===0?'♛':'#'+(i+1)}</span><span class="quest-leader-avatar">${esc((u.name||'?').trim().charAt(0).toUpperCase())}</span><span class="quest-leader-name"><b>${esc(u.name)}${u.is_you?' · You':''}</b><small>Level ${u.level}</small></span><strong>${u.xp} <small>XP</small></strong></div>`).join(''):'<div class="quest-empty-small">Be the first learner to earn XP.</div>';
  }
  function render(){if(!state)return;updateMini();renderChallenges();renderAchievements();renderLeaderboard();
    if($('#questTotalXp'))$('#questTotalXp').textContent=state.xp.toLocaleString();
    if($('#questLevelLabel'))$('#questLevelLabel').textContent=`LEVEL ${state.level}`;
    if($('#questLevelBar'))$('#questLevelBar').style.width=`${state.level_progress}%`;
    if($('#questNextLevel'))$('#questNextLevel').textContent=`${100-state.level_progress} XP to Level ${state.level+1}`;
    if($('#questStreak'))$('#questStreak').innerHTML=`${state.streak} <em>days</em>`;
    if($('#questStreakNote'))$('#questStreakNote').textContent=state.streak>=7?'Amazing consistency — a full week of learning!':state.streak>=3?'Great momentum. Keep your daily check-ins going.':'Check in each day to build your streak.';
    if($('#questDoneToday'))$('#questDoneToday').textContent=`${state.completed_today} / ${state.challenges.length}`;
    if($('#questDateLabel'))$('#questDateLabel').textContent=new Date(`${state.day}T12:00:00`).toLocaleDateString(undefined,{weekday:'long',month:'long',day:'numeric',year:'numeric'});
    if($('#questWeekDots'))[...$('#questWeekDots').children].forEach((dot,i)=>dot.classList.toggle('active',i<Math.min(7,state.streak)));
  }
  async function load(){
    if(!$('#questChallenges'))return;
    if(!currentUser && !document.querySelector('#sideName')?.textContent?.trim())return;
    if(!currentUser && document.querySelector('#sideName')?.textContent==='Guest learner'){
      $('#questChallenges').innerHTML='<div class="quest-login-prompt"><span>⚡</span><h3>Your learning journey starts here.</h3><p>Log in to save XP, build your streak and unlock achievements.</p><button class="primary-button" id="questLoginBtn">Log in to Quest ↗</button></div>';
      $('#questLoginBtn')?.addEventListener('click',()=>document.querySelector('#topAuth')?.click());return;
    }
    try{const data=await questApi('/api/quest');state=data.quest;render();}
    catch(error){if(error.status===401){$('#questChallenges').innerHTML='<div class="quest-login-prompt"><h3>Log in to access your Quest.</h3><button class="primary-button" id="questLoginBtn">Log in ↗</button></div>';$('#questLoginBtn')?.addEventListener('click',()=>document.querySelector('#topAuth')?.click());}else if($('#questChallenges'))$('#questChallenges').innerHTML=`<div class="empty-state">${esc(error.message)} <button class="secondary-button" id="questRetry">Retry ↻</button></div>`;$('#questRetry')?.addEventListener('click',load);}
  }
  async function complete(id,button){if(busy)return;busy=true;if(button){button.disabled=true;button.textContent='Verifying…'}try{const result=await questApi('/api/quest/complete',{method:'POST',body:JSON.stringify({challenge_id:id})});state=result.quest;render();if(window.toast)toast(result.message||'Quest updated!');}catch(error){if(window.toast)toast(error.message,true);await load();}finally{busy=false;}}
  async function checkin(){if(!currentUser){document.querySelector('#topAuth')?.click();return;}const c=state?.challenges?.find(x=>x.id==='daily_checkin');if(c?.completed){if(window.toast)toast('You have already checked in today.');return;}const button=$('#dailyCheckin');await complete('daily_checkin',button);}
  function reset(){state=null;['questTotalXp','questLevelLabel','questLevelBar','questNextLevel','questStreak','questStreakNote','questDoneToday'].forEach(id=>{const el=$('#'+id);if(el)el.textContent='—'});if($('#questChallenges'))$('#questChallenges').innerHTML='<div class="empty-state">Log in to start your daily quests.</div>';if($('#questLeaderboard'))$('#questLeaderboard').innerHTML='';if($('#questAchievements'))$('#questAchievements').innerHTML='';}
  window.questLoad=load;window.questRefresh=load;window.questCheckin=checkin;window.questReset=reset;window.questUpdateMini=updateMini;
  document.addEventListener('DOMContentLoaded',()=>{setTimeout(load,900);});
  // app.js is loaded first and may finish its session check after this file is parsed.
  setTimeout(load,1500);
})();
