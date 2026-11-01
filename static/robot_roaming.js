/* SkillBuddy roaming companion. All behaviour is local to this browser tab.
   It reacts to coarse UI activity (view changes, scrolling and pointer presence),
   never reads form contents or records browsing history. */
(() => {
  const widget = document.getElementById('assistantWidget');
  const toggle = document.getElementById('assistantToggle');
  const panel = document.getElementById('assistantPanel');
  const speech = document.getElementById('petSpeech');
  const status = document.getElementById('petStatusLine');
  const roamButton = document.getElementById('petRoamToggle');
  const robot = widget?.querySelector('.robot-pet');
  if (!widget || !toggle || !panel || !speech || !robot) return;

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const storeKey = 'skillswap_pet_roaming';
  let roaming = localStorage.getItem(storeKey) !== 'off';
  let lastActivity = Date.now();
  let moveTimer = 0;
  let moodResetTimer = 0;
  let moodCycleTimer = 0;
  let speechTimer = 0;
  let lastPointerAt = 0;
  let home = null;
  let currentMood = 'idle';

  const suggestions = {
    overview: ['A tiny goal for today: teach one thing you learned this week. ✨', 'Your next adventure could be a new skill match. Want to explore?', 'Psst… a 15-minute learning sprint is a great start.'],
    discover: ['Try adding both a skill to teach and a skill to learn for better matches.', 'Look for someone whose learning goal complements yours.'],
    matches: ['A good skill swap works both ways. Check what you can teach each other.', 'Send a friendly exchange proposal when you find a promising match.'],
    rooms: ['Learning together works best when everyone gets a turn to explain.', 'Ask your room a quick question to get the discussion moving.'],
    quest: ['One small quest today can keep your learning streak alive. 🔥', 'Try a challenge that stretches you just a little.'],
    community: ['Share a small win or a project-in-progress with the community.', 'A thoughtful comment can help another learner keep going.'],
    mentor: ['Ask me to explain a tricky concept with a simple example.', 'Try a short quiz after studying. Retrieval helps learning stick.'],
    arena: ['Show your process in your competition submission, not just the final result.', 'Explore other entries and leave constructive feedback.'],
    profile: ['Keep your teach and learn skills up to date so people can find you.', 'A clear profile makes it easier to start a great skill exchange.']
  };
  const random = list => list[Math.floor(Math.random() * list.length)];
  const activeView = () => document.querySelector('.view.active')?.id?.replace('view-', '') || 'overview';
  const panelOpen = () => panel.classList.contains('open');
  const modalOpen = () => !!document.querySelector('.modal-backdrop.open');
  const setStatus = text => { if (status) status.textContent = text; };

  function say(message, duration = 5600) {
    speech.replaceChildren();
    const text = document.createElement('span');
    text.textContent = message;
    const sparkle = document.createElement('b');
    sparkle.textContent = ' ✦';
    speech.append(text, sparkle);
    speech.classList.add('show');
    clearTimeout(speechTimer);
    speechTimer = setTimeout(() => speech.classList.remove('show'), duration);
  }

  function mood(name, line, duration = 5200) {
    widget.classList.remove('pet-happy','pet-thinking','pet-sleepy','pet-curious','pet-crying','pet-waving');
    currentMood = name;
    if (name !== 'idle') widget.classList.add('pet-' + name);
    if (line) setStatus(line);
    clearTimeout(moodResetTimer);
    if (name !== 'idle') moodResetTimer = setTimeout(() => {
      widget.classList.remove('pet-happy','pet-thinking','pet-sleepy','pet-curious','pet-crying','pet-waving');
      currentMood = 'idle';
      setStatus(roaming ? 'Wandering nearby · here if you need me' : 'Roaming paused · here if you need me');
    }, duration);
  }

  function viewportBounds() {
    const r = toggle.getBoundingClientRect();
    return { w: r.width || 190, h: r.height || 70, vw: window.innerWidth, vh: window.innerHeight };
  }

  function saveHome() {
    const r = widget.getBoundingClientRect();
    home = { x: Math.max(12, window.innerWidth - r.width - 22), y: Math.max(12, window.innerHeight - r.height - 20) };
  }

  function positionAt(x, y) {
    const {w,h,vw,vh} = viewportBounds();
    const left = Math.max(10, Math.min(vw - w - 10, x));
    const top = Math.max(10, Math.min(vh - h - 10, y));
    widget.classList.add('pet-roaming');
    widget.style.left = left + 'px';
    widget.style.top = top + 'px';
    widget.style.right = 'auto';
    widget.style.bottom = 'auto';
    placePanel();
    placeSpeech();
  }

  function placePanel() {
    if (!panelOpen()) return;
    const r = toggle.getBoundingClientRect();
    const width = Math.min(380, window.innerWidth - 24);
    const height = Math.min(590, window.innerHeight - 100);
    const left = Math.max(12, Math.min(window.innerWidth - width - 12, r.left + r.width - width));
    const preferAbove = r.top > height + 95;
    const top = preferAbove ? Math.max(12, r.top - height - 14) : Math.min(window.innerHeight - height - 12, r.bottom + 14);
    panel.style.position = 'fixed';
    panel.style.left = left + 'px';
    panel.style.right = 'auto';
    panel.style.top = top + 'px';
    panel.style.bottom = 'auto';
    placeSpeech();
  }

  function placeSpeech() {
    if (!widget.classList.contains('pet-roaming')) return;
    const r = toggle.getBoundingClientRect();
    const width = Math.min(230, window.innerWidth - 28);
    const left = Math.max(14, Math.min(window.innerWidth - width - 14, r.left + r.width - width));
    const top = r.top > 82 ? r.top - 62 : Math.min(window.innerHeight - 58, r.bottom + 8);
    speech.style.left = left + 'px'; speech.style.top = Math.max(8, top) + 'px';
  }

  function returnHome() {
    if (!home) saveHome();
    if (home) positionAt(home.x, home.y);
  }

  function safeDestinations() {
    const {w,h,vw,vh} = viewportBounds();
    const pad = 12;
    const right = vw - w - pad;
    const bottom = vh - h - pad;
    // Keep the robot around the perimeter so it doesn't cover the main reading area.
    return [
      [pad, bottom], [right, bottom], [pad, Math.max(pad, bottom * .52)],
      [right, Math.max(pad, bottom * .52)], [Math.max(pad, vw*.08), pad],
      [Math.max(pad, right*.5), pad], [Math.max(pad, right*.78), bottom],
      [right, Math.max(pad, vh*.18)]
    ].filter(([x,y]) => x >= 0 && y >= 0);
  }

  function wander() {
    if (!roaming || reduceMotion.matches || document.visibilityState !== 'visible' || panelOpen() || modalOpen()) return;
    const choices = safeDestinations();
    if (choices.length) {
      const current = toggle.getBoundingClientRect();
      const far = choices.filter(([x,y]) => Math.abs(x-current.left) + Math.abs(y-current.top) > 170);
      const [x,y] = random(far.length ? far : choices);
      positionAt(x,y);
      const lines = ['Just taking a little stroll around your learning space. 🤖','I am exploring the page… beep boop!','Found a nice spot to cheer you on.','I am keeping an eye out for your next learning adventure.'];
      mood(random(['curious','waving','happy']), 'Exploring SkillSwap');
      if (Math.random() < .72) say(random(lines), 4300);
      if (Math.random() < .38) setTimeout(() => { if (!panelOpen() && document.visibilityState === 'visible') say(random(suggestions[activeView()] || suggestions.overview)); }, 2600);
    }
  }

  function scheduleWander(delay) {
    clearTimeout(moveTimer);
    if (!roaming || reduceMotion.matches) return;
    moveTimer = setTimeout(() => {
      const idleFor = Date.now() - lastActivity;
      if (idleFor > 14000 && !panelOpen() && !modalOpen() && document.visibilityState === 'visible') wander();
      scheduleWander(18000 + Math.random()*15000);
    }, delay);
  }

  function noteActivity() {
    lastActivity = Date.now();
    if (currentMood === 'sleepy') mood('curious','I noticed you are back!');
    clearTimeout(moveTimer);
    // On interaction, move back to the usual dock so the controls are predictable.
    if (!panelOpen() && !modalOpen()) returnHome();
    scheduleWander(19000 + Math.random()*9000);
  }

  function trackGaze(event) {
    const now = Date.now();
    if (now - lastPointerAt < 90 || panelOpen()) return;
    lastPointerAt = now;
    const r = robot.getBoundingClientRect();
    const dx = Math.max(-1, Math.min(1, (event.clientX - (r.left+r.width/2)) / Math.max(1,r.width)));
    const dy = Math.max(-1, Math.min(1, (event.clientY - (r.top+r.height/2)) / Math.max(1,r.height)));
    robot.querySelectorAll('.pet-eye').forEach(eye => { eye.style.translate = `${dx*1.8}px ${dy*1.2}px`; });
  }

  function updateRoamButton() {
    if (!roamButton) return;
    roamButton.textContent = roaming ? '✧ Roaming: On' : '✧ Roaming: Off';
    roamButton.setAttribute('aria-pressed', String(roaming));
  }

  roamButton?.addEventListener('click', () => {
    roaming = !roaming;
    localStorage.setItem(storeKey, roaming ? 'on' : 'off');
    updateRoamButton();
    if (roaming) { saveHome(); mood('happy','Roaming enabled'); say('Yay! I will wander gently when you take a pause.'); scheduleWander(19000); }
    else { clearTimeout(moveTimer); returnHome(); mood('idle','Roaming paused · tap me whenever you need help'); say('I will stay right here. You can turn roaming back on anytime.'); }
  });

  // A page-aware hint follows navigation, without inspecting what the user types.
  document.addEventListener('click', event => {
    const nav = event.target.closest('[data-view], [data-open-view]');
    if (!nav) return;
    noteActivity();
    const destination = nav.dataset.view || nav.dataset.openView;
    if (destination) setTimeout(() => {
      if (!panelOpen() && document.visibilityState === 'visible' && Date.now()-lastActivity < 4500) {
        const options = suggestions[destination];
        if (options) say(random(options), 5200);
      }
    }, 1300);
  });
  ['pointerdown','keydown','wheel','touchstart'].forEach(type => document.addEventListener(type, noteActivity, {passive:true}));
  document.addEventListener('pointermove', trackGaze, {passive:true});
  window.addEventListener('resize', () => { saveHome(); if (panelOpen()) placePanel(); else returnHome(); });
  window.addEventListener('scroll', () => { if (panelOpen()) placePanel(); }, {passive:true});
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') { noteActivity(); scheduleWander(22000); }
    else clearTimeout(moveTimer);
  });
  toggle.addEventListener('click', () => { clearTimeout(moveTimer); setTimeout(() => { if (panelOpen()) placePanel(); else { returnHome(); scheduleWander(26000); } }, 40); });
  document.getElementById('assistantClose')?.addEventListener('click', () => setTimeout(() => { returnHome(); scheduleWander(22000); }, 40));

  // Gentle personality moments. The sleepy/teary states are playful expressions, never guilt prompts.
  const moods = [
    () => { mood('happy','Feeling cheerful!'); say('You are making this learning space brighter. 💜'); },
    () => { mood('curious','Curious little robot'); say('What new skill are you curious about today?'); },
    () => { mood('sleepy','Taking a tiny robot recharge'); say('Even robots need a micro-break. Stretch your shoulders if you like.'); },
    () => { mood('crying','A tiny dramatic robot moment'); say('Oh no, I dropped a digital tear. Want a hint with something tricky?'); },
    () => { mood('waving','Here to cheer you on'); say('Beep boop! Your next small step is waiting.'); }
  ];
  function scheduleMood() {
    clearTimeout(moodCycleTimer);
    moodCycleTimer = setTimeout(() => {
      if (!panelOpen() && document.visibilityState === 'visible' && Date.now()-lastActivity > 18000 && Math.random() < .72) random(moods)();
      scheduleMood();
    }, 38000 + Math.random()*30000);
  }

  updateRoamButton();
  saveHome();
  setStatus(roaming ? 'Wandering nearby · here if you need me' : 'Roaming paused · here if you need me');
  if (roaming && !reduceMotion.matches) scheduleWander(21000);
  scheduleMood();
  reduceMotion.addEventListener?.('change', () => { if (reduceMotion.matches) { clearTimeout(moveTimer); returnHome(); } else if (roaming) scheduleWander(22000); });
})();
