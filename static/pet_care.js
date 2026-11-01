/* SkillBuddy Virtual Pet: account-backed care stats with gentle, non-punitive mechanics. */
(() => {
  const root = document.getElementById('petCarePanel');
  if (!root) return;
  const $ = id => document.getElementById(id);
  const loginHint = $('petCareLogin');
  const message = $('petCareMessage');
  let busy = false;
  let loggedIn = false;
  let state = null;
  const api = async (url, options = {}) => {
    const response = await fetch(url, {credentials:'same-origin', ...options, headers:{'Content-Type':'application/json', ...(options.headers||{})}});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) { const error = new Error(data.error || 'Something went wrong.'); error.status = response.status; throw error; }
    return data;
  };
  const setMeter = (valueId, barId, value) => {
    $(valueId).textContent = `${value}/100`;
    $(barId).style.width = `${Math.max(0, Math.min(100, value))}%`;
    $(barId).parentElement.setAttribute('aria-label', `${value} out of 100`);
  };
  function render(pet) {
    state = pet;
    setMeter('petHappinessValue','petHappinessBar',pet.happiness);
    setMeter('petEnergyValue','petEnergyBar',pet.energy);
    setMeter('petFriendshipValue','petFriendshipBar',pet.friendship);
    $('petBondLevel').textContent = pet.bond;
    const labels = {joyful:'Feeling joyful ✨',content:'Feeling content 😊','needs-a-cuddle':'Could use a cuddle 💜',sleepy:'A little sleepy 😴'};
    $('petMoodLabel').textContent = labels[pet.mood] || 'Here with you';
    const widget = document.getElementById('assistantWidget');
    if (widget) {
      widget.classList.remove('pet-happy','pet-sleepy','pet-curious','pet-waving','pet-crying');
      if (pet.mood === 'sleepy') widget.classList.add('pet-sleepy');
      else if (pet.mood === 'joyful') widget.classList.add('pet-happy');
    }
    const treat = $('petTreatButton');
    treat.disabled = !pet.treat_available;
    $('petTreatStatus').textContent = pet.treat_available ? 'Once a day' : 'Come back tomorrow';
    root.querySelectorAll('[data-pet-action="play"]').forEach(button => button.disabled = pet.energy < 15);
    root.querySelectorAll('[data-pet-action="talk"]').forEach(button => button.disabled = pet.energy < 3);
    root.querySelectorAll('[data-pet-action="cuddle"]').forEach(button => button.disabled = pet.energy < 2);
  }
  async function refresh() {
    try {
      const data = await api('/api/pet/state');
      loggedIn = true; loginHint.hidden = true; root.querySelectorAll('[data-pet-action]').forEach(b=>b.disabled=false);
      render(data.pet);
      message.textContent = 'Your buddy recharges gently while you are away. Care is for fun—nothing is lost if you take a break.';
    } catch (error) {
      if (error.status === 401) {
        loggedIn = false; loginHint.hidden = false;
        ['petHappinessValue','petEnergyValue','petFriendshipValue'].forEach(id=>$(id).textContent='—');
        ['petHappinessBar','petEnergyBar','petFriendshipBar'].forEach(id=>$(id).style.width='0%');
        $('petBondLevel').textContent='Guest mode'; $('petMoodLabel').textContent='Waiting to meet you';
        root.querySelectorAll('[data-pet-action]').forEach(b=>b.disabled=true);
      } else { message.textContent = error.message; }
    }
  }
  async function act(action, button) {
    if (busy || !loggedIn) return;
    busy = true; button?.classList.add('is-loading');
    try {
      const data = await api('/api/pet/action',{method:'POST',body:JSON.stringify({action})});
      render(data.pet); message.textContent = data.message;
      const widget = document.getElementById('assistantWidget');
      if (widget) {
        widget.classList.remove('pet-happy','pet-sleepy','pet-curious','pet-waving','pet-crying');
        widget.classList.add(action==='rest'?'pet-sleepy':'pet-happy');
        setTimeout(()=>widget.classList.remove('pet-happy','pet-sleepy'),2200);
      }
      const speech = document.getElementById('petSpeech');
      if (speech) { speech.textContent = data.message; speech.classList.add('show'); setTimeout(()=>speech.classList.remove('show'),3800); }
    } catch (error) { message.textContent = error.message; }
    finally { busy = false; button?.classList.remove('is-loading'); }
  }
  root.addEventListener('click', event => {
    const button = event.target.closest('[data-pet-action]');
    if (button) act(button.dataset.petAction,button);
  });
  $('petCareRefresh')?.addEventListener('click',refresh);
  $('petCheer')?.addEventListener('click', async () => {
    if (!loggedIn) { await refresh(); return; }
    const button = $('petCheer'); await act('cuddle',button);
  });
  // The assistant panel opens independently; load account state when the visitor opens it.
  $('assistantToggle')?.addEventListener('click',()=>{ if (document.getElementById('assistantPanel')?.classList.contains('open')) refresh(); });
  window.addEventListener('skillswap:auth-changed',refresh);
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible' && loggedIn) refresh();});
  refresh();
})();
