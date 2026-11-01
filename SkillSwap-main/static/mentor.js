(() => {
  const $ = (s, r=document) => r.querySelector(s);
  const $$ = (s, r=document) => [...r.querySelectorAll(s)];
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const apiCall = async (url, options={}) => {
    const res = await fetch(url, {credentials:'include', cache:'no-store', ...options, headers:{...(options.body?{'Content-Type':'application/json'}:{}), ...(options.headers||{})}});
    let data={}; try { data=await res.json(); } catch {}
    if(!res.ok) throw new Error(data.error || 'Something went wrong. Please try again.');
    return data;
  };
  let activeQuiz=null, activeInterview=null, historyCache=[];
  const topicFromProfile = () => {
    const user = currentUser;
    return (user?.learn?.[0] || user?.teach?.[0] || 'Python');
  };
  function switchTab(name){
    $$('.mentor-tab').forEach(b=>b.classList.toggle('active',b.dataset.mentorTab===name));
    $$('.mentor-pane').forEach(p=>p.classList.toggle('active',p.id===`mentor-pane-${name}`));
    if(name==='history') loadHistory();
  }
  function setTopicDefaults(data){
    const skills=[...(data.skills||[])];
    const focus=$('#mentorFocus'); if(focus) focus.textContent=skills.length?`Suggested focus: ${skills.slice(0,4).join(' · ')}`:'Add a skill to your profile to personalise practice.';
    const suggestions=$('#mentorSkillSuggestions');
    if(suggestions) suggestions.innerHTML=skills.length?`<small>YOUR PROFILE SKILLS</small><div>${skills.slice(0,8).map(s=>`<button type="button" class="mentor-skill-chip" data-mentor-skill="${esc(s)}">${esc(s)}</button>`).join('')}</div>`:'<small>Add skills in My profile to see suggestions here.</small>';
    if(!$('#mentorQuizTopic').value) $('#mentorQuizTopic').value=skills[0]||'Python';
    if(!$('#mentorInterviewTopic').value) $('#mentorInterviewTopic').value=skills[0]||'Python Developer';
    suggestions?.querySelectorAll('[data-mentor-skill]').forEach(b=>b.addEventListener('click',()=>{$('#mentorQuizTopic').value=b.dataset.mentorSkill;$('#mentorInterviewTopic').value=b.dataset.mentorSkill;}));
    historyCache=data.attempts||[]; renderHistory(historyCache);
  }
  async function loadMentor(){
    if(!currentUser){
      $('#mentorFocus').textContent='Log in to personalise your practice and save results.';
      $('#mentorHistoryList').innerHTML='<p class="muted">Log in to save quizzes and interview practice to your account.</p>';
      if($('#mentorQuizTopic')&&!$('#mentorQuizTopic').value) $('#mentorQuizTopic').value='Python';
      if($('#mentorInterviewTopic')&&!$('#mentorInterviewTopic').value) $('#mentorInterviewTopic').value='Python Developer';
      return;
    }
    try { const data=await apiCall('/api/mentor/context'); setTopicDefaults(data); }
    catch(e){ if(window.toast) toast(e.message,true); }
  }
  function renderHistory(rows){
    const box=$('#mentorHistoryList'); if(!box)return;
    if(!currentUser){box.innerHTML='<p class="muted">Log in to view saved sessions.</p>';return;}
    if(!rows?.length){box.innerHTML='<div class="mentor-empty compact"><span>▤</span><h3>Your progress starts here</h3><p>Complete a quiz or interview practice session and it will appear here.</p></div>';return;}
    box.innerHTML=rows.map(a=>`<article class="mentor-history-item"><span class="mentor-history-icon">${a.mode==='quiz'?'✎':'◉'}</span><div><b>${esc(a.topic)}</b><small>${a.mode==='quiz'?'Knowledge quiz':'Interview practice'} · ${a.created_at?new Date(a.created_at).toLocaleString():''}</small><p>${esc(a.feedback||'Practice completed.')}</p></div><strong>${a.mode==='quiz'?`${a.score}/${a.total}`:`${a.score}/100`}</strong></article>`).join('');
  }
  async function loadHistory(){
    if(!currentUser){renderHistory([]);return;}
    try{const d=await apiCall('/api/mentor/context');historyCache=d.attempts||[];renderHistory(historyCache);}catch(e){$('#mentorHistoryList').innerHTML=`<p class="error-note">${esc(e.message)}</p>`;}
  }
  function renderQuiz(quiz){
    const box=$('#mentorQuizOutput');
    box.innerHTML=`<div class="mentor-quiz-head"><div><span class="eyebrow">${esc(quiz.level)} PRACTICE</span><h2>${esc(quiz.topic)} quiz</h2><p>${quiz.questions.length} questions · Choose one answer for each question.</p></div><span class="mentor-quiz-count">${quiz.questions.length} Q</span></div><form id="mentorQuizAnswerForm"><div class="mentor-question-list">${quiz.questions.map((q,i)=>`<fieldset class="mentor-question"><legend><span>Q${i+1}</span>${esc(q.prompt)}</legend><div class="mentor-options">${q.options.map((o,j)=>`<label><input type="radio" name="q${q.id}" value="${j}" required><span>${esc(o)}</span></label>`).join('')}</div></fieldset>`).join('')}</div><button class="primary-button full-width" type="submit">Submit answers & see results ↗</button></form><p class="mentor-disclaimer">Your result and explanations will be saved to your SkillSwap account.</p>`;
    $('#mentorQuizAnswerForm').addEventListener('submit',async e=>{
      e.preventDefault(); if(!activeQuiz)return;
      const answers={}; quiz.questions.forEach(q=>{const selected=$(`input[name="q${q.id}"]:checked`,e.currentTarget);if(selected)answers[q.id]=Number(selected.value);});
      const btn=$('button[type="submit"]',e.currentTarget);btn.disabled=true;btn.textContent='Checking your answers…';
      try{const result=await apiCall('/api/mentor/quiz/submit',{method:'POST',body:JSON.stringify({quiz_id:activeQuiz.quiz_id,answers})});renderQuizResult(result,quiz);if(window.questRefresh)window.questRefresh();}
      catch(err){if(window.toast)toast(err.message,true);btn.disabled=false;btn.textContent='Submit answers & see results ↗';}
    });
  }
  function renderQuizResult(r,quiz){
    const box=$('#mentorQuizOutput');
    box.innerHTML=`<div class="mentor-result-hero"><span>YOUR RESULT</span><strong>${r.percentage}%</strong><b>${r.score} / ${r.total} correct</b><p>${esc(r.feedback)}</p></div><div class="mentor-review-list">${r.details.map((d,i)=>{const q=quiz.questions[i];return `<article class="mentor-review-item ${d.correct?'correct':'incorrect'}"><b>${d.correct?'✓':'↻'} ${esc(q.prompt)}</b><p>${d.correct?'Correct answer':'Correct answer: '+esc(q.options[d.correct_index])}</p><small>${esc(d.explanation)}</small></article>`}).join('')}</div><button type="button" class="primary-button" id="mentorRetryQuiz">Try another quiz ↗</button>`;
    $('#mentorRetryQuiz').addEventListener('click',()=>$('#mentorQuizForm').requestSubmit());
    activeQuiz=null; loadHistory();
  }
  $('#mentorQuizForm')?.addEventListener('submit',async e=>{
    e.preventDefault(); if(!currentUser){window.openAuth?.('login');return;}
    const topic=$('#mentorQuizTopic').value.trim(),level=$('#mentorQuizLevel').value,count=Number($('#mentorQuizCount').value),btn=$('#mentorQuizStart');
    btn.disabled=true;btn.textContent='Preparing questions…';$('#mentorQuizOutput').innerHTML='<div class="mentor-empty"><span class="mentor-spinner">✧</span><h3>Building your practice set</h3><p>Selecting questions for your topic and level…</p></div>';
    try{const d=await apiCall('/api/mentor/quiz',{method:'POST',body:JSON.stringify({topic,level,count})});activeQuiz=d;renderQuiz(d);}
    catch(err){$('#mentorQuizOutput').innerHTML=`<div class="mentor-empty"><h3>Could not create quiz</h3><p>${esc(err.message)}</p></div>`;}
    finally{btn.disabled=false;btn.textContent='Generate my quiz ↗';}
  });
  $('#mentorInterviewForm')?.addEventListener('submit',async e=>{
    e.preventDefault();if(!currentUser){window.openAuth?.('login');return;}
    const topic=$('#mentorInterviewTopic').value.trim(),btn=$('button[type="submit"]',e.currentTarget),box=$('#mentorInterviewOutput');
    btn.disabled=true;btn.textContent='Preparing question…';box.innerHTML='<div class="mentor-empty"><span class="mentor-spinner">◎</span><h3>Preparing your interview</h3><p>Finding a practice question…</p></div>';
    try{const d=await apiCall('/api/mentor/interview/question',{method:'POST',body:JSON.stringify({topic,focus:$('#mentorInterviewFocus').value})});activeInterview={...d,topic};box.innerHTML=`<div class="mentor-interview-question"><div class="eyebrow">QUESTION ${d.question_number} · ${esc(topic)}</div><h2>${esc(d.question)}</h2><p>${esc(d.guidance)}</p></div><form id="mentorInterviewAnswerForm" class="mentor-answer-form"><label for="mentorInterviewAnswer">Your answer</label><textarea id="mentorInterviewAnswer" rows="7" maxlength="4000" minlength="20" required placeholder="Structure your response and include a specific example…"></textarea><div class="mentor-answer-footer"><small>Tip: aim for 4–8 clear sentences.</small><button class="primary-button" type="submit">Review my answer ↗</button></div></form>`;
      $('#mentorInterviewAnswerForm').addEventListener('submit',submitInterviewAnswer);
    }catch(err){box.innerHTML=`<div class="mentor-empty"><h3>Could not prepare question</h3><p>${esc(err.message)}</p></div>`;}
    finally{btn.disabled=false;btn.textContent='Get an interview question ↗';}
  });
  async function submitInterviewAnswer(e){
    e.preventDefault();const answer=$('#mentorInterviewAnswer').value.trim(),btn=$('button[type="submit"]',e.currentTarget);btn.disabled=true;btn.textContent='Reviewing your answer…';
    try{const d=await apiCall('/api/mentor/interview/evaluate',{method:'POST',body:JSON.stringify({topic:activeInterview.topic,question:activeInterview.question,answer})});
      $('#mentorInterviewOutput').innerHTML=`<div class="mentor-result-hero interview-result"><span>COACHING SCORE · ESTIMATE</span><strong>${d.score}<small>/100</small></strong><b>${d.word_count} words analysed</b><p>${esc(d.feedback)}</p></div><div class="mentor-rubric">${d.rubric.map(r=>`<div><span>${esc(r.name)}</span><b>${r.score}/${r.max}</b><i><em style="width:${Math.round(r.score/r.max*100)}%"></em></i></div>`).join('')}</div><div class="mentor-coach-note"><b>Keep improving</b><p>${esc(d.note)}</p></div><button type="button" class="primary-button" id="mentorNextInterview">Practise another question ↗</button>`;
      $('#mentorNextInterview').addEventListener('click',()=>$('#mentorInterviewForm').requestSubmit());loadHistory();
    }catch(err){if(window.toast)toast(err.message,true);btn.disabled=false;btn.textContent='Review my answer ↗';}
  }
  $('#mentorTutorForm')?.addEventListener('submit',sendTutor);
  async function sendTutor(e){
    e.preventDefault();const input=$('#mentorTutorInput'),question=input.value.trim();if(!question)return;
    if(!currentUser){window.openAuth?.('login');return;}
    const area=$('#mentorTutorMessages');area.insertAdjacentHTML('beforeend',`<div class="mentor-chat-bubble user"><b>You</b><p>${esc(question)}</p></div>`);input.value='';area.insertAdjacentHTML('beforeend','<div class="mentor-chat-bubble bot mentor-thinking"><b>SkillBuddy</b><p>Thinking through that with you…</p></div>');area.scrollTop=area.scrollHeight;
    try{const d=await apiCall('/api/assistant',{method:'POST',body:JSON.stringify({question:`You are acting as my personal learning mentor. My current learning context is ${$('#mentorQuizTopic')?.value||topicFromProfile()}. Please explain in simple steps, include a short practical example, and finish with one small exercise. My question: ${question}`})});$('.mentor-thinking',area)?.remove();area.insertAdjacentHTML('beforeend',`<div class="mentor-chat-bubble bot"><b>SkillBuddy · ${d.mode==='ai'?'AI-assisted':'Built-in mentor'}</b><p>${esc(d.answer).replace(/\n/g,'<br>')}</p></div>`);}
    catch(err){$('.mentor-thinking',area)?.remove();area.insertAdjacentHTML('beforeend',`<div class="mentor-chat-bubble bot"><b>SkillBuddy</b><p>${esc(err.message)}</p></div>`);}
    area.scrollTop=area.scrollHeight;
  }
  $$('.mentor-tab').forEach(b=>b.addEventListener('click',()=>switchTab(b.dataset.mentorTab)));
  $$('[data-mentor-tab]').filter(b=>!b.classList.contains('mentor-tab')).forEach(b=>b.addEventListener('click',()=>switchTab(b.dataset.mentorTab)));
  $$('[data-mentor-prompt]').forEach(b=>b.addEventListener('click',()=>{$('#mentorTutorInput').value=b.dataset.mentorPrompt;$('#mentorTutorInput').focus();}));
  $('#mentorHistoryRefresh')?.addEventListener('click',loadHistory);
  window.mentorLoad=loadMentor;
})();
